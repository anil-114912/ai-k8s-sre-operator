"""CLI entrypoint — ai-sre command with rich terminal output."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# Load .env from project root so DEMO_MODE, KUBECONFIG, etc. are available
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

import click
import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

console = Console()
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--api-url", default=API_BASE, envvar="API_BASE_URL", help="API base URL")
@click.pass_context
def cli(ctx: click.Context, api_url: str) -> None:
    """AI Kubernetes SRE Operator — incident detection, RCA, and remediation."""
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _api_get(api_url: str, path: str) -> Optional[Any]:
    """Make an API GET request and return parsed JSON."""
    try:
        r = httpx.get(f"{api_url}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        console.print(f"[red]API error: {exc}[/red]")
        return None


def _api_post(api_url: str, path: str, data: dict = None) -> Optional[Any]:
    """Make an API POST request and return parsed JSON."""
    try:
        r = httpx.post(f"{api_url}{path}", json=data or {}, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        console.print(f"[red]API error: {exc}[/red]")
        return None


def _severity_color(sev: str) -> str:
    """Map severity to a rich color."""
    return {
        "critical": "red",
        "high": "orange3",
        "medium": "yellow",
        "low": "green",
        "info": "blue",
    }.get(sev, "white")


def _safety_color(level: str) -> str:
    """Map safety level to a rich color."""
    return {"auto_fix": "green", "approval_required": "yellow", "suggest_only": "magenta"}.get(
        level, "white"
    )


# ---------------------------------------------------------------------------
# Cluster scan
# ---------------------------------------------------------------------------


@cli.group()
def cluster() -> None:
    """Cluster management commands."""
    pass


@cluster.command("scan")
@click.option("--namespace", "-n", default="", help="Kubernetes namespace to scan")
@click.pass_context
def cluster_scan(ctx: click.Context, namespace: str) -> None:
    """Scan the cluster for all active incidents."""
    api_url = ctx.obj["api_url"]
    console.print(Panel("[bold cyan]Running cluster scan...[/bold cyan]", title="🔍 Cluster Scan"))

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task("Scanning...", total=None)
        params = f"?namespace={namespace}" if namespace else ""
        result = _api_post(api_url, f"/api/v1/scan{params}")

    if not result:
        console.print("[red]Scan failed.[/red]")
        return

    console.print(
        Panel(
            f"[bold]Scan complete[/bold]\n"
            f"  Total detections:  [yellow]{result.get('total_detections', 0)}[/yellow]\n"
            f"  Incidents created: [cyan]{result.get('incidents_created', 0)}[/cyan]\n"
            f"  Scanned at:        {result.get('scanned_at', '')}",
            title="✅ Scan Results",
            border_style="green",
        )
    )

    if result.get("incident_ids"):
        table = Table(title="Created Incidents", box=box.ROUNDED, border_style="cyan")
        table.add_column("Incident ID", style="dim")
        for iid in result["incident_ids"]:
            table.add_row(iid)
        console.print(table)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@cli.group()
def incidents() -> None:
    """Incident management commands."""
    pass


@incidents.command("list")
@click.option("--severity", default="", help="Filter by severity (critical/high/medium/low)")
@click.option("--namespace", "-n", default="", help="Filter by namespace")
@click.pass_context
def incidents_list(ctx: click.Context, severity: str, namespace: str) -> None:
    """List all active incidents."""
    api_url = ctx.obj["api_url"]
    params = "?"
    if severity:
        params += f"severity={severity}&"
    if namespace:
        params += f"namespace={namespace}&"

    data = _api_get(api_url, f"/api/v1/incidents{params}")
    if data is None:
        return

    if not data:
        console.print("[yellow]No incidents found.[/yellow]")
        return

    table = Table(title="Active Incidents", box=box.ROUNDED, border_style="cyan")
    table.add_column("ID", style="dim", width=12)
    table.add_column("Severity", width=10)
    table.add_column("Type", width=20)
    table.add_column("Namespace", width=15)
    table.add_column("Workload", width=20)
    table.add_column("Status", width=12)
    table.add_column("Root Cause", width=40)

    for inc in data:
        sev = inc.get("severity", "?")
        table.add_row(
            inc.get("id", "")[:8] + "...",
            Text(sev.upper(), style=_severity_color(sev)),
            inc.get("incident_type", "?"),
            inc.get("namespace", "?"),
            inc.get("workload", "?"),
            inc.get("status", "?"),
            (inc.get("root_cause") or "Not yet analyzed")[:38],
        )

    console.print(table)


@cli.group("incident")
def incident_cmd() -> None:
    """Single incident commands."""
    pass


@incident_cmd.command("analyze")
@click.argument("incident_id_or_file")
@click.pass_context
def incident_analyze(ctx: click.Context, incident_id_or_file: str) -> None:
    """Run AI analysis on an incident (by ID or JSON file)."""
    api_url = ctx.obj["api_url"]

    # If a file path, load and ingest first
    incident_id = incident_id_or_file
    if os.path.isfile(incident_id_or_file):
        with open(incident_id_or_file) as f:
            inc_data = json.load(f)
        ingested = _api_post(api_url, "/api/v1/incidents", inc_data)
        if not ingested:
            return
        incident_id = ingested["id"]
        console.print(f"[green]Incident ingested: {incident_id}[/green]")

    console.print(
        Panel(f"[bold cyan]Analyzing incident: {incident_id}[/bold cyan]", title="🧠 AI RCA")
    )

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task("Running correlation and AI analysis...", total=None)
        result = _api_post(api_url, f"/api/v1/incidents/{incident_id}/analyze")

    if not result:
        return

    sev = result.get("severity", "?")
    console.print(
        Panel(
            f"[bold]Title:[/bold] {result.get('title')}\n"
            f"[bold]Type:[/bold]  {result.get('incident_type')}\n"
            f"[bold]Namespace:[/bold] {result.get('namespace')}/{result.get('workload')}\n"
            f"[bold]Severity:[/bold] [{_severity_color(sev)}]{sev.upper()}[/{_severity_color(sev)}]\n"
            f"[bold]Confidence:[/bold] {result.get('confidence', 0):.0%}",
            title="📋 Incident Summary",
            border_style="cyan",
        )
    )

    if result.get("root_cause"):
        console.print(
            Panel(
                f"[bold]{result['root_cause']}[/bold]",
                title="🎯 Root Cause",
                border_style="red",
            )
        )

    if result.get("ai_explanation"):
        console.print(
            Panel(
                result["ai_explanation"],
                title="📖 AI Explanation",
                border_style="blue",
            )
        )

    if result.get("contributing_factors"):
        console.print("\n[bold]Contributing Factors:[/bold]")
        for cf in result["contributing_factors"]:
            console.print(f"  • {cf}")

    if result.get("suggested_fix"):
        console.print(
            Panel(
                result["suggested_fix"],
                title="💡 Suggested Fix",
                border_style="green",
            )
        )


# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------


@cli.group()
def remediation() -> None:
    """Remediation plan commands."""
    pass


@remediation.command("plan")
@click.argument("incident_id")
@click.pass_context
def remediation_plan(ctx: click.Context, incident_id: str) -> None:
    """Show the remediation plan for an incident."""
    api_url = ctx.obj["api_url"]
    plan = _api_get(api_url, f"/api/v1/incidents/{incident_id}/remediation")
    if not plan:
        return

    safety = plan.get("overall_safety_level", "?")
    console.print(
        Panel(
            f"[bold]Summary:[/bold] {plan.get('summary')}\n"
            f"[bold]Safety Level:[/bold] [{_safety_color(safety)}]{safety.upper()}[/{_safety_color(safety)}]\n"
            f"[bold]Requires Approval:[/bold] {'Yes' if plan.get('requires_approval') else 'No'}\n"
            f"[bold]Est. Downtime:[/bold] {plan.get('estimated_downtime_secs', 0)}s",
            title="🔧 Remediation Plan",
            border_style="cyan",
        )
    )

    table = Table(title="Remediation Steps", box=box.SIMPLE_HEAVY, border_style="dim")
    table.add_column("#", width=4)
    table.add_column("Action", width=25)
    table.add_column("Safety", width=20)
    table.add_column("Reversible", width=10)
    table.add_column("Description", width=50)

    for step in plan.get("steps", []):
        sl = step.get("safety_level", "?")
        table.add_row(
            str(step.get("order", "?")),
            step.get("action", "?"),
            Text(sl.upper(), style=_safety_color(sl)),
            "✅" if step.get("reversible") else "❌",
            step.get("description", "")[:48],
        )
    console.print(table)


@remediation.command("execute")
@click.argument("incident_id")
@click.option("--dry-run/--no-dry-run", default=True, help="Simulate execution without changes")
@click.pass_context
def remediation_execute(ctx: click.Context, incident_id: str, dry_run: bool) -> None:
    """Execute the remediation plan for an incident."""
    api_url = ctx.obj["api_url"]
    mode = "DRY RUN" if dry_run else "LIVE"
    console.print(Panel(f"[bold]Executing remediation ({mode})...[/bold]", title="▶️ Execute"))
    result = _api_post(
        api_url,
        f"/api/v1/incidents/{incident_id}/remediation/execute?dry_run={str(dry_run).lower()}",
    )
    if result:
        console.print(result.get("output", ""))
        if result.get("success"):
            console.print("[green]✅ Execution successful[/green]")


@remediation.command("approve")
@click.argument("incident_id")
@click.pass_context
def remediation_approve(ctx: click.Context, incident_id: str) -> None:
    """Approve a remediation plan for execution."""
    api_url = ctx.obj["api_url"]
    result = _api_post(api_url, f"/api/v1/incidents/{incident_id}/remediation/approve")
    if result:
        console.print(f"[green]✅ {result.get('message')}[/green]")


# ---------------------------------------------------------------------------
# Simulate
# ---------------------------------------------------------------------------


@cli.command("simulate")
@click.option(
    "--type",
    "inc_type",
    default="crashloop",
    type=click.Choice(["crashloop", "oomkilled", "pending", "ingress", "pvc"]),
    help="Incident type to simulate",
)
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Run fully offline (no API server required — uses local pipeline directly)",
)
@click.pass_context
def simulate(ctx: click.Context, inc_type: str, demo: bool) -> None:
    """Simulate a specific incident type and run full AI analysis."""
    api_url = ctx.obj["api_url"]

    example_files = {
        "crashloop": "examples/crashloop_missing_secret.json",
        "oomkilled": "examples/oomkilled_app.json",
        "pending": "examples/pending_due_to_capacity.json",
        "ingress": "examples/ingress_service_mismatch.json",
        "pvc": "examples/pvc_mount_failure.json",
    }

    file_path = example_files.get(inc_type, "examples/crashloop_missing_secret.json")

    console.print(
        Panel(
            f"[bold cyan]Simulating {inc_type.upper()} incident[/bold cyan]\n"
            f"Loading from: {file_path}",
            title="🎮 Simulation Mode",
            border_style="magenta",
        )
    )

    if not os.path.isfile(file_path):
        console.print(f"[red]Example file not found: {file_path}[/red]")
        return

    with open(file_path) as f:
        inc_data = json.load(f)

    if demo:
        # ── Offline mode: run pipeline directly without API server ──────────
        _run_demo_pipeline(inc_data)
        return

    # ── API mode (requires running API server) ──────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("Ingesting incident..."), transient=True) as p:
        p.add_task("", total=None)
        ingested = _api_post(api_url, "/api/v1/incidents", inc_data)

    if not ingested:
        console.print(
            "[yellow]API server not reachable. Run with --demo for offline simulation.[/yellow]"
        )
        return

    incident_id = ingested["id"]
    console.print(f"[green]Incident created: {incident_id}[/green]")

    with Progress(
        SpinnerColumn(), TextColumn("Running AI analysis pipeline..."), transient=True
    ) as p:
        p.add_task("", total=None)
        analyzed = _api_post(api_url, f"/api/v1/incidents/{incident_id}/analyze")

    if not analyzed:
        return

    _print_incident_detail(analyzed)

    console.print("\n[bold]Generating remediation plan...[/bold]")
    plan = _api_get(api_url, f"/api/v1/incidents/{incident_id}/remediation")
    if plan:
        _print_remediation_summary(plan)


def _run_demo_pipeline(inc_data: Dict[str, Any]) -> None:
    """Run the full analysis pipeline locally without the API server."""
    from ai.rca_engine import RCAEngine
    from ai.remediation_engine import RemediationEngine
    from correlation.signal_correlator import SignalCorrelator
    from models.incident import Incident

    with Progress(
        SpinnerColumn(), TextColumn("Running AI analysis pipeline (offline)..."), transient=True
    ) as p:
        task = p.add_task("", total=None)

        incident = Incident(**inc_data)
        rca = RCAEngine()
        rem = RemediationEngine()
        correlator = SignalCorrelator()

        # correlation
        signals = incident.raw_signals or {}
        corr = correlator.correlate(
            detections=[],
            cluster_state={},
            raw_signals=signals,
        )

        # RCA
        analyzed = rca.analyze(incident, corr)
        p.update(task, completed=True)

    _print_incident_detail(analyzed.model_dump())

    console.print("\n[bold]Generating remediation plan...[/bold]")
    plan = rem.generate_plan(analyzed)
    _print_remediation_summary(plan.model_dump())


def _print_incident_detail(inc: Dict[str, Any]) -> None:
    """Print a rich incident detail panel."""
    sev = inc.get("severity", "?")
    color = _severity_color(sev)

    console.print(
        Panel(
            f"[{color}][bold]● {sev.upper()}[/bold][/{color}] — {inc.get('incident_type')}\n"
            f"[bold]Namespace/Workload:[/bold] {inc.get('namespace')}/{inc.get('workload')}\n"
            f"[bold]Root Cause:[/bold] {inc.get('root_cause', 'Analyzing...')}\n"
            f"[bold]Confidence:[/bold] {inc.get('confidence', 0):.0%}",
            title=f"📋 {inc.get('title', 'Incident')}",
            border_style=color,
        )
    )

    if inc.get("ai_explanation"):
        console.print(Panel(inc["ai_explanation"], title="📖 AI Explanation", border_style="blue"))

    if inc.get("suggested_fix"):
        console.print(Panel(inc["suggested_fix"], title="💡 Suggested Fix", border_style="green"))


def _print_remediation_summary(plan: Dict[str, Any]) -> None:
    """Print a rich remediation plan summary."""
    safety = plan.get("overall_safety_level", "?")
    color = _safety_color(safety)
    approval = "Yes ⚠️" if plan.get("requires_approval") else "No ✅"

    console.print(
        Panel(
            f"[bold]Summary:[/bold] {plan.get('summary')}\n"
            f"[bold]Safety Level:[/bold] [{color}]{safety.upper()}[/{color}]\n"
            f"[bold]Requires Approval:[/bold] {approval}\n"
            f"[bold]Steps:[/bold] {len(plan.get('steps', []))}",
            title="🔧 Remediation Plan",
            border_style=color,
        )
    )


# ---------------------------------------------------------------------------
# Learn / feedback
# ---------------------------------------------------------------------------


@cli.group()
def learn() -> None:
    """Learning and feedback commands."""
    pass


@learn.command("feedback")
@click.argument("incident_id")
@click.option("--success/--failure", default=True, help="Whether the remediation succeeded")
@click.option("--notes", default="", help="Operator notes")
@click.pass_context
def learn_feedback(ctx: click.Context, incident_id: str, success: bool, notes: str) -> None:
    """Record operator feedback for a remediation outcome."""
    api_url = ctx.obj["api_url"]
    result = _api_post(
        api_url,
        "/api/v1/feedback",
        {"incident_id": incident_id, "success": success, "notes": notes, "plan_summary": ""},
    )
    if result:
        status = "✅ Success" if success else "❌ Failure"
        console.print(f"[green]Feedback recorded: {status}[/green]")


# ---------------------------------------------------------------------------
# Feedback commands (extended)
# ---------------------------------------------------------------------------


@cli.group()
def feedback() -> None:
    """Operator feedback commands."""
    pass


@feedback.group("submit")
def feedback_submit_group() -> None:
    """Submit feedback for an incident."""
    pass


@feedback.command("submit")
@click.argument("incident_id")
@click.option("--correct/--incorrect", default=True, help="Whether the RCA was correct")
@click.option(
    "--fix-worked/--fix-failed",
    "fix_worked",
    default=True,
    help="Whether the fix resolved the incident",
)
@click.option("--notes", default="", help="Operator notes")
@click.pass_context
def feedback_submit(
    ctx: click.Context, incident_id: str, correct: bool, fix_worked: bool, notes: str
) -> None:
    """Submit structured feedback for an incident's RCA and fix quality."""
    api_url = ctx.obj["api_url"]
    result = _api_post(
        api_url,
        "/api/v1/feedback",
        {
            "incident_id": incident_id,
            "success": fix_worked,
            "notes": notes,
            "plan_summary": f"RCA correct={correct}",
        },
    )
    if result:
        rca_str = "✅ Correct RCA" if correct else "❌ Incorrect RCA"
        fix_str = "✅ Fix worked" if fix_worked else "❌ Fix failed"
        console.print(
            Panel(
                f"Incident: {incident_id}\n{rca_str}\n{fix_str}\nNotes: {notes or '(none)'}",
                title="📊 Feedback Submitted",
                border_style="green",
            )
        )


@feedback.command("stats")
@click.pass_context
def feedback_stats(ctx: click.Context) -> None:
    """Show RCA accuracy and fix success statistics."""
    api_url = ctx.obj["api_url"]
    stats = _api_get(api_url, "/api/v1/stats/accuracy")
    if not stats:
        return

    table = Table(title="Learning Statistics", box=box.ROUNDED, border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Total Incidents Analyzed", str(stats.get("total_analyzed", 0)))
    table.add_row("RCA Accuracy", f"{stats.get('correct_rca_pct', 0):.1f}%")
    table.add_row("Fix Success Rate", f"{stats.get('fix_success_pct', 0):.1f}%")

    top_types = stats.get("top_failure_types", [])
    if top_types:
        top_str = ", ".join(f"{t['type']} ({t['count']})" for t in top_types[:3])
        table.add_row("Top Failure Types", top_str)

    console.print(table)


# ---------------------------------------------------------------------------
# Knowledge base commands
# ---------------------------------------------------------------------------


@cli.group()
def knowledge() -> None:
    """Knowledge base commands."""
    pass


@knowledge.command("search")
@click.argument("query")
@click.option("--provider", default="generic", help="Cloud provider context: generic/aws/azure/gcp")
@click.option("--top-k", default=5, help="Number of results to return")
@click.pass_context
def knowledge_search(ctx: click.Context, query: str, provider: str, top_k: int) -> None:
    """Search the failure pattern knowledge base."""
    api_url = ctx.obj["api_url"]
    results = _api_get(
        api_url, f"/api/v1/knowledge/search?q={query}&provider={provider}&top_k={top_k}"
    )
    if not results:
        console.print("[yellow]No matching patterns found.[/yellow]")
        return

    table = Table(title=f"Knowledge Base Search: '{query}'", box=box.ROUNDED, border_style="cyan")
    table.add_column("ID", width=10)
    table.add_column("Title", width=40)
    table.add_column("Score", width=8)
    table.add_column("Safety", width=16)
    table.add_column("Tags", width=30)

    for p in results:
        safety = p.get("safety_level", "?")
        tags = ", ".join(str(t) for t in p.get("tags", [])[:4])
        table.add_row(
            p.get("id", "?"),
            p.get("title", "?")[:38],
            f"{p.get('score', 0):.2f}",
            Text(safety, style=_safety_color(safety)),
            tags,
        )
    console.print(table)

    # Show top result remediation steps
    if results:
        top = results[0]
        console.print(
            Panel(
                f"[bold]Root cause:[/bold] {top.get('root_cause', '')}\n\n"
                + "\n".join(
                    f"{i + 1}. {s}" for i, s in enumerate(top.get("remediation_steps", [])[:3])
                ),
                title=f"💡 Top Match: {top.get('title', '')}",
                border_style="green",
            )
        )


@knowledge.command("list")
@click.option("--tag", default="", help="Filter by tag (e.g. networking, storage, crashloop)")
@click.pass_context
def knowledge_list(ctx: click.Context, tag: str) -> None:
    """List all knowledge base failure patterns."""
    api_url = ctx.obj["api_url"]
    url = f"/api/v1/knowledge/failures?tag={tag}" if tag else "/api/v1/knowledge/failures"
    patterns = _api_get(api_url, url)
    if not patterns:
        console.print("[yellow]No patterns found.[/yellow]")
        return

    table = Table(
        title=f"Failure Patterns{' [tag=' + tag + ']' if tag else ''}",
        box=box.SIMPLE_HEAVY,
        border_style="dim",
    )
    table.add_column("ID", width=12)
    table.add_column("Title", width=45)
    table.add_column("Scope", width=10)
    table.add_column("Safety", width=18)
    table.add_column("Tags", width=30)

    for p in patterns:
        safety = p.get("safety_level", "?")
        tags = ", ".join(str(t) for t in p.get("tags", [])[:4])
        table.add_row(
            p.get("id", "?"),
            p.get("title", "?")[:43],
            p.get("scope", "?"),
            Text(safety, style=_safety_color(safety)),
            tags,
        )
    console.print(table)
    console.print(f"[dim]Total: {len(patterns)} patterns[/dim]")


# ---------------------------------------------------------------------------
# Cluster patterns command
# ---------------------------------------------------------------------------


@cluster.command("patterns")
@click.option("--cluster-name", default="default", help="Cluster name identifier")
@click.option("--limit", default=10, help="Number of patterns to show")
@click.pass_context
def cluster_patterns(ctx: click.Context, cluster_name: str, limit: int) -> None:
    """Show recurring failure type patterns for a cluster."""
    api_url = ctx.obj["api_url"]
    patterns = _api_get(
        api_url,
        f"/api/v1/cluster/patterns?cluster_name={cluster_name}&limit={limit}",
    )
    if not patterns:
        console.print(f"[yellow]No patterns found for cluster '{cluster_name}'.[/yellow]")
        return

    table = Table(
        title=f"Cluster Patterns: {cluster_name}",
        box=box.ROUNDED,
        border_style="cyan",
    )
    table.add_column("Failure Type", width=30)
    table.add_column("Count", width=10)

    for p in patterns:
        table.add_row(p.get("incident_type", "?"), str(p.get("count", 0)))
    console.print(table)


if __name__ == "__main__":
    cli(obj={})
