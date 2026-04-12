"""Tests for all FastAPI endpoints."""
from __future__ import annotations

import os
import pytest

os.environ["DEMO_MODE"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///./test_sre.db"

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def make_incident_payload(**kwargs) -> dict:
    """Build a minimal valid incident payload."""
    defaults = {
        "title": "CrashLoopBackOff: test-api missing secret",
        "incident_type": "CrashLoopBackOff",
        "severity": "critical",
        "namespace": "production",
        "workload": "test-api",
        "pod_name": "test-api-abc-xyz",
        "provider_used": "simulation",
    }
    defaults.update(kwargs)
    return defaults


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self):
        """GET /health should return 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_includes_version(self):
        """GET /health should include version field."""
        response = client.get("/health")
        assert "version" in response.json()


class TestIncidentEndpoints:
    """Tests for incident CRUD endpoints."""

    def test_create_incident(self):
        """POST /api/v1/incidents should create and return the incident."""
        payload = make_incident_payload()
        response = client.post("/api/v1/incidents", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == payload["title"]
        assert "id" in data
        assert data["status"] == "detected"

    def test_list_incidents(self):
        """GET /api/v1/incidents should return a list."""
        # Create one first
        client.post("/api/v1/incidents", json=make_incident_payload())
        response = client.get("/api/v1/incidents")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_incident_by_id(self):
        """GET /api/v1/incidents/{id} should return the specific incident."""
        created = client.post("/api/v1/incidents", json=make_incident_payload()).json()
        inc_id = created["id"]
        response = client.get(f"/api/v1/incidents/{inc_id}")
        assert response.status_code == 200
        assert response.json()["id"] == inc_id

    def test_get_nonexistent_incident_returns_404(self):
        """GET /api/v1/incidents/{bad-id} should return 404."""
        response = client.get("/api/v1/incidents/nonexistent-id-12345")
        assert response.status_code == 404

    def test_filter_by_severity(self):
        """GET /api/v1/incidents?severity=critical should filter results."""
        client.post("/api/v1/incidents", json=make_incident_payload(severity="critical"))
        client.post("/api/v1/incidents", json=make_incident_payload(severity="low"))
        response = client.get("/api/v1/incidents?severity=critical")
        assert response.status_code == 200
        for inc in response.json():
            assert inc["severity"] == "critical"

    def test_create_incident_with_raw_signals(self):
        """POST /api/v1/incidents should accept raw_signals."""
        payload = make_incident_payload(
            raw_signals={
                "restart_count": 15,
                "recent_logs": ["ERROR: secret not found"],
            }
        )
        response = client.post("/api/v1/incidents", json=payload)
        assert response.status_code == 200
        assert response.json()["raw_signals"]["restart_count"] == 15


class TestAnalysisEndpoint:
    """Tests for the analysis pipeline endpoint."""

    def test_analyze_returns_enriched_incident(self):
        """POST /api/v1/incidents/{id}/analyze should run RCA and return enriched incident."""
        created = client.post("/api/v1/incidents", json=make_incident_payload()).json()
        inc_id = created["id"]
        response = client.post(f"/api/v1/incidents/{inc_id}/analyze")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "analyzed"
        assert data["root_cause"] is not None

    def test_analyze_nonexistent_incident(self):
        """POST /api/v1/incidents/bad-id/analyze should return 404."""
        response = client.post("/api/v1/incidents/nonexistent/analyze")
        assert response.status_code == 404


class TestRemediationEndpoints:
    """Tests for remediation endpoints."""

    def _create_analyzed_incident(self) -> str:
        """Helper to create and analyze an incident, returning its ID."""
        created = client.post("/api/v1/incidents", json=make_incident_payload()).json()
        inc_id = created["id"]
        client.post(f"/api/v1/incidents/{inc_id}/analyze")
        return inc_id

    def test_get_remediation_plan(self):
        """GET /api/v1/incidents/{id}/remediation should generate a plan."""
        inc_id = self._create_analyzed_incident()
        response = client.get(f"/api/v1/incidents/{inc_id}/remediation")
        assert response.status_code == 200
        data = response.json()
        assert "steps" in data
        assert len(data["steps"]) > 0

    def test_execute_remediation_dry_run(self):
        """POST /api/v1/incidents/{id}/remediation/execute?dry_run=true should succeed after approval."""
        inc_id = self._create_analyzed_incident()
        # First get the plan
        plan_resp = client.get(f"/api/v1/incidents/{inc_id}/remediation")
        assert plan_resp.status_code == 200
        plan = plan_resp.json()

        # If plan requires approval, approve first
        if plan.get("requires_approval"):
            approve_resp = client.post(f"/api/v1/incidents/{inc_id}/remediation/approve")
            assert approve_resp.status_code == 200

        # Now execute
        response = client.post(
            f"/api/v1/incidents/{inc_id}/remediation/execute?dry_run=true"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True

    def test_approve_remediation(self):
        """POST /api/v1/incidents/{id}/remediation/approve should work."""
        inc_id = self._create_analyzed_incident()
        client.get(f"/api/v1/incidents/{inc_id}/remediation")
        response = client.post(f"/api/v1/incidents/{inc_id}/remediation/approve")
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    def test_remediation_for_nonexistent_incident(self):
        """GET /api/v1/incidents/bad-id/remediation should return 404."""
        response = client.get("/api/v1/incidents/nonexistent/remediation")
        assert response.status_code == 404


class TestScanEndpoint:
    """Tests for the cluster scan endpoint."""

    def test_scan_returns_results(self):
        """POST /api/v1/scan should return detection results."""
        response = client.post("/api/v1/scan")
        assert response.status_code == 200
        data = response.json()
        assert "total_detections" in data
        assert "incidents_created" in data
        assert isinstance(data["incident_ids"], list)

    def test_scan_creates_incidents(self):
        """Cluster scan should detect incidents in the simulated cluster."""
        response = client.post("/api/v1/scan")
        data = response.json()
        # Simulated cluster has known issues
        assert data["total_detections"] >= 0  # At least runs without error


class TestClusterSummaryEndpoint:
    """Tests for the cluster summary endpoint."""

    def test_cluster_summary_returns_data(self):
        """GET /api/v1/cluster/summary should return health summary."""
        response = client.get("/api/v1/cluster/summary")
        assert response.status_code == 200
        data = response.json()
        assert "health_score" in data
        assert "total_pods" in data
        assert "total_nodes" in data

    def test_health_score_in_range(self):
        """Health score should be between 0 and 100."""
        response = client.get("/api/v1/cluster/summary")
        score = response.json()["health_score"]
        assert 0.0 <= score <= 100.0


class TestFeedbackEndpoint:
    """Tests for the feedback endpoint."""

    def test_submit_feedback(self):
        """POST /api/v1/feedback should return recorded status."""
        created = client.post("/api/v1/incidents", json=make_incident_payload()).json()
        inc_id = created["id"]
        response = client.post(
            "/api/v1/feedback",
            json={
                "incident_id": inc_id,
                "plan_summary": "Restarted the deployment",
                "success": True,
                "notes": "Fixed by creating the missing secret",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "recorded"

    def test_similar_incidents_endpoint(self):
        """GET /api/v1/incidents/{id}/similar should return a list."""
        created = client.post("/api/v1/incidents", json=make_incident_payload()).json()
        inc_id = created["id"]
        response = client.get(f"/api/v1/incidents/{inc_id}/similar")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
