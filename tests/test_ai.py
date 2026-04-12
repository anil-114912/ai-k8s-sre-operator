"""Tests for AI RCA engine, remediation engine, and LLM client."""
from __future__ import annotations

import json
import os
import pytest

os.environ["DEMO_MODE"] = "1"

from ai.llm import LLMClient
from ai.rca_engine import RCAEngine
from ai.remediation_engine import RemediationEngine
from models.incident import Incident, IncidentType, Severity, IncidentStatus
from models.remediation import SafetyLevel


def make_test_incident(**kwargs) -> Incident:
    """Create a test incident with sensible defaults."""
    defaults = dict(
        title="CrashLoopBackOff: payment-api missing secret",
        incident_type=IncidentType.crash_loop,
        severity=Severity.critical,
        namespace="production",
        workload="payment-api",
        pod_name="payment-api-abc-xyz",
    )
    defaults.update(kwargs)
    return Incident(**defaults)


class TestLLMClient:
    """Tests for the LLMClient rule-based fallback."""

    def test_chat_returns_string(self):
        """chat() should always return a non-empty string."""
        client = LLMClient()
        response = client.chat(system="You are an SRE.", user="Analyze this crash.")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_rca_fallback_is_valid_json(self):
        """Rule-based RCA response should be valid JSON."""
        client = LLMClient()
        client.demo_mode = True
        response = client.chat(
            system="You are an SRE doing RCA.",
            user="CrashLoopBackOff payment-api missing secret db-credentials",
        )
        data = json.loads(response)
        assert "root_cause" in data
        assert "confidence" in data
        assert "explanation" in data

    def test_rca_fallback_confidence_in_range(self):
        """Confidence score should be between 0 and 1."""
        client = LLMClient()
        client.demo_mode = True
        response = client.chat(
            system="RCA",
            user="OOMKilled analytics-worker memory limit exceeded",
        )
        data = json.loads(response)
        assert 0.0 <= data["confidence"] <= 1.0

    def test_remediation_fallback_is_valid_json(self):
        """Rule-based remediation response should be valid JSON."""
        client = LLMClient()
        client.demo_mode = True
        response = client.chat(
            system="You are an SRE generating remediation plans.",
            user="Remediation for CrashLoopBackOff payment-api missing secret",
        )
        data = json.loads(response)
        assert "steps" in data
        assert isinstance(data["steps"], list)
        assert len(data["steps"]) > 0

    def test_detects_oom_incident_type(self):
        """Should correctly detect OOMKilled type from user text."""
        client = LLMClient()
        detected = client._detect_incident_type_from_text("OOMKilled container analytics-worker")
        assert detected == "OOMKilled"

    def test_detects_crashloop_incident_type(self):
        """Should correctly detect CrashLoopBackOff type from user text."""
        client = LLMClient()
        detected = client._detect_incident_type_from_text("CrashLoopBackOff payment-api")
        assert detected == "CrashLoopBackOff"

    def test_realistic_crash_loop_explanation(self):
        """Rule-based CrashLoop response should contain realistic detail."""
        client = LLMClient()
        client.demo_mode = True
        response = client._get_rca_response("CrashLoopBackOff")
        data = json.loads(response)
        # Should contain substantive explanation, not placeholder text
        assert len(data["explanation"]) > 100
        assert "secret" in data["explanation"].lower() or "config" in data["explanation"].lower()


class TestRCAEngine:
    """Tests for the RCAEngine."""

    def test_analyze_returns_enriched_incident(self):
        """analyze() should return an Incident with root_cause populated."""
        engine = RCAEngine()
        incident = make_test_incident()
        result = engine.analyze(
            incident=incident,
            cluster_state={"events": [], "pods": []},
        )
        assert result.root_cause is not None
        assert len(result.root_cause) > 0

    def test_analyze_sets_status_to_analyzed(self):
        """After analysis, status should be 'analyzed'."""
        engine = RCAEngine()
        incident = make_test_incident()
        result = engine.analyze(incident=incident, cluster_state={})
        assert result.status == IncidentStatus.analyzed

    def test_analyze_populates_confidence(self):
        """After analysis, confidence should be set and in [0, 1]."""
        engine = RCAEngine()
        incident = make_test_incident()
        result = engine.analyze(incident=incident, cluster_state={})
        assert result.confidence is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_analyze_with_oom_incident(self):
        """analyze() should correctly handle OOMKilled incidents."""
        engine = RCAEngine()
        incident = make_test_incident(
            title="OOMKilled: analytics-worker",
            incident_type=IncidentType.oom_killed,
            severity=Severity.high,
            workload="analytics-worker",
        )
        result = engine.analyze(incident=incident, cluster_state={})
        assert result.root_cause is not None
        assert result.status == IncidentStatus.analyzed

    def test_analyze_adds_ai_evidence(self):
        """analyze() should add AI analysis as an evidence item."""
        engine = RCAEngine()
        incident = make_test_incident()
        result = engine.analyze(incident=incident, cluster_state={})
        sources = [ev.source for ev in (result.evidence or [])]
        assert "ai_rca" in sources


class TestRemediationEngine:
    """Tests for the RemediationEngine."""

    def test_generate_plan_returns_plan(self):
        """generate_plan() should return a non-empty RemediationPlan."""
        engine = RemediationEngine()
        incident = make_test_incident(
            root_cause="Missing secret db-credentials",
            ai_explanation="The app cannot find the secret.",
        )
        plan = engine.generate_plan(incident)
        assert plan is not None
        assert plan.incident_id == incident.id
        assert len(plan.steps) > 0

    def test_plan_has_valid_safety_levels(self):
        """All steps should have valid safety levels."""
        engine = RemediationEngine()
        incident = make_test_incident()
        plan = engine.generate_plan(incident)
        valid_levels = {SafetyLevel.auto_fix, SafetyLevel.approval_required, SafetyLevel.suggest_only}
        for step in plan.steps:
            assert step.safety_level in valid_levels

    def test_plan_has_ordered_steps(self):
        """Steps should have sequential order values."""
        engine = RemediationEngine()
        incident = make_test_incident()
        plan = engine.generate_plan(incident)
        orders = [s.order for s in plan.steps]
        assert orders == sorted(orders)

    def test_oom_plan_has_patch_limits_step(self):
        """OOMKill remediation should include a patch_limits step."""
        engine = RemediationEngine()
        incident = make_test_incident(
            incident_type=IncidentType.oom_killed,
            severity=Severity.high,
            workload="analytics-worker",
            root_cause="Memory limit too low",
        )
        plan = engine.generate_plan(incident)
        actions = [s.action for s in plan.steps]
        assert "patch_limits" in actions

    def test_crashloop_plan_has_restart_step(self):
        """CrashLoop remediation should include a rollout_restart step."""
        engine = RemediationEngine()
        incident = make_test_incident()
        plan = engine.generate_plan(incident)
        actions = [s.action for s in plan.steps]
        assert "rollout_restart" in actions

    def test_overall_safety_is_most_restrictive(self):
        """Overall safety level should reflect the most restrictive step."""
        engine = RemediationEngine()
        incident = make_test_incident()
        plan = engine.generate_plan(incident)
        # If any step is suggest_only, overall should be suggest_only
        # If any step is approval_required, overall should be at least approval_required
        step_levels = [s.safety_level for s in plan.steps]
        if SafetyLevel.suggest_only in step_levels:
            assert plan.overall_safety_level == SafetyLevel.suggest_only
        elif SafetyLevel.approval_required in step_levels:
            assert plan.overall_safety_level in (SafetyLevel.approval_required, SafetyLevel.suggest_only)
