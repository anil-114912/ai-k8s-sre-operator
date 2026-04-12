"""Tests for remediation executors (all in dry-run mode)."""
from __future__ import annotations

import os
import pytest

os.environ["DEMO_MODE"] = "1"

from remediations.restart_pod import RestartPodRemediation
from remediations.rollout_restart import RolloutRestartRemediation
from remediations.rollback_deployment import RollbackDeploymentRemediation
from remediations.scale_deployment import ScaleDeploymentRemediation
from remediations.patch_resources import PatchResourcesRemediation
from remediations.rerun_job import RerunJobRemediation


INCIDENT_ID = "test-incident-001"
PLAN_ID = "test-plan-001"


class TestRestartPodRemediation:
    """Tests for RestartPodRemediation."""

    def test_dry_run_returns_success(self):
        """Dry run should return success without any K8s call."""
        rem = RestartPodRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "production", "pod_name": "payment-api-abc-xyz"},
            dry_run=True,
        )
        assert result.success is True
        assert "DRY RUN" in result.output

    def test_dry_run_includes_command(self):
        """Dry run output should mention the pod name."""
        rem = RestartPodRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "default", "pod_name": "my-pod-xyz"},
            dry_run=True,
        )
        assert "my-pod-xyz" in result.output

    def test_correct_executed_steps(self):
        """executed_steps should contain the action name."""
        rem = RestartPodRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "default", "pod_name": "pod-xyz"},
            dry_run=True,
        )
        assert "restart_pod" in result.executed_steps


class TestRolloutRestartRemediation:
    """Tests for RolloutRestartRemediation."""

    def test_dry_run_returns_success(self):
        """Dry run should succeed without K8s call."""
        rem = RolloutRestartRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "production", "workload": "payment-api"},
            dry_run=True,
        )
        assert result.success is True
        assert "DRY RUN" in result.output

    def test_command_includes_deployment_name(self):
        """Dry run output should mention the deployment name."""
        rem = RolloutRestartRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "staging", "workload": "my-deployment"},
            dry_run=True,
        )
        assert "my-deployment" in result.output


class TestRollbackDeploymentRemediation:
    """Tests for RollbackDeploymentRemediation."""

    def test_dry_run_returns_success(self):
        """Dry run should succeed."""
        rem = RollbackDeploymentRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "production", "workload": "payment-api"},
            dry_run=True,
        )
        assert result.success is True

    def test_plan_id_in_result(self):
        """Result should reference the plan ID."""
        rem = RollbackDeploymentRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "default", "workload": "app"},
            dry_run=True,
        )
        assert result.plan_id == PLAN_ID


class TestScaleDeploymentRemediation:
    """Tests for ScaleDeploymentRemediation."""

    def test_dry_run_scale_up(self):
        """Dry run scale-up should succeed."""
        rem = ScaleDeploymentRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "production", "workload": "api", "replicas": 5},
            dry_run=True,
        )
        assert result.success is True
        assert "DRY RUN" in result.output

    def test_dry_run_output_mentions_deployment(self):
        """Dry run output should mention the deployment name."""
        rem = ScaleDeploymentRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "production", "workload": "my-api", "replicas": 3},
            dry_run=True,
        )
        assert "my-api" in result.output


class TestPatchResourcesRemediation:
    """Tests for PatchResourcesRemediation."""

    def test_dry_run_patch(self):
        """Dry run patch should succeed with descriptive output."""
        rem = PatchResourcesRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={
                "namespace": "production",
                "workload": "analytics-worker",
                "container_name": "analytics-worker",
                "memory_limit": "512Mi",
                "cpu_limit": "1000m",
            },
            dry_run=True,
        )
        assert result.success is True


class TestRerunJobRemediation:
    """Tests for RerunJobRemediation."""

    def test_dry_run_rerun(self):
        """Dry run job rerun should succeed."""
        rem = RerunJobRemediation()
        result = rem.execute(
            incident_id=INCIDENT_ID,
            plan_id=PLAN_ID,
            params={"namespace": "production", "job_name": "daily-etl"},
            dry_run=True,
        )
        assert result.success is True
        assert "daily-etl" in result.output
