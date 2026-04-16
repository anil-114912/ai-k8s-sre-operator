"""Streamlit dashboard — dark futuristic incident management UI."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env from project root so DEMO_MODE, KUBECONFIG, etc. are available
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

import httpx
import streamlit as st

# Suppress harmless Tornado WebSocket closed errors during tab switches/refreshes
import logging
logging.getLogger("tornado.application").setLevel(logging.CRITICAL)

# Shared httpx client — disable SSL verification for local API calls.
# The API runs on http://localhost:8000 (plain HTTP) but macOS Python's
# broken SSL setup can interfere even with HTTP requests in some configs.
_http_client = httpx.Client(verify=False, timeout=30)

_DEFAULT_API_BASE = "http://localhost:8000"


def _get_api_base() -> str:
    """Return the current API base URL, validated with protocol prefix."""
    url = st.session_state.get("api_base_url", os.getenv("API_BASE_URL", _DEFAULT_API_BASE))
    if not url:
        return _DEFAULT_API_BASE
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url.rstrip("/")

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AI K8s SRE Operator",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — dark futuristic theme
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* ── Adaptive theme: works in both light and dark mode ── */

    /* Badge styles — visible on any background */
    .badge-critical { background: #ff3366; color: white; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
    .badge-high { background: #ff7722; color: white; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
    .badge-medium { background: #e6a800; color: black; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
    .badge-low { background: #00cc6a; color: black; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
    .badge-auto_fix { background: #00cc6a; color: black; padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; }
    .badge-approval_required { background: #e6a800; color: black; padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; }
    .badge-suggest_only { background: #9b59b6; color: white; padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; }

    /* ── Dark mode overrides (only applied when Streamlit is in dark theme) ── */
    @media (prefers-color-scheme: dark) {
        .main .block-container { padding: 1.5rem; }
    }

    /* Streamlit dark theme detection via data attribute */
    [data-testid="stAppViewContainer"][data-theme="dark"] {
        --bg: #060b18;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(path: str) -> Optional[Any]:
    """Make a GET request to the API."""
    try:
        base = _get_api_base()
        r = _http_client.get(f"{base}{path}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def api_post(path: str, data: dict = None) -> Optional[Any]:
    """Make a POST request to the API."""
    try:
        base = _get_api_base()
        r = _http_client.post(f"{base}{path}", json=data or {})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def severity_badge(sev: str) -> str:
    """Return an HTML severity badge."""
    return f'<span class="badge-{sev}">{sev.upper()}</span>'


def safety_badge(level: str) -> str:
    """Return an HTML safety level badge."""
    labels = {
        "auto_fix": "L1: AUTO",
        "approval_required": "L2: APPROVAL",
        "suggest_only": "L3: SUGGEST",
    }
    return f'<span class="badge-{level}">{labels.get(level, level)}</span>'


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🛡️ AI SRE Operator")
    st.markdown("---")

    st.markdown("### Connection")
    api_url = st.text_input("API URL", value=_get_api_base(), key="sidebar_api_url")
    if api_url:
        st.session_state["api_base_url"] = api_url

    # Warn if pointing at a K8s API server instead of the local FastAPI
    _current = _get_api_base()
    if any(k in _current for k in (".eks.amazonaws.com", ".azmk8s.io", "container.googleapis.com")):
        st.error(
            "⚠️ API URL points to a Kubernetes API server, not the SRE Operator API. "
            "Change it to `http://localhost:8000` (or wherever the FastAPI server runs)."
        )
    if st.button("🔄 Reset to localhost:8000", key="reset_api_url"):
        st.session_state["api_base_url"] = _DEFAULT_API_BASE
        st.rerun()

    st.markdown("---")
    health = api_get("/health")
    if health:
        is_demo = health.get("demo_mode", True)
        cluster_mode = health.get("cluster", "simulated")
        if is_demo:
            st.warning(f"🎮 Demo Mode — simulated cluster")
        else:
            st.success(f"✅ Live Cluster — {cluster_mode}")
        st.caption(f"API v{health.get('version', '?')}")
    else:
        st.error("❌ API Offline — run `make run-api` first")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    "# 🛡️ AI Kubernetes SRE Operator",
    unsafe_allow_html=False,
)

# Cluster summary bar
summary = api_get("/api/v1/cluster/summary")
if summary:
    cols = st.columns(7)
    score = summary.get("health_score", 0)
    score_color = "green" if score > 80 else ("orange" if score > 50 else "red")
    cols[0].metric("Health Score", f"{score:.0f}/100")
    cols[1].metric("Nodes", f"{summary.get('ready_nodes',0)}/{summary.get('total_nodes',0)}")
    cols[2].metric("Pods Running", summary.get("running_pods", 0))
    cols[3].metric("Pending", summary.get("pending_pods", 0), delta_color="inverse")
    cols[4].metric("CrashLoop", summary.get("crashloop_pods", 0), delta_color="inverse")
    cols[5].metric("Active Incidents", summary.get("active_incidents", 0), delta_color="inverse")
    cols[6].metric("PVCs Bound", f"{summary.get('bound_pvcs',0)}/{summary.get('total_pvcs',0)}")

st.markdown("---")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "⚡ Live Incidents",
    "🧠 RCA Analysis",
    "🔧 Remediation",
    "📚 Incident History",
    "🔍 Cluster Scan",
    "📖 Knowledge Base",
    "🧪 Learning & Feedback",
])

# ---------------------------------------------------------------------------
# Tab 1: Live Incidents
# ---------------------------------------------------------------------------

with tab1:
    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        sev_filter = st.selectbox("Severity", ["All", "critical", "high", "medium", "low"])
    with col2:
        ns_filter = st.text_input("Namespace", "")
    with col3:
        st.write("")

    params = "?"
    if sev_filter != "All":
        params += f"severity={sev_filter}&"
    if ns_filter:
        params += f"namespace={ns_filter}&"

    incidents = api_get(f"/api/v1/incidents{params}")

    if not incidents:
        st.info("No incidents detected. Run a cluster scan or load an example.")
    else:
        for inc in incidents:
            sev = inc.get("severity", "info")
            status = inc.get("status", "detected")
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")

            with st.expander(
                f"{icon} [{inc.get('incident_type','?')}] {inc.get('workload','?')} / {inc.get('namespace','?')} — {inc.get('title','')[:60]}"
            ):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Severity:** {severity_badge(sev)}", unsafe_allow_html=True)
                c2.markdown(f"**Status:** `{status}`")
                c3.markdown(f"**Detected:** `{inc.get('detected_at','')[:19]}`")

                if inc.get("root_cause"):
                    st.info(f"🎯 Root Cause: {inc['root_cause']}")
                if inc.get("confidence"):
                    st.progress(inc["confidence"], text=f"Confidence: {inc['confidence']:.0%}")

                ic1, ic2, ic3 = st.columns(3)
                if ic1.button("🧠 Analyze", key=f"analyze_{inc['id']}"):
                    with st.spinner("Running AI analysis..."):
                        result = api_post(f"/api/v1/incidents/{inc['id']}/analyze")
                    if result:
                        st.success("Analysis complete!")
                        st.json(result)

                if ic2.button("🔧 Get Plan", key=f"plan_{inc['id']}"):
                    plan = api_get(f"/api/v1/incidents/{inc['id']}/remediation")
                    if plan:
                        st.json(plan)

                if ic3.button("👥 Similar", key=f"similar_{inc['id']}"):
                    similar = api_get(f"/api/v1/incidents/{inc['id']}/similar")
                    if similar:
                        st.json(similar)
                    else:
                        st.info("No similar past incidents found.")

                # Inline feedback form
                if inc.get("status") == "analyzed":
                    st.markdown("---")
                    st.markdown("**📝 Operator Feedback**")
                    fb_c1, fb_c2 = st.columns(2)
                    fix_worked = fb_c1.radio(
                        "Did the fix work?",
                        ["Yes ✅", "No ❌"],
                        key=f"fix_{inc['id']}",
                        horizontal=True,
                    )
                    rca_correct = fb_c2.radio(
                        "Was root cause correct?",
                        ["Yes ✅", "No ❌"],
                        key=f"rca_{inc['id']}",
                        horizontal=True,
                    )
                    better_fix = st.text_input(
                        "Better remediation (optional)",
                        key=f"better_{inc['id']}",
                        placeholder="e.g. kubectl create secret generic db-creds ...",
                    )
                    notes = st.text_input(
                        "Notes",
                        key=f"notes_{inc['id']}",
                        placeholder="What actually fixed it?",
                    )
                    if st.button("📤 Submit Feedback", key=f"submit_fb_{inc['id']}"):
                        fb_payload = {
                            "incident_id": inc["id"],
                            "correct_root_cause": fix_worked.startswith("Yes"),
                            "fix_worked": rca_correct.startswith("Yes"),
                            "operator_notes": notes,
                            "better_remediation": better_fix if better_fix else None,
                        }
                        fb_result = api_post("/api/v1/feedback/structured", fb_payload)
                        if fb_result:
                            st.success(
                                f"✅ Feedback recorded! "
                                f"Learned patterns: {fb_result.get('learning_stats', {}).get('total_learned_patterns', 0)}"
                            )

# ---------------------------------------------------------------------------
# Tab 2: RCA Analysis
# ---------------------------------------------------------------------------

with tab2:
    st.markdown("### 🧠 AI Root Cause Analysis")
    inc_id = st.text_input("Incident ID", key="rca_inc_id", placeholder="paste incident UUID")

    if inc_id:
        inc_data = api_get(f"/api/v1/incidents/{inc_id}")
        if inc_data:
            st.markdown(f"#### {inc_data.get('title')}")
            c1, c2, c3 = st.columns(3)
            c1.markdown(
                f"**Severity:** {severity_badge(inc_data.get('severity','?'))}",
                unsafe_allow_html=True,
            )
            c2.markdown(f"**Type:** `{inc_data.get('incident_type','?')}`")
            c3.markdown(f"**Status:** `{inc_data.get('status','?')}`")

            if st.button("▶️ Run Full AI Analysis", type="primary"):
                with st.spinner("Correlating signals, retrieving past incidents, calling AI..."):
                    result = api_post(f"/api/v1/incidents/{inc_id}/analyze")
                if result:
                    inc_data = result

            if inc_data.get("root_cause"):
                st.markdown("---")
                st.markdown("#### 🎯 Root Cause")
                st.error(inc_data["root_cause"])

                if inc_data.get("confidence"):
                    st.progress(inc_data["confidence"], text=f"Confidence: {inc_data['confidence']:.0%}")

            if inc_data.get("ai_explanation"):
                st.markdown("#### 📖 AI Explanation")
                st.markdown(inc_data["ai_explanation"])

            if inc_data.get("contributing_factors"):
                st.markdown("#### 🔗 Contributing Factors")
                for cf in inc_data["contributing_factors"]:
                    st.markdown(f"- {cf}")

            if inc_data.get("evidence"):
                st.markdown("#### 🔬 Evidence")
                for ev in inc_data["evidence"]:
                    relevance = ev.get("relevance", 1.0)
                    source = ev.get("source", "?")
                    with st.expander(f"[{source}] relevance={relevance:.0%}"):
                        st.code(ev.get("content", ""), language="text")

            # Knowledge Base Matches
            if inc_id:
                kb_results = api_get(
                    f"/api/v1/knowledge/search?q={inc_data.get('incident_type','')}"
                    f"+{inc_data.get('namespace','')}&top_k=3"
                )
                if kb_results:
                    st.markdown("#### 📖 Knowledge Base Matches")
                    for kb in kb_results:
                        score = kb.get("score", 0)
                        safety = kb.get("safety_level", "suggest_only")
                        with st.expander(
                            f"[{kb.get('id','?')}] {kb.get('title','')} — score={score:.2f}"
                        ):
                            st.markdown(
                                f"**Safety:** {safety_badge(safety)}",
                                unsafe_allow_html=True,
                            )
                            st.markdown(f"**Root cause:** {kb.get('root_cause','')}")
                            steps = kb.get("remediation_steps", [])
                            if steps:
                                st.markdown("**Remediation steps:**")
                                for i, step in enumerate(steps[:3], 1):
                                    st.markdown(f"{i}. {step}")
                            tags = kb.get("tags", [])
                            if tags:
                                st.markdown(
                                    " ".join(f"`{t}`" for t in tags)
                                )

            # Similar Past Incidents
            if inc_id:
                similar_data = api_get(f"/api/v1/incidents/{inc_id}/similar")
                if similar_data:
                    st.markdown("#### 🔁 Similar Past Incidents")
                    for sim in similar_data[:3]:
                        outcome = sim.get("resolution_outcome") or ("resolved" if sim.get("resolved") else None)
                        feedback_icon = "✅" if outcome == "resolved" else ("❌" if outcome == "failed" else "—")
                        with st.expander(
                            f"{feedback_icon} similarity={sim.get('similarity', 0):.2f} | "
                            f"{sim.get('type','?')} in {sim.get('namespace','?')}"
                        ):
                            if sim.get("root_cause"):
                                st.markdown(f"**Root cause:** {sim['root_cause']}")
                            if sim.get("suggested_fix"):
                                st.markdown(f"**Fix:** {sim['suggested_fix']}")

# ---------------------------------------------------------------------------
# Tab 3: Remediation
# ---------------------------------------------------------------------------

with tab3:
    st.markdown("### 🔧 Remediation Plans")
    rem_inc_id = st.text_input("Incident ID", key="rem_inc_id", placeholder="paste incident UUID")

    if rem_inc_id:
        col1, col2 = st.columns(2)
        dry_run = col1.checkbox("Dry Run Mode", value=True)
        get_plan = col2.button("📋 Get Remediation Plan")

        plan_data = None
        if get_plan:
            plan_data = api_get(f"/api/v1/incidents/{rem_inc_id}/remediation")

        if plan_data:
            st.markdown(f"**Plan:** {plan_data.get('summary')}")
            st.markdown(
                f"**Overall Safety:** {safety_badge(plan_data.get('overall_safety_level','?'))}",
                unsafe_allow_html=True,
            )

            if plan_data.get("requires_approval"):
                st.warning("⚠️ This plan requires approval before execution.")
                if st.button("✅ Approve Plan"):
                    result = api_post(f"/api/v1/incidents/{rem_inc_id}/remediation/approve")
                    if result:
                        st.success("Plan approved!")

            st.markdown("#### Steps")
            for step in plan_data.get("steps", []):
                level = step.get("safety_level", "?")
                level_label = {"auto_fix": "L1: AUTO", "approval_required": "L2: APPROVAL", "suggest_only": "L3: SUGGEST"}.get(level, level)
                with st.expander(f"Step {step['order']}: {step['action']} [{level_label}]"):
                    st.markdown(safety_badge(level), unsafe_allow_html=True)
                    st.markdown(f"**Description:** {step.get('description','')}")
                    if step.get("command"):
                        st.code(step["command"], language="bash")
                    st.markdown(
                        f"Reversible: {'✅' if step.get('reversible') else '❌'} | "
                        f"Est. Duration: {step.get('estimated_duration_secs', 0)}s"
                    )

            bc1, bc2 = st.columns(2)
            if bc1.button("▶️ Execute (Dry Run)" if dry_run else "▶️ Execute"):
                with st.spinner("Executing remediation..."):
                    result = api_post(
                        f"/api/v1/incidents/{rem_inc_id}/remediation/execute?dry_run={str(dry_run).lower()}"
                    )
                if result:
                    st.code(result.get("output", ""), language="text")

# ---------------------------------------------------------------------------
# Tab 4: Incident History
# ---------------------------------------------------------------------------

with tab4:
    st.markdown("### 📚 Incident History")

    # Learning stats row
    stats = api_get("/api/v1/stats/accuracy")
    if stats:
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Total Analyzed", stats.get("total_analyzed", 0))
        sc2.metric("RCA Accuracy", f"{stats.get('correct_rca_pct', 0):.0f}%")
        sc3.metric("Fix Success Rate", f"{stats.get('fix_success_pct', 0):.0f}%")
        top_types = stats.get("top_failure_types", [])
        sc4.metric("Top Failure Type", top_types[0]["type"] if top_types else "—")

    st.markdown("---")

    # Cluster patterns bar chart
    cluster_patterns = api_get("/api/v1/cluster/patterns?cluster_name=default&limit=5")
    if cluster_patterns:
        st.markdown("#### Cluster Recurring Failure Patterns")
        try:
            import pandas as pd
            import plotly.express as px
            df_cp = pd.DataFrame(cluster_patterns)
            if not df_cp.empty:
                fig = px.bar(
                    df_cp, x="incident_type", y="count",
                    title="Top 5 Failure Types in This Cluster",
                    color="count", color_continuous_scale="reds",
                )
                fig.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            for cp in cluster_patterns:
                st.markdown(f"- **{cp.get('incident_type','?')}**: {cp.get('count',0)} occurrences")

    st.markdown("---")

    history = api_get("/api/v1/incidents?limit=100")

    if history:
        import pandas as pd

        df_data = [
            {
                "ID": i.get("id", "")[:8] + "...",
                "Title": i.get("title", "")[:50],
                "Type": i.get("incident_type", ""),
                "Severity": i.get("severity", ""),
                "Namespace": i.get("namespace", ""),
                "Status": i.get("status", ""),
                "Detected": i.get("detected_at", "")[:19],
            }
            for i in history
        ]
        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True)

        st.markdown(f"**Total incidents:** {len(history)}")
        resolved = sum(1 for i in history if i.get("status") in ("resolved", "closed"))
        st.markdown(f"**Resolved:** {resolved} ({resolved/len(history):.0%})")
    else:
        st.info("No incident history yet. Run a cluster scan to generate incidents.")

# ---------------------------------------------------------------------------
# Tab 5: Cluster Scan
# ---------------------------------------------------------------------------

with tab5:
    st.markdown("### 🔍 Cluster Scan")

    col1, col2 = st.columns([2, 1])
    scan_ns = col1.text_input("Namespace filter (optional)", "")

    if col2.button("🚀 Run Cluster Scan", type="primary"):
        with st.spinner("Scanning cluster for incidents..."):
            params = f"?namespace={scan_ns}" if scan_ns else ""
            result = api_post(f"/api/v1/scan{params}")
        if result:
            st.success(f"✅ Scan complete: {result.get('total_detections', 0)} detections, {result.get('incidents_created', 0)} incidents created")
            if result.get("incident_ids"):
                st.markdown("**Created incidents:**")
                for iid in result["incident_ids"]:
                    st.code(iid)

    # Always show cluster summary
    st.markdown("---")
    st.markdown("#### Current Cluster Health")
    summary = api_get("/api/v1/cluster/summary")
    if summary:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Health Score", f"{summary.get('health_score', 0):.0f}/100")
        c2.metric("Nodes Ready", f"{summary.get('ready_nodes',0)}/{summary.get('total_nodes',0)}")
        c3.metric("Deployments Available", f"{summary.get('available_deployments',0)}/{summary.get('total_deployments',0)}")
        c4.metric("PVCs Bound", f"{summary.get('bound_pvcs',0)}/{summary.get('total_pvcs',0)}")

        st.markdown(f"**Summary:** {summary.get('summary','')}")

# ---------------------------------------------------------------------------
# Tab 6: Knowledge Base
# ---------------------------------------------------------------------------

with tab6:
    st.markdown("### 📖 Failure Pattern Knowledge Base")

    # Stats row
    kb_patterns = api_get("/api/v1/knowledge/failures")
    stats = api_get("/api/v1/stats/accuracy")
    kb_count = len(kb_patterns) if kb_patterns else 0

    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.metric("Total Patterns", kb_count)
    if stats:
        kc2.metric("Incidents Analyzed", stats.get("total_analyzed", 0))
        kc3.metric("RCA Accuracy", f"{stats.get('correct_rca_pct', 0):.0f}%")
        kc4.metric("Fix Success Rate", f"{stats.get('fix_success_pct', 0):.0f}%")

    st.markdown("---")

    # Search box and tag filter
    col_search, col_tag = st.columns([3, 1])
    kb_query = col_search.text_input(
        "Search knowledge base", placeholder="e.g. secret not found crashloop"
    )

    # Build tag list from all patterns
    all_tags: List[str] = []
    if kb_patterns:
        tag_set = set()
        for p in kb_patterns:
            for t in p.get("tags", []):
                if isinstance(t, str):
                    tag_set.add(t)
        all_tags = sorted(tag_set)

    tag_filter = col_tag.selectbox(
        "Filter by tag", ["All"] + all_tags, key="kb_tag_filter"
    )

    # Search or list
    if kb_query:
        provider_sel = st.selectbox(
            "Provider context", ["generic", "aws", "azure", "gcp"], key="kb_provider"
        )
        search_url = f"/api/v1/knowledge/search?q={kb_query}&provider={provider_sel}&top_k=10"
        display_patterns = api_get(search_url) or []
    elif tag_filter != "All":
        display_patterns = api_get(f"/api/v1/knowledge/failures?tag={tag_filter}") or []
    else:
        display_patterns = kb_patterns or []

    if display_patterns:
        st.markdown(f"**Showing {len(display_patterns)} pattern(s)**")
        for p in display_patterns:
            safety = p.get("safety_level", "suggest_only")
            score = p.get("score")
            score_str = f" — score={score:.2f}" if score is not None else ""
            tags = p.get("tags", [])
            tag_str = " ".join(f"`{t}`" for t in tags if isinstance(t, str))

            with st.expander(
                f"[{p.get('id','?')}] {p.get('title','')}{score_str}"
            ):
                col_a, col_b = st.columns([3, 1])
                col_a.markdown(f"**Root cause:** {p.get('root_cause','')}")
                col_b.markdown(
                    f"**Safety:** {safety_badge(safety)}", unsafe_allow_html=True
                )

                steps = p.get("remediation_steps", [])
                if steps:
                    st.markdown("**Remediation steps:**")
                    for i, step in enumerate(steps, 1):
                        st.markdown(f"{i}. {step}")

                if tag_str:
                    st.markdown(f"**Tags:** {tag_str}")
    else:
        st.info("No patterns found. Try a different search query or tag filter.")

# ---------------------------------------------------------------------------
# Tab 7: Learning & Feedback
# ---------------------------------------------------------------------------

with tab7:
    st.markdown("### 🧪 Learning & Feedback Dashboard")
    st.markdown(
        "This tab shows how the system learns from operator feedback. "
        "Submit feedback on incidents to improve future analysis."
    )

    # Learning stats
    learning_stats = api_get("/api/v1/stats/learning")
    accuracy_stats = api_get("/api/v1/stats/accuracy")

    if learning_stats:
        st.markdown("#### 📊 Learning System Status")
        lc1, lc2, lc3, lc4, lc5 = st.columns(5)
        lc1.metric("Learned Patterns", learning_stats.get("total_learned_patterns", 0))
        lc2.metric("Promoted Patterns", learning_stats.get("promoted_patterns", 0))
        lc3.metric("Captured Errors", learning_stats.get("captured_error_patterns", 0))
        lc4.metric("Feedback Events", learning_stats.get("total_feedback_events", 0))
        lc5.metric("Successful Fixes", learning_stats.get("total_successful_fixes", 0))

        st.markdown("---")
        st.markdown(
            f"**Embedder refit:** {learning_stats.get('incidents_since_last_refit', 0)}"
            f" / {learning_stats.get('refit_threshold', 5)} incidents until next refit"
        )

    if accuracy_stats:
        st.markdown("#### 📈 Accuracy Over Time")
        ac1, ac2, ac3 = st.columns(3)
        ac1.metric("Total Analyzed", accuracy_stats.get("total_analyzed", 0))

        rca_pct = accuracy_stats.get("correct_rca_pct", 0)
        ac2.metric("RCA Accuracy", f"{rca_pct:.0f}%")

        fix_pct = accuracy_stats.get("fix_success_pct", 0)
        ac3.metric("Fix Success Rate", f"{fix_pct:.0f}%")

        # Top failure types chart
        top_types = accuracy_stats.get("top_failure_types", [])
        if top_types:
            st.markdown("#### Top Failure Types")
            try:
                import pandas as pd
                import plotly.express as px
                df_types = pd.DataFrame(top_types)
                fig = px.bar(
                    df_types, x="type", y="count",
                    title="Most Frequent Incident Types",
                    color="count", color_continuous_scale="blues",
                )
                fig.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                for t in top_types:
                    st.markdown(f"- **{t.get('type','?')}**: {t.get('count',0)}")

    st.markdown("---")

    # Manual feedback submission form
    st.markdown("#### 📝 Submit Feedback for an Incident")
    st.markdown(
        "Paste an incident ID and tell the system whether the analysis was correct "
        "and whether the fix worked. This directly improves future analysis."
    )

    fb_inc_id = st.text_input(
        "Incident ID", key="fb_loop_inc_id",
        placeholder="paste incident UUID from Live Incidents tab",
    )

    if fb_inc_id:
        # Show incident summary
        fb_inc = api_get(f"/api/v1/incidents/{fb_inc_id}")
        if fb_inc:
            st.markdown(
                f"**{fb_inc.get('title','')}** — "
                f"{severity_badge(fb_inc.get('severity','?'))} "
                f"`{fb_inc.get('incident_type','?')}`",
                unsafe_allow_html=True,
            )
            if fb_inc.get("root_cause"):
                st.info(f"🎯 AI Root Cause: {fb_inc['root_cause']}")
            if fb_inc.get("suggested_fix"):
                st.success(f"💡 AI Suggested Fix: {fb_inc['suggested_fix']}")

            st.markdown("---")

            fc1, fc2 = st.columns(2)
            fb_rca_correct = fc1.radio(
                "Was the root cause correct?",
                ["Yes — AI got it right", "No — root cause was wrong"],
                key="fb_loop_rca",
            )
            fb_fix_worked = fc2.radio(
                "Did the suggested fix work?",
                ["Yes — fix resolved the issue", "No — fix did not work"],
                key="fb_loop_fix",
            )

            fb_better = st.text_area(
                "Better remediation (if the AI suggestion was wrong)",
                key="fb_loop_better",
                placeholder="e.g. The actual fix was: kubectl create secret generic db-creds -n production --from-literal=DB_URL=...",
                height=80,
            )
            fb_notes = st.text_area(
                "Operator notes",
                key="fb_loop_notes",
                placeholder="Any additional context about what happened and how it was resolved",
                height=80,
            )

            if st.button("📤 Submit Structured Feedback", type="primary", key="fb_loop_submit"):
                payload = {
                    "incident_id": fb_inc_id,
                    "correct_root_cause": fb_rca_correct.startswith("Yes"),
                    "fix_worked": fb_fix_worked.startswith("Yes"),
                    "operator_notes": fb_notes,
                    "better_remediation": fb_better if fb_better.strip() else None,
                }
                result = api_post("/api/v1/feedback/structured", payload)
                if result:
                    st.success("✅ Feedback submitted successfully!")
                    st.markdown("**Learning system updated:**")
                    ls = result.get("learning_stats", {})
                    st.json(ls)

                    if payload["correct_root_cause"] and payload["fix_worked"]:
                        st.balloons()
                        st.markdown(
                            "🎉 Great! The system will prioritize this root cause and fix "
                            "for similar incidents in the future."
                        )
                    elif not payload["fix_worked"] and payload.get("better_remediation"):
                        st.markdown(
                            "📝 Your better remediation has been recorded. "
                            "The system will suggest it for similar incidents next time."
                        )
                    elif not payload["correct_root_cause"]:
                        st.markdown(
                            "⚠️ Noted. The system will reduce confidence for this "
                            "root cause pattern in future similar incidents."
                        )
        else:
            st.warning(f"Incident `{fb_inc_id}` not found. Check the ID and try again.")

    st.markdown("---")

    # How learning works explanation
    with st.expander("ℹ️ How does the learning loop work?"):
        st.markdown("""
**The system improves through 5 mechanisms:**

1. **Unknown Error Capture** — When a new incident arrives with log lines containing
   ERROR/FATAL/PANIC patterns not seen before, the system automatically creates a new
   knowledge base entry in `learned.yaml`.

2. **Embedder Refit** — Every 5 new incidents, the TF-IDF similarity engine is
   retrained on all stored incident texts, improving future similarity matching.

3. **Feedback Scoring** — When you mark a fix as successful (+1.0) or failed (-0.5),
   the score is stored on the incident. Future similarity searches boost incidents
   with positive feedback and penalize those with negative feedback.

4. **Pattern Promotion** — When 2+ similar incidents in the same namespace are
   resolved successfully, the system promotes the root cause and fix into a
   permanent learned pattern.

5. **Confidence Adjustment** — The AI confidence score is adjusted based on
   historical feedback for the same incident type + namespace. If past fixes
   in "payments" namespace for CrashLoopBackOff were 90% successful, the next
   CrashLoopBackOff in "payments" gets a confidence boost.

**Example flow:**
```
Incident #1: CrashLoop in payments/order-svc → AI says "missing secret" (75% confidence)
  → Operator: "Yes, correct! Fixed by creating the secret" ✅

Incident #2: CrashLoop in payments/order-svc → AI says "missing secret" (82% confidence)
  → Confidence boosted because of positive feedback history
  → Past fix shown in "Similar Past Incidents" section
  → Operator: "Yes, same issue" ✅

Incident #3: CrashLoop in payments/order-svc → AI says "missing secret" (88% confidence)
  → Pattern promoted to permanent knowledge base
  → Remediation suggested immediately with high confidence
```
        """)

    # Show learned patterns if any exist
    st.markdown("#### 📚 Learned Patterns")
    st.markdown("These patterns were automatically captured or promoted from operator feedback.")
    learned = api_get("/api/v1/knowledge/failures?tag=learned") or []
    promoted = api_get("/api/v1/knowledge/failures?tag=promoted") or []
    all_learned = learned + promoted

    if all_learned:
        for p in all_learned:
            icon = "🎓" if "promoted" in (p.get("id") or "") else "🔍"
            with st.expander(f"{icon} [{p.get('id','?')}] {p.get('title','')}"):
                st.markdown(f"**Root cause:** {p.get('root_cause','')}")
                steps = p.get("remediation_steps", [])
                if steps:
                    st.markdown("**Remediation:**")
                    for i, s in enumerate(steps[:5], 1):
                        st.markdown(f"{i}. {s}")
                tags = p.get("tags", [])
                if tags:
                    st.markdown(" ".join(f"`{t}`" for t in tags))
    else:
        st.info(
            "No learned patterns yet. Submit feedback on analyzed incidents "
            "to start building the learned knowledge base."
        )
