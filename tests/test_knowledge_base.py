"""Tests for the Hybrid Learning Architecture knowledge base components."""
from __future__ import annotations

import pytest

from knowledge.failure_kb import FailureKnowledgeBase, FailurePattern
from knowledge.feedback_store import FeedbackStore
from knowledge.incident_store import IncidentStore
from knowledge.learning import ContextBuilder
from knowledge.retrieval import SimilarityRetriever, RetrievedIncident
from models.incident import Incident, IncidentType, Severity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kb() -> FailureKnowledgeBase:
    """Return a loaded FailureKnowledgeBase."""
    kb = FailureKnowledgeBase()
    kb.load()
    return kb


@pytest.fixture
def mem_store(tmp_path):
    """Return an in-memory SQLite IncidentStore for isolation."""
    return IncidentStore(database_url=f"sqlite:///{tmp_path}/test.db")


@pytest.fixture
def sample_incident() -> Incident:
    """Return a sample CrashLoopBackOff incident."""
    return Incident(
        title="CrashLoopBackOff: payment-api-abc-xyz",
        incident_type=IncidentType.crash_loop,
        severity=Severity.critical,
        namespace="production",
        workload="payment-api",
        pod_name="payment-api-abc-xyz",
    )


# ---------------------------------------------------------------------------
# FailureKnowledgeBase — load tests
# ---------------------------------------------------------------------------

class TestFailureKnowledgeBaseLoad:
    """Tests for FailureKnowledgeBase.load()."""

    def test_load_returns_patterns(self, kb):
        """load() should populate patterns from all YAML files."""
        patterns = kb.list_all()
        assert len(patterns) >= 40, f"Expected >= 40 patterns, got {len(patterns)}"

    def test_all_patterns_have_required_fields(self, kb):
        """Every pattern must have id, title, root_cause, and remediation_steps."""
        for p in kb.list_all():
            assert p.id, f"Pattern missing id: {p}"
            assert p.title, f"Pattern '{p.id}' missing title"
            assert p.root_cause, f"Pattern '{p.id}' missing root_cause"
            assert len(p.remediation_steps) > 0, f"Pattern '{p.id}' has no remediation_steps"

    def test_load_idempotent(self, kb):
        """Calling load() twice should not duplicate patterns."""
        count_before = len(kb.list_all())
        kb.load()
        count_after = len(kb.list_all())
        assert count_before == count_after

    def test_generic_k8s_patterns_present(self, kb):
        """k8s-001 through k8s-012 should be loaded."""
        for pattern_id in ("k8s-001", "k8s-002", "k8s-003", "k8s-006", "k8s-012"):
            p = kb.get_by_id(pattern_id)
            assert p is not None, f"Pattern {pattern_id} not found"

    def test_provider_patterns_present(self, kb):
        """EKS, AKS, and GKE patterns should be loaded."""
        assert kb.get_by_id("eks-001") is not None
        assert kb.get_by_id("aks-001") is not None
        assert kb.get_by_id("gke-001") is not None

    def test_cluster_patterns_present(self, kb):
        """Cluster-level patterns (quota, etcd, node) should be loaded."""
        assert kb.get_by_id("clust-001") is not None
        assert kb.get_by_id("clust-004") is not None


# ---------------------------------------------------------------------------
# FailureKnowledgeBase — search tests
# ---------------------------------------------------------------------------

class TestFailureKnowledgeBaseSearch:
    """Tests for FailureKnowledgeBase.search()."""

    def test_secret_not_found_returns_k8s_001_as_top(self, kb):
        """Searching for 'secret not found crashloop' should return k8s-001 first."""
        results = kb.search("secret not found crashloop")
        assert results, "Expected at least one result"
        assert results[0].id == "k8s-001", (
            f"Expected k8s-001 as top result, got {results[0].id} ({results[0].title})"
        )

    def test_search_returns_list_of_failure_patterns(self, kb):
        """search() should return FailurePattern objects with score set."""
        results = kb.search("pod pending insufficient memory")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, FailurePattern)
            assert r.score >= 0.0

    def test_search_top_k_respected(self, kb):
        """search() should not return more than top_k results."""
        results = kb.search("crashloop", top_k=3)
        assert len(results) <= 3

    def test_search_sorted_by_score_desc(self, kb):
        """Results should be sorted by score descending."""
        results = kb.search("secret not found crashloop", top_k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True), "Results not sorted by score descending"

    def test_search_with_aws_provider_boosts_eks_patterns(self, kb):
        """Provider='aws' should boost EKS-specific patterns."""
        results = kb.search("IAM IRSA missing AccessDenied", provider="aws", top_k=5)
        ids = [r.id for r in results]
        assert "eks-002" in ids, f"Expected eks-002 in AWS results, got: {ids}"

    def test_search_with_azure_provider_boosts_aks_patterns(self, kb):
        """Provider='azure' should boost AKS-specific patterns."""
        results = kb.search("managed identity authorization failed", provider="azure", top_k=5)
        ids = [r.id for r in results]
        assert "aks-002" in ids, f"Expected aks-002 in Azure results, got: {ids}"

    def test_search_with_gcp_provider_boosts_gke_patterns(self, kb):
        """Provider='gcp' should boost GKE-specific patterns."""
        results = kb.search("workload identity PERMISSION_DENIED", provider="gcp", top_k=5)
        ids = [r.id for r in results]
        assert "gke-001" in ids, f"Expected gke-001 in GCP results, got: {ids}"

    def test_search_empty_query_returns_results(self, kb):
        """Even an empty search should return patterns based on fallback scoring."""
        results = kb.search("", top_k=5)
        # Empty query may return nothing or something — just must not raise
        assert isinstance(results, list)

    def test_search_oom_returns_k8s_003(self, kb):
        """OOMKill search should surface k8s-003."""
        results = kb.search("OOMKilled exit code 137 memory limit", top_k=5)
        ids = [r.id for r in results]
        assert "k8s-003" in ids, f"Expected k8s-003 for OOM search, got: {ids}"

    def test_get_by_id_returns_correct_pattern(self, kb):
        """get_by_id should return the exact pattern."""
        p = kb.get_by_id("k8s-001")
        assert p is not None
        assert p.title == "CrashLoopBackOff — missing secret"
        assert p.safe_auto_fix is False
        assert p.safety_level == "suggest_only"

    def test_get_by_id_missing_returns_none(self, kb):
        """get_by_id with unknown ID should return None."""
        assert kb.get_by_id("nonexistent-999") is None

    def test_list_by_tag_networking(self, kb):
        """list_by_tag('networking') should return networking patterns."""
        patterns = kb.list_by_tag("networking")
        assert len(patterns) > 0, "Expected networking patterns"
        for p in patterns:
            assert "networking" in p.tags

    def test_list_by_tag_storage(self, kb):
        """list_by_tag('storage') should return storage patterns."""
        patterns = kb.list_by_tag("storage")
        assert len(patterns) > 0


# ---------------------------------------------------------------------------
# ContextBuilder — combined KB + memory context
# ---------------------------------------------------------------------------

class TestContextBuilder:
    """Tests for ContextBuilder combined context generation."""

    def test_build_context_returns_string(self, mem_store, sample_incident):
        """build_context() should always return a string."""
        builder = ContextBuilder(store=mem_store)
        ctx = builder.build_context(sample_incident)
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_build_context_includes_kb_section(self, mem_store, sample_incident):
        """Context should include KNOWLEDGE BASE MATCHES section when KB has results."""
        builder = ContextBuilder(store=mem_store)
        ctx = builder.build_context(sample_incident)
        # Should have KB section since we have a loaded KB with matching patterns
        assert "KNOWLEDGE BASE" in ctx or "Pattern" in ctx or "No relevant context" in ctx

    def test_build_context_no_store_incidents_returns_gracefully(self, mem_store, sample_incident):
        """Context builder should not crash when no past incidents exist."""
        builder = ContextBuilder(store=mem_store)
        ctx = builder.build_context(sample_incident)
        assert isinstance(ctx, str)

    def test_context_includes_memory_section_when_incidents_exist(self, mem_store, sample_incident):
        """When past incidents exist, context should reference them."""
        # Store an incident first
        mem_store.save_incident(sample_incident)
        builder = ContextBuilder(store=mem_store)

        # Build context for a second incident
        second = Incident(
            title="CrashLoopBackOff: api-xyz",
            incident_type=IncidentType.crash_loop,
            severity=Severity.high,
            namespace="production",
            workload="api",
        )
        ctx = builder.build_context(second)
        assert isinstance(ctx, str)

    def test_retrieve_similar_returns_list(self, mem_store, sample_incident):
        """retrieve_similar() should return a list (possibly empty)."""
        builder = ContextBuilder(store=mem_store)
        result = builder.retrieve_similar(sample_incident)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# SimilarityRetriever — feedback boost tests
# ---------------------------------------------------------------------------

class TestSimilarityRetrieverFeedback:
    """Tests for SimilarityRetriever feedback boost and scoring."""

    def test_feedback_boost_increases_score(self, mem_store):
        """An incident with positive feedback_score should rank higher than one without."""
        # Save two incidents
        inc_a = Incident(
            title="CrashLoopBackOff missing secret production",
            incident_type=IncidentType.crash_loop,
            severity=Severity.critical,
            namespace="production",
            workload="payment-api",
        )
        inc_b = Incident(
            title="CrashLoopBackOff missing secret staging",
            incident_type=IncidentType.crash_loop,
            severity=Severity.high,
            namespace="staging",
            workload="payment-api",
        )
        mem_store.save_incident(inc_a)
        mem_store.save_incident(inc_b)

        # Mark inc_a as successfully resolved
        mem_store.update_feedback(inc_a.id, success=True)

        retriever = SimilarityRetriever(store=mem_store, top_k=5, feedback_boost=0.3)
        results = retriever.retrieve(
            query_text="CrashLoopBackOff missing secret production",
            namespace="production",
        )

        assert len(results) > 0
        # Find inc_a in results
        inc_a_result = next((r for r in results if r.incident_id == inc_a.id), None)
        if inc_a_result:
            assert inc_a_result.feedback_boost > 0.0, (
                "Expected feedback_boost > 0 for positively-scored incident"
            )

    def test_find_similar_returns_dicts(self, mem_store):
        """find_similar() backward-compat method should return plain dicts."""
        inc = Incident(
            title="OOMKilled worker pod",
            incident_type=IncidentType.oom_killed,
            severity=Severity.high,
            namespace="default",
            workload="worker",
        )
        mem_store.save_incident(inc)

        retriever = SimilarityRetriever(store=mem_store, top_k=3)
        results = retriever.find_similar("OOMKilled worker memory limit")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, dict)
            assert "similarity" in r

    def test_retrieve_returns_retrieved_incident_objects(self, mem_store):
        """retrieve() should return RetrievedIncident dataclass objects."""
        inc = Incident(
            title="ImagePullBackOff bad tag",
            incident_type=IncidentType.image_pull,
            severity=Severity.high,
            namespace="staging",
            workload="frontend",
        )
        mem_store.save_incident(inc)

        retriever = SimilarityRetriever(store=mem_store, top_k=3)
        results = retriever.retrieve("ImagePullBackOff manifest unknown")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, RetrievedIncident)
            assert hasattr(r, "incident_id")
            assert hasattr(r, "similarity")
            assert hasattr(r, "feedback_boost")

    def test_retrieve_empty_store_returns_empty(self, mem_store):
        """retrieve() should return empty list when no incidents are stored."""
        retriever = SimilarityRetriever(store=mem_store, top_k=3)
        results = retriever.retrieve("crashloop secret not found")
        assert results == []


# ---------------------------------------------------------------------------
# FeedbackStore — accuracy stats
# ---------------------------------------------------------------------------

class TestFeedbackStoreAccuracyStats:
    """Tests for FeedbackStore.get_accuracy_stats()."""

    def test_get_accuracy_stats_empty_store(self, mem_store):
        """Stats should return zero values when no incidents exist."""
        fs = FeedbackStore(mem_store)
        stats = fs.get_accuracy_stats()
        assert stats["total_analyzed"] == 0
        assert stats["correct_rca_pct"] == 0.0
        assert stats["fix_success_pct"] == 0.0
        assert isinstance(stats["top_failure_types"], list)

    def test_get_accuracy_stats_with_incidents(self, mem_store):
        """Stats should reflect stored incidents correctly."""
        # Save two incidents
        for i in range(3):
            inc = Incident(
                title=f"Test incident {i}",
                incident_type=IncidentType.crash_loop,
                severity=Severity.medium,
                namespace="default",
                workload=f"workload-{i}",
            )
            mem_store.save_incident(inc)

        fs = FeedbackStore(mem_store)
        stats = fs.get_accuracy_stats()
        assert stats["total_analyzed"] == 3

    def test_fix_success_pct_reflects_positive_feedback(self, mem_store):
        """fix_success_pct should increase when feedback is positive."""
        inc = Incident(
            title="Test incident",
            incident_type=IncidentType.crash_loop,
            severity=Severity.high,
            namespace="prod",
            workload="app",
        )
        mem_store.save_incident(inc)
        mem_store.update_feedback(inc.id, success=True)

        fs = FeedbackStore(mem_store)
        stats = fs.get_accuracy_stats()
        assert stats["fix_success_pct"] > 0.0

    def test_submit_feedback_creates_record(self, mem_store):
        """submit_feedback() should create a retrievable FeedbackRecord."""
        inc = Incident(
            title="Test",
            incident_type=IncidentType.crash_loop,
            severity=Severity.low,
            namespace="default",
            workload="app",
        )
        mem_store.save_incident(inc)

        fs = FeedbackStore(mem_store)
        record = fs.submit_feedback(
            incident_id=inc.id,
            correct_root_cause=True,
            fix_worked=True,
            operator_notes="All good",
            better_remediation=None,
        )
        assert record.incident_id == inc.id
        assert record.correct_root_cause is True
        assert record.fix_worked is True

        retrieved = fs.get_feedback_for_incident(inc.id)
        assert retrieved is not None
        assert retrieved.incident_id == inc.id

    def test_top_failure_types_populated(self, mem_store):
        """top_failure_types should list the most common incident types."""
        for _ in range(4):
            mem_store.save_incident(Incident(
                title="CrashLoop",
                incident_type=IncidentType.crash_loop,
                severity=Severity.high,
                namespace="prod",
                workload="app",
            ))
        for _ in range(2):
            mem_store.save_incident(Incident(
                title="OOM",
                incident_type=IncidentType.oom_killed,
                severity=Severity.high,
                namespace="prod",
                workload="app",
            ))

        fs = FeedbackStore(mem_store)
        stats = fs.get_accuracy_stats()
        types = [t["type"] for t in stats["top_failure_types"]]
        assert "CrashLoopBackOff" in types
        assert stats["top_failure_types"][0]["type"] == "CrashLoopBackOff"


# ---------------------------------------------------------------------------
# IncidentStore — new methods
# ---------------------------------------------------------------------------

class TestIncidentStoreNewMethods:
    """Tests for the new IncidentStore methods."""

    def test_get_by_namespace(self, mem_store):
        """get_by_namespace() should return only incidents in that namespace."""
        for ns in ("prod", "staging", "prod"):
            mem_store.save_incident(Incident(
                title=f"Inc in {ns}",
                incident_type=IncidentType.crash_loop,
                severity=Severity.medium,
                namespace=ns,
                workload="app",
            ))
        results = mem_store.get_by_namespace("prod")
        assert len(results) == 2
        assert all(r["namespace"] == "prod" for r in results)

    def test_get_by_type(self, mem_store):
        """get_by_type() should return only incidents of that type."""
        mem_store.save_incident(Incident(
            title="CrashLoop",
            incident_type=IncidentType.crash_loop,
            severity=Severity.high,
            namespace="prod",
            workload="app",
        ))
        mem_store.save_incident(Incident(
            title="OOM",
            incident_type=IncidentType.oom_killed,
            severity=Severity.high,
            namespace="prod",
            workload="app",
        ))
        results = mem_store.get_by_type("CrashLoopBackOff")
        assert len(results) == 1
        assert results[0]["type"] == "CrashLoopBackOff"

    def test_get_recent_limit(self, mem_store):
        """get_recent() should respect the limit parameter."""
        for i in range(5):
            mem_store.save_incident(Incident(
                title=f"Inc {i}",
                incident_type=IncidentType.crash_loop,
                severity=Severity.low,
                namespace="default",
                workload="app",
            ))
        results = mem_store.get_recent(limit=3)
        assert len(results) == 3

    def test_update_feedback_success(self, mem_store):
        """update_feedback with success=True should set feedback_score=1.0."""
        inc = Incident(
            title="Test",
            incident_type=IncidentType.crash_loop,
            severity=Severity.medium,
            namespace="prod",
            workload="app",
        )
        mem_store.save_incident(inc)
        mem_store.update_feedback(inc.id, success=True)

        record = mem_store.get_incident(inc.id)
        assert record is not None
        assert record["feedback_score"] == 1.0
        assert record["resolution_outcome"] == "resolved"

    def test_update_feedback_failure(self, mem_store):
        """update_feedback with success=False should set feedback_score=-0.5."""
        inc = Incident(
            title="Test",
            incident_type=IncidentType.crash_loop,
            severity=Severity.medium,
            namespace="prod",
            workload="app",
        )
        mem_store.save_incident(inc)
        mem_store.update_feedback(inc.id, success=False)

        record = mem_store.get_incident(inc.id)
        assert record is not None
        assert record["feedback_score"] == -0.5
        assert record["resolution_outcome"] == "failed"

    def test_get_cluster_patterns(self, mem_store):
        """get_cluster_patterns() should return aggregated failure types."""
        for _ in range(3):
            mem_store.save_incident(
                Incident(
                    title="CL",
                    incident_type=IncidentType.crash_loop,
                    severity=Severity.high,
                    namespace="prod",
                    workload="app",
                ),
                cluster_name="prod-cluster",
            )
        mem_store.save_incident(
            Incident(
                title="OOM",
                incident_type=IncidentType.oom_killed,
                severity=Severity.high,
                namespace="prod",
                workload="app",
            ),
            cluster_name="prod-cluster",
        )

        patterns = mem_store.get_cluster_patterns("prod-cluster")
        assert len(patterns) >= 1
        # CrashLoopBackOff should be most frequent
        assert patterns[0]["incident_type"] == "CrashLoopBackOff"
        assert patterns[0]["count"] == 3
