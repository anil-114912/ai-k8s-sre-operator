"""Streamlit dashboard — modern production-grade observability UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional

# Load .env from project root so DEMO_MODE, KUBECONFIG, etc. are available
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

# Suppress harmless Tornado WebSocket closed errors during tab switches/refreshes
import logging

import httpx
import streamlit as st

logging.getLogger("tornado.application").setLevel(logging.CRITICAL)

# Shared httpx client
_http_client = httpx.Client(verify=False, timeout=30)
_DEFAULT_API_BASE = "http://localhost:8000"


def _get_api_base() -> str:
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
# Design System CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

    /* ╔══════════════════════════════════════════════════════════════╗
       ║  AI SRE OPERATOR — DESIGN SYSTEM v3                         ║
       ║  Adaptive dark/light mode • WCAG AA contrast                ║
       ╚══════════════════════════════════════════════════════════════╝ */

    /* ══════════════════════════════════════════════════════════════
       SECTION 1: TOKEN DEFINITIONS
       Dark mode = default. Light mode via @media + [data-theme].
    ══════════════════════════════════════════════════════════════ */

    /* ── Dark mode tokens (default) ─────────────────────────────── */
    :root {
        /* Backgrounds */
        --bg-base:     #0B1220;
        --bg-input:    #1C2840;
        --bg-hover:    #162032;
        --bg-sidebar:  #080F1C;

        /* Borders */
        --border:       #1F2937;
        --border-focus: #7C3AED;
        --border-card:  #1E2A3B;

        /* Brand / Status colors */
        --purple:    #7C3AED;
        --purple-lt: #A78BFA;
        --purple-bg: rgba(124,58,237,0.12);
        --green:     #22C55E;
        --green-lt:  #86EFAC;
        --green-bg:  rgba(34,197,94,0.1);
        --yellow:    #F59E0B;
        --yellow-lt: #FCD34D;
        --red:       #EF4444;
        --red-lt:    #FCA5A5;
        --orange:    #F97316;
        --blue:      #3B82F6;

        /* Text — WCAG AA compliant on dark backgrounds */
        --text-primary:   #F9FAFB;   /* 17:1 on --bg-card  */
        --text-secondary: #D1D5DB;   /*  9:1 on --bg-card  */
        --text-muted:     #9CA3AF;   /*  5:1 on --bg-card  */
        --text-disabled:  #6B7280;   /* 3.5:1  */

        /* Spacing — 8px grid */
        --sp1: 4px; --sp2: 8px; --sp3: 12px; --sp4: 16px;
        --sp5: 20px; --sp6: 24px; --sp8: 32px;

        /* Radius */
        --r-sm: 6px;
        --r-md: 10px;
        --r-lg: 14px;

        /* Shadows */
        --shadow-card:      0 1px 3px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4);
        --shadow-card-hover:0 8px 24px rgba(0,0,0,0.6);
        --shadow-btn:       0 4px 14px rgba(124,58,237,0.35);

        /* Card bg (alias used in components) */
        --bg-card: #111827;
    }

    /* ── Light mode tokens — system preference ───────────────────── */
    @media (prefers-color-scheme: light) {
        :root {
            --bg-base:    #F8FAFC;
            --bg-card:    #FFFFFF;
            --bg-input:   #F1F5F9;
            --bg-hover:   #F1F5F9;
            --bg-sidebar: #F1F5F9;
            --border:      #CBD5E1;
            --border-card: #E2E8F0;
            --text-primary:   #0F172A;   /* 16:1 on white  */
            --text-secondary: #1E293B;   /* 13:1 on white  */
            --text-muted:     #475569;   /*  7:1 on white  */
            --text-disabled:  #94A3B8;   /* 3.5:1 on white */
            --shadow-card:       0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
            --shadow-card-hover: 0 8px 24px rgba(0,0,0,0.12);
            --shadow-btn:        0 4px 14px rgba(124,58,237,0.25);
        }
    }
    /* ── Light mode tokens — Streamlit data-theme attribute ─────── */
    /* Streamlit sets data-theme on <html> in v1.28+                 */
    html[data-theme="light"],
    html[data-theme="light"] :root {
        --bg-base:    #F8FAFC;
        --bg-card:    #FFFFFF;
        --bg-input:   #F1F5F9;
        --bg-hover:   #F1F5F9;
        --bg-sidebar: #F1F5F9;
        --border:      #CBD5E1;
        --border-card: #E2E8F0;
        --text-primary:   #0F172A;
        --text-secondary: #1E293B;
        --text-muted:     #475569;
        --text-disabled:  #94A3B8;
        --shadow-card:       0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
        --shadow-card-hover: 0 8px 24px rgba(0,0,0,0.12);
        --shadow-btn:        0 4px 14px rgba(124,58,237,0.25);
    }
    /* Explicit dark override (locks dark even if system is light) */
    html[data-theme="dark"],
    html[data-theme="dark"] :root {
        --bg-base:    #0B1220;
        --bg-card:    #111827;
        --bg-input:   #1C2840;
        --bg-hover:   #162032;
        --bg-sidebar: #080F1C;
        --border:      #1F2937;
        --border-card: #1E2A3B;
        --text-primary:   #F9FAFB;
        --text-secondary: #D1D5DB;
        --text-muted:     #9CA3AF;
        --text-disabled:  #6B7280;
    }

    /* ── 2. GLOBAL RESET & FONT ───────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; }
    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont,
                     'Segoe UI', Roboto, sans-serif !important;
        font-feature-settings: 'cv02','cv03','cv04','cv11';
        -webkit-font-smoothing: antialiased;
    }

    /* ── 3. APP SHELL ─────────────────────────────────────────────── */
    .stApp,
    .stApp > div,
    section[data-testid="stAppViewContainer"],
    section[data-testid="stAppViewContainer"] > div {
        background-color: var(--bg-base) !important;
    }
    .main .block-container {
        padding: var(--sp6) var(--sp8) var(--sp8) var(--sp8) !important;
        max-width: 100% !important;
        background: transparent !important;
    }

    /* ── 4. GLOBAL TEXT — force light text everywhere ─────────────── */
    .stApp, .stApp * {
        color: var(--text-primary);
    }
    /* Overrides that Streamlit injects (must use !important) */
    .stApp p, .stApp span, .stApp div,
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
    .stApp li, .stApp td, .stApp th,
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stText"] *,
    [data-testid="stExpander"] * { color: var(--text-primary) !important; }

    /* Captions / helper text — muted but still readable (5:1) */
    [data-testid="stCaption"],
    [data-testid="stCaption"] * { color: var(--text-muted) !important; }

    /* ── 5. SIDEBAR ───────────────────────────────────────────────── */
    div[data-testid="stSidebar"],
    div[data-testid="stSidebar"] > div { background: var(--bg-sidebar) !important; }
    div[data-testid="stSidebar"] * { color: var(--text-primary) !important; }

    /* Sidebar brand header */
    div[data-testid="stSidebar"] h2 {
        font-size: 1.05rem !important;
        font-weight: 800 !important;
        letter-spacing: -0.3px;
        color: var(--text-primary) !important;
    }
    /* Sidebar divider */
    div[data-testid="stSidebar"] hr {
        border-color: var(--border-card) !important;
        margin: var(--sp3) 0 !important;
    }
    /* Sidebar caption */
    div[data-testid="stSidebar"] [data-testid="stCaption"],
    div[data-testid="stSidebar"] [data-testid="stCaption"] * {
        color: var(--text-disabled) !important;
    }
    /* Sidebar inputs */
    div[data-testid="stSidebar"] input {
        background: var(--bg-input) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--r-sm) !important;
    }
    div[data-testid="stSidebar"] .stButton > button {
        width: 100%;
        justify-content: center;
    }

    /* ─── SIDEBAR NAVIGATION ─── */
    /* Hide "Navigate" label */
    div[data-testid="stSidebar"] .stRadio [data-testid="stWidgetLabel"] {
        display: none !important;
    }
    /* Kill radio circles — covers all Streamlit versions */
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radio"],
    div[data-testid="stSidebar"] .stRadio input[type="radio"],
    div[data-testid="stSidebar"] .stRadio [role="radio"] {
        display: none !important;
        width: 0 !important; height: 0 !important;
        overflow: hidden !important; margin: 0 !important;
    }
    /* Nav list container */
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] {
        display: flex !important;
        flex-direction: column !important;
        gap: 2px !important;
        width: 100% !important;
        padding: 0 !important;
    }
    /* Each nav item */
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label {
        display: flex !important;
        align-items: center !important;
        gap: var(--sp2) !important;
        padding: 9px 14px !important;
        border-radius: var(--r-md) !important;
        cursor: pointer !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        color: var(--text-muted) !important;
        transition: background 0.15s ease, color 0.15s ease !important;
        width: 100% !important;
        margin: 0 !important;
        user-select: none !important;
    }
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:hover {
        background: var(--purple-bg) !important;
        color: var(--purple-lt) !important;
    }
    /* Active / selected nav item */
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:has(input:checked),
    div[data-testid="stSidebar"] .stRadio [aria-checked="true"] {
        background: var(--purple-bg) !important;
        color: var(--purple-lt) !important;
        font-weight: 700 !important;
        box-shadow: inset 3px 0 0 var(--purple) !important;
    }
    /* Section separators */
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:nth-child(2),
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:nth-child(6),
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:nth-child(8),
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:nth-child(11),
    div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:nth-child(13) {
        border-top: 1px solid var(--border-card) !important;
        margin-top: var(--sp2) !important;
        padding-top: 11px !important;
    }

    /* ── 6. FORM INPUTS ───────────────────────────────────────────── */
    /* Labels */
    .stTextInput > label, .stSelectbox > label, .stCheckbox > label,
    .stNumberInput > label, .stTextArea > label,
    [data-testid="stWidgetLabel"] span {
        color: var(--text-secondary) !important;
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.02em !important;
        margin-bottom: var(--sp1) !important;
    }
    /* Text / number inputs */
    .stTextInput input, .stTextArea textarea, .stNumberInput input,
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input {
        background: var(--bg-input) !important;
        color: var(--text-primary) !important;
        border: 1.5px solid var(--border) !important;
        border-radius: var(--r-sm) !important;
        padding: 8px 12px !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        transition: border-color 0.15s !important;
        caret-color: var(--purple-lt) !important;
    }
    .stTextInput input::placeholder, .stTextArea textarea::placeholder {
        color: var(--text-disabled) !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus,
    .stNumberInput input:focus {
        border-color: var(--border-focus) !important;
        outline: none !important;
        box-shadow: 0 0 0 3px rgba(124,58,237,0.18) !important;
    }
    /* Selectboxes */
    [data-baseweb="select"] > div {
        background: var(--bg-input) !important;
        border: 1.5px solid var(--border) !important;
        border-radius: var(--r-sm) !important;
        transition: border-color 0.15s !important;
    }
    [data-baseweb="select"] > div:focus-within {
        border-color: var(--border-focus) !important;
        box-shadow: 0 0 0 3px rgba(124,58,237,0.18) !important;
    }
    [data-baseweb="select"] span,
    [data-baseweb="select"] div,
    [data-baseweb="select"] p { color: var(--text-primary) !important; background: transparent !important; }
    /* Dropdown list */
    [data-baseweb="popover"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--r-md) !important;
        box-shadow: var(--shadow-card-hover) !important;
    }
    [data-baseweb="popover"] li { background: transparent !important; color: var(--text-secondary) !important; padding: 8px 14px !important; }
    [data-baseweb="popover"] li:hover,
    [data-baseweb="popover"] [aria-selected="true"] {
        background: var(--purple-bg) !important;
        color: var(--purple-lt) !important;
    }
    /* Checkboxes */
    .stCheckbox label span { color: var(--text-secondary) !important; font-size: 0.875rem !important; }
    [data-baseweb="checkbox"] [data-checked="true"] { background: var(--purple) !important; border-color: var(--purple) !important; }

    /* ── 7. BUTTONS ───────────────────────────────────────────────── */
    /* Base — secondary / outlined */
    .stButton > button {
        background: var(--bg-card) !important;
        color: var(--text-secondary) !important;
        border: 1.5px solid var(--border) !important;
        border-radius: var(--r-sm) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.84rem !important;
        font-weight: 600 !important;
        padding: 8px 18px !important;
        line-height: 1.4 !important;
        cursor: pointer !important;
        transition: background 0.15s, border-color 0.15s,
                    color 0.15s, box-shadow 0.15s !important;
        white-space: nowrap !important;
    }
    .stButton > button:hover {
        background: var(--bg-hover) !important;
        border-color: var(--purple) !important;
        color: var(--purple-lt) !important;
        box-shadow: 0 0 0 3px var(--purple-bg) !important;
    }
    .stButton > button:active { transform: scale(0.98) !important; }
    /* Primary button */
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="baseButton-primary"] {
        background: var(--purple) !important;
        color: #FFFFFF !important;
        border: none !important;
        box-shadow: var(--shadow-btn) !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="baseButton-primary"]:hover {
        background: #6D28D9 !important;
        box-shadow: 0 6px 20px rgba(124,58,237,0.5) !important;
        border: none !important;
        color: #FFFFFF !important;
    }

    /* ── 8. METRIC / KPI CARDS ────────────────────────────────────── */
    [data-testid="metric-container"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: var(--r-md) !important;
        padding: var(--sp5) var(--sp5) var(--sp4) !important;
        position: relative !important;
        overflow: hidden !important;
        box-shadow: var(--shadow-card) !important;
        transition: border-color 0.2s, box-shadow 0.2s !important;
    }
    [data-testid="metric-container"]:hover {
        border-color: var(--purple) !important;
        box-shadow: 0 0 0 1px var(--purple), var(--shadow-card) !important;
    }
    /* Top accent line */
    [data-testid="metric-container"]::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--purple), var(--purple-lt));
    }
    /* Metric label */
    [data-testid="metric-container"] [data-testid="stMetricLabel"],
    [data-testid="metric-container"] label {
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: var(--text-muted) !important;
    }
    /* Metric value — largest, brightest element */
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: 900 !important;
        line-height: 1.1 !important;
        color: var(--text-primary) !important;
        letter-spacing: -0.5px !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] {
        font-size: 0.78rem !important;
        font-weight: 600 !important;
    }

    /* ── 9. EXPANDER / INCIDENT CARDS ────────────────────────────── */
    div[data-testid="stExpander"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: var(--r-md) !important;
        margin-bottom: 6px !important;
        box-shadow: var(--shadow-card) !important;
        overflow: hidden !important;
        transition: border-color 0.15s, box-shadow 0.15s !important;
    }
    div[data-testid="stExpander"]:hover {
        border-color: var(--purple) !important;
        box-shadow: 0 0 0 1px var(--purple) !important;
    }
    div[data-testid="stExpander"] details,
    div[data-testid="stExpander"] > div { background: transparent !important; }
    /* Expander header */
    div[data-testid="stExpander"] details summary {
        padding: 12px 16px !important;
        cursor: pointer !important;
    }
    div[data-testid="stExpander"] details summary p,
    div[data-testid="stExpander"] summary span {
        color: var(--text-secondary) !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
    }
    div[data-testid="stExpander"] details summary:hover p {
        color: var(--purple-lt) !important;
    }
    /* Expander body */
    div[data-testid="stExpander"] details[open] > div {
        padding: 0 16px 16px !important;
        border-top: 1px solid var(--border-card) !important;
    }

    /* ── 10. PAGE HEADER ──────────────────────────────────────────── */
    .page-title {
        font-size: 1.6rem !important;
        font-weight: 900 !important;
        color: var(--text-primary) !important;
        letter-spacing: -0.6px !important;
        line-height: 1.2 !important;
        margin: 0 0 2px 0 !important;
    }
    .page-subtitle {
        font-size: 0.83rem !important;
        color: var(--text-muted) !important;
        font-weight: 400 !important;
        margin: 0 !important;
    }

    /* ── 11. SECTION HEADERS ──────────────────────────────────────── */
    .section-header {
        display: block !important;
        font-size: 0.78rem !important;
        font-weight: 800 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.1em !important;
        color: var(--text-muted) !important;
        margin: var(--sp6) 0 var(--sp3) 0 !important;
        padding: 0 0 var(--sp2) 0 !important;
        border-bottom: 1px solid var(--border-card) !important;
    }

    /* ── 12. DIVIDERS ─────────────────────────────────────────────── */
    hr {
        border: none !important;
        border-top: 1px solid var(--border-card) !important;
        margin: var(--sp4) 0 !important;
    }

    /* ══════════════════════════════════════════════════════════════
       SECTION 2: ADAPTIVE BADGES
       Dark: tinted dark bg + light text. Light: tinted light bg + dark text.
       Both sets achieve ≥ 4.5:1 contrast ratio (WCAG AA).
    ══════════════════════════════════════════════════════════════ */

    /* ── Shared badge base ───────────────────────────────────────── */
    .badge-critical, .badge-high, .badge-medium, .badge-low,
    .badge-warning, .badge-info, .badge-auto_fix,
    .badge-approval_required, .badge-suggest_only {
        display: inline-flex;
        align-items: center;
        padding: 2px 10px;
        border-radius: 99px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.4px;
        text-transform: uppercase;
        border-width: 1px;
        border-style: solid;
        line-height: 1.6;
        white-space: nowrap;
    }

    /* ── Dark mode badges (default) ──────────────────────────────── */
    .badge-critical          { background:#7F1D1D; color:#FCA5A5; border-color:#B91C1C; }
    .badge-high              { background:#7C2D12; color:#FDBA74; border-color:#C2410C; }
    .badge-medium            { background:#78350F; color:#FDE68A; border-color:#B45309; }
    .badge-low               { background:#14532D; color:#86EFAC; border-color:#15803D; }
    .badge-warning           { background:#78350F; color:#FDE68A; border-color:#B45309; }
    .badge-info              { background:#1E3A5F; color:#93C5FD; border-color:#2563EB; }
    .badge-auto_fix          { background:#14532D; color:#86EFAC; border-color:#15803D; }
    .badge-approval_required { background:#78350F; color:#FDE68A; border-color:#B45309; }
    .badge-suggest_only      { background:#3B0764; color:#DDD6FE; border-color:#6D28D9; }

    /* ── Light mode badge overrides ──────────────────────────────── */
    @media (prefers-color-scheme: light) {
        .badge-critical          { background:#FEF2F2; color:#991B1B; border-color:#FECACA; }
        .badge-high              { background:#FFF7ED; color:#9A3412; border-color:#FED7AA; }
        .badge-medium            { background:#FFFBEB; color:#92400E; border-color:#FDE68A; }
        .badge-low               { background:#F0FDF4; color:#166534; border-color:#BBF7D0; }
        .badge-warning           { background:#FFFBEB; color:#92400E; border-color:#FDE68A; }
        .badge-info              { background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE; }
        .badge-auto_fix          { background:#F0FDF4; color:#166534; border-color:#BBF7D0; }
        .badge-approval_required { background:#FFFBEB; color:#92400E; border-color:#FDE68A; }
        .badge-suggest_only      { background:#F5F3FF; color:#5B21B6; border-color:#DDD6FE; }
    }
    html[data-theme="light"] .badge-critical          { background:#FEF2F2; color:#991B1B; border-color:#FECACA; }
    html[data-theme="light"] .badge-high              { background:#FFF7ED; color:#9A3412; border-color:#FED7AA; }
    html[data-theme="light"] .badge-medium            { background:#FFFBEB; color:#92400E; border-color:#FDE68A; }
    html[data-theme="light"] .badge-low               { background:#F0FDF4; color:#166534; border-color:#BBF7D0; }
    html[data-theme="light"] .badge-warning           { background:#FFFBEB; color:#92400E; border-color:#FDE68A; }
    html[data-theme="light"] .badge-info              { background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE; }
    html[data-theme="light"] .badge-auto_fix          { background:#F0FDF4; color:#166534; border-color:#BBF7D0; }
    html[data-theme="light"] .badge-approval_required { background:#FFFBEB; color:#92400E; border-color:#FDE68A; }
    html[data-theme="light"] .badge-suggest_only      { background:#F5F3FF; color:#5B21B6; border-color:#DDD6FE; }

    /* ── 14. STATUS DOTS ──────────────────────────────────────────── */
    .status-dot-green  { display:inline-block; width:8px; height:8px; border-radius:50%;
                         background:var(--green); box-shadow:0 0 6px var(--green);
                         margin-right:6px; vertical-align:middle; flex-shrink:0; }
    .status-dot-yellow { display:inline-block; width:8px; height:8px; border-radius:50%;
                         background:var(--yellow); box-shadow:0 0 6px var(--yellow);
                         margin-right:6px; vertical-align:middle; flex-shrink:0; }
    .status-dot-red    { display:inline-block; width:8px; height:8px; border-radius:50%;
                         background:var(--red); box-shadow:0 0 6px var(--red);
                         margin-right:6px; vertical-align:middle; flex-shrink:0; }
    .status-dot-gray   { display:inline-block; width:8px; height:8px; border-radius:50%;
                         background:var(--text-disabled);
                         margin-right:6px; vertical-align:middle; flex-shrink:0; }

    /* ── 15. ALERTS / NOTIFICATIONS ──────────────────────────────── */
    div[data-testid="stAlert"] {
        border-radius: var(--r-md) !important;
        border-left-width: 3px !important;
    }
    div[data-testid="stAlert"] p { color: inherit !important; }

    /* ── 16. PROGRESS BAR ─────────────────────────────────────────── */
    [data-testid="stProgressBar"] > div {
        background: rgba(124,58,237,0.18) !important;
        border-radius: 99px !important;
        height: 6px !important;
    }
    [data-testid="stProgressBar"] > div > div {
        background: linear-gradient(90deg, var(--purple), var(--purple-lt)) !important;
        border-radius: 99px !important;
    }

    /* ── 17. CODE BLOCKS (adaptive) ───────────────────────────────── */
    .stCodeBlock, pre, code {
        background: #060D1F !important;
        color: #7DD3FC !important;
        border: 1px solid var(--border-card) !important;
        border-radius: var(--r-sm) !important;
        font-size: 0.82rem !important;
    }
    @media (prefers-color-scheme: light) {
        .stCodeBlock, pre, code {
            background: #F1F5F9 !important;
            color: #1E3A5F !important;
            border-color: #CBD5E1 !important;
        }
    }
    html[data-theme="light"] .stCodeBlock,
    html[data-theme="light"] pre,
    html[data-theme="light"] code {
        background: #F1F5F9 !important;
        color: #1E3A5F !important;
        border-color: #CBD5E1 !important;
    }

    /* ── 18. DATAFRAME (adaptive) ─────────────────────────────────── */
    .stDataFrame, [data-testid="stDataFrame"] {
        border-radius: var(--r-md) !important;
        border: 1px solid var(--border-card) !important;
        overflow: hidden !important;
    }
    .stDataFrame table th {
        background: var(--bg-card) !important;
        color: var(--text-muted) !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        padding: 10px 12px !important;
        border-bottom: 1px solid var(--border-card) !important;
    }
    .stDataFrame table td {
        color: var(--text-secondary) !important;
        font-size: 0.84rem !important;
        padding: 8px 12px !important;
        border-bottom: 1px solid var(--border-card) !important;
    }
    .stDataFrame table tr:hover td { background: var(--bg-hover) !important; }

    /* ══════════════════════════════════════════════════════════════
       SECTION 3: LIGHT MODE COMPONENT OVERRIDES
       Extra specificity rules for elements that have hard-coded dark
       colors and need an explicit override in light mode.
    ══════════════════════════════════════════════════════════════ */
    @media (prefers-color-scheme: light) {
        /* Sidebar */
        div[data-testid="stSidebar"],
        div[data-testid="stSidebar"] > div { background: var(--bg-sidebar) !important; }
        div[data-testid="stSidebar"] * { color: var(--text-primary) !important; }
        div[data-testid="stSidebar"] [data-testid="stCaption"],
        div[data-testid="stSidebar"] [data-testid="stCaption"] * { color: var(--text-muted) !important; }
        div[data-testid="stSidebar"] hr { border-color: var(--border) !important; }
        div[data-testid="stSidebar"] input {
            background: var(--bg-card) !important;
            color: var(--text-primary) !important;
            border-color: var(--border) !important;
        }
        div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label { color: var(--text-muted) !important; }
        div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:hover {
            background: var(--purple-bg) !important; color: var(--purple) !important;
        }
        div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:has(input:checked),
        div[data-testid="stSidebar"] .stRadio [aria-checked="true"] {
            background: var(--purple-bg) !important; color: var(--purple) !important;
        }
        /* Buttons */
        .stButton > button {
            background: var(--bg-card) !important;
            color: var(--text-secondary) !important;
            border-color: var(--border) !important;
        }
        .stButton > button:hover {
            background: var(--bg-hover) !important;
            border-color: var(--purple) !important;
            color: var(--purple) !important;
        }
        .stButton > button[kind="primary"],
        .stButton > button[data-testid="baseButton-primary"] {
            background: var(--purple) !important;
            color: #FFFFFF !important;
            border-color: transparent !important;
        }
        /* Metric cards */
        [data-testid="metric-container"] { box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important; }
        [data-testid="metric-container"] [data-testid="stMetricValue"] { color: var(--text-primary) !important; }
        [data-testid="metric-container"] [data-testid="stMetricLabel"],
        [data-testid="metric-container"] label { color: var(--text-muted) !important; }
        /* Expanders */
        div[data-testid="stExpander"] { box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important; }
        div[data-testid="stExpander"] details summary p { color: var(--text-primary) !important; }
        /* Inputs */
        [data-baseweb="select"] > div {
            background: var(--bg-card) !important;
            border-color: var(--border) !important;
        }
        [data-baseweb="popover"] { background: var(--bg-card) !important; border-color: var(--border) !important; }
        [data-baseweb="popover"] li { color: var(--text-secondary) !important; }
    }
    /* Duplicate for Streamlit data-theme="light" attribute */
    html[data-theme="light"] div[data-testid="stSidebar"],
    html[data-theme="light"] div[data-testid="stSidebar"] > div { background: var(--bg-sidebar) !important; }
    html[data-theme="light"] div[data-testid="stSidebar"] * { color: var(--text-primary) !important; }
    html[data-theme="light"] div[data-testid="stSidebar"] [data-testid="stCaption"] * { color: var(--text-muted) !important; }
    html[data-theme="light"] div[data-testid="stSidebar"] input {
        background: var(--bg-card) !important; color: var(--text-primary) !important; border-color: var(--border) !important;
    }
    html[data-theme="light"] div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label { color: var(--text-muted) !important; }
    html[data-theme="light"] div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:hover,
    html[data-theme="light"] div[data-testid="stSidebar"] .stRadio [data-baseweb="radiogroup"] > label:has(input:checked),
    html[data-theme="light"] div[data-testid="stSidebar"] .stRadio [aria-checked="true"] {
        background: var(--purple-bg) !important; color: var(--purple) !important;
    }
    html[data-theme="light"] .stButton > button {
        background: var(--bg-card) !important; color: var(--text-secondary) !important; border-color: var(--border) !important;
    }
    html[data-theme="light"] .stButton > button:hover {
        background: var(--bg-hover) !important; border-color: var(--purple) !important; color: var(--purple) !important;
    }
    html[data-theme="light"] .stButton > button[kind="primary"],
    html[data-theme="light"] .stButton > button[data-testid="baseButton-primary"] {
        background: var(--purple) !important; color: #FFFFFF !important; border-color: transparent !important;
    }
    html[data-theme="light"] [data-baseweb="select"] > div { background: var(--bg-card) !important; border-color: var(--border) !important; }
    html[data-theme="light"] [data-baseweb="popover"] { background: var(--bg-card) !important; border-color: var(--border) !important; }
    html[data-theme="light"] [data-baseweb="popover"] li { color: var(--text-secondary) !important; }
    html[data-theme="light"] [data-testid="metric-container"] [data-testid="stMetricValue"] { color: var(--text-primary) !important; }
    html[data-theme="light"] [data-testid="metric-container"] label { color: var(--text-muted) !important; }

    /* ── 19. EMPTY STATES ─────────────────────────────────────────── */
    .empty-state {
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
        padding: 48px 24px;
        background: var(--bg-card);
        border: 1px dashed var(--border-card);
        border-radius: var(--r-lg);
        text-align: center;
    }
    .empty-state-icon  { font-size: 2.6rem; margin-bottom: 12px; }
    .empty-state-title { font-size: 1rem; font-weight: 700;
                         color: var(--text-secondary) !important; display: block; }
    .empty-state-body  { font-size: 0.82rem; color: var(--text-disabled) !important;
                         margin-top: 6px; display: block; max-width: 320px; }

    /* ── 20. MISC ─────────────────────────────────────────────────── */
    /* Spinner */
    .stSpinner > div { border-top-color: var(--purple) !important; }
    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: var(--bg-base); }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 99px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--purple); }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Plotly chart theme helper
# ---------------------------------------------------------------------------

_CHART_LAYOUT = dict(
    template="plotly_dark",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, -apple-system, sans-serif", size=12, color="#9CA3AF"),
    title_font=dict(family="Inter, sans-serif", size=13, color="#D1D5DB"),
    margin=dict(l=4, r=4, t=40, b=4),
    colorway=["#7C3AED", "#22C55E", "#F59E0B", "#EF4444", "#3B82F6", "#A78BFA", "#F97316"],
    legend=dict(
        bgcolor="rgba(17,24,39,0.8)",
        bordercolor="#1F2937",
        borderwidth=1,
        font=dict(size=11, color="#9CA3AF"),
    ),
    xaxis=dict(
        gridcolor="rgba(31,41,55,0.8)",
        linecolor="#1F2937",
        tickfont=dict(size=11, color="#6B7280"),
        title_font=dict(size=11, color="#9CA3AF"),
    ),
    yaxis=dict(
        gridcolor="rgba(31,41,55,0.8)",
        linecolor="#1F2937",
        tickfont=dict(size=11, color="#6B7280"),
        title_font=dict(size=11, color="#9CA3AF"),
    ),
)


def _chart(**overrides):
    """Return a Plotly layout dict merged with the design-system base."""
    layout = dict(_CHART_LAYOUT)
    # Deep-merge axis overrides so callers can add axis titles without replacing everything
    for k, v in overrides.items():
        if k in ("xaxis", "yaxis") and isinstance(v, dict):
            layout[k] = {**layout.get(k, {}), **v}
        else:
            layout[k] = v
    return layout


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def api_get(path: str) -> Optional[Any]:
    try:
        r = _http_client.get(f"{_get_api_base()}{path}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def api_post(path: str, data: dict = None) -> Optional[Any]:
    try:
        r = _http_client.post(f"{_get_api_base()}{path}", json=data or {})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def severity_badge(sev: str) -> str:
    return f'<span class="badge-{sev.lower()}">{sev.upper()}</span>'


def safety_badge(level: str) -> str:
    labels = {
        "auto_fix": "L1: AUTO",
        "approval_required": "L2: APPROVAL",
        "suggest_only": "L3: SUGGEST",
    }
    return f'<span class="badge-{level}">{labels.get(level, level)}</span>'


def status_dot(color: str = "green") -> str:
    return f'<span class="status-dot-{color}"></span>'


@st.cache_data(ttl=120)
def _fetch_cluster_namespaces() -> List[str]:
    """Fetch namespace list from the cluster (cached 2 min)."""
    data = api_get("/api/v1/cluster/namespaces")
    if data and data.get("namespaces"):
        return data["namespaces"]
    return []


def namespace_selector(key: str, label: str = "Namespace") -> str:
    """Render a selectbox with live cluster namespaces. Returns selected ns or empty string."""
    ns_list = _fetch_cluster_namespaces()
    options = ["All namespaces"] + ns_list
    selected = st.selectbox(label, options, key=key, label_visibility="visible")
    return "" if selected == "All namespaces" else selected


def empty_state(icon: str, title: str, body: str = "") -> None:
    st.markdown(
        f'<div class="empty-state">'
        f'<span class="empty-state-icon">{icon}</span>'
        f'<span class="empty-state-title">{title}</span>'
        f'<span class="empty-state-body">{body}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    # Brand
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;padding:4px 0 12px 0;">'
        '<span style="font-size:1.4rem;">🛡️</span>'
        '<div>'
        '<div style="font-size:0.95rem;font-weight:800;color:#F9FAFB;letter-spacing:-0.3px;">AI SRE Operator</div>'
        '<div style="font-size:0.7rem;color:#6B7280;margin-top:1px;">Kubernetes Observability</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # API status pill
    _health = api_get("/health")
    if _health:
        _is_demo = _health.get("demo_mode", True)
        _ver = _health.get("version", "?")
        if _is_demo:
            st.markdown(
                f'<div style="display:inline-flex;align-items:center;gap:6px;'
                f'background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);'
                f'border-radius:99px;padding:4px 10px;font-size:0.72rem;font-weight:600;color:#FCD34D;">'
                f'{status_dot("yellow")}Demo Mode · v{_ver}</div>',
                unsafe_allow_html=True,
            )
        else:
            _cluster = _health.get("cluster", "k8s")
            st.markdown(
                f'<div style="display:inline-flex;align-items:center;gap:6px;'
                f'background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.25);'
                f'border-radius:99px;padding:4px 10px;font-size:0.72rem;font-weight:600;color:#86EFAC;">'
                f'{status_dot("green")}Live · {_cluster} · v{_ver}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:6px;'
            f'background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);'
            f'border-radius:99px;padding:4px 10px;font-size:0.72rem;font-weight:600;color:#FCA5A5;">'
            f'{status_dot("red")}API Offline</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # Navigation — single radio, CSS group separators
    _page = st.radio(
        "Navigate",
        options=[
            "🏠 Overview",
            "⚡ Live Incidents",
            "🔔 Alerts & Monitoring",
            "📊 APM Services",
            "🏥 Health Rules",
            "🧠 RCA Analysis",
            "🔧 Remediation",
            "🔍 Cluster Scan",
            "📚 Incident History",
            "📖 Knowledge Base",
            "🧪 Learning & Feedback",
            "📈 Learning Insights",
            "🌐 Multi-Cluster",
        ],
        label_visibility="collapsed",
        key="nav_page",
    )

    st.divider()

    # Connection settings collapsed
    with st.expander("⚙️ Connection", expanded=False):
        api_url = st.text_input("API URL", value=_get_api_base(), key="sidebar_api_url",
                                label_visibility="visible")
        if api_url:
            st.session_state["api_base_url"] = api_url
        _current = _get_api_base()
        if any(k in _current for k in (".eks.amazonaws.com", ".azmk8s.io", "container.googleapis.com")):
            st.error("⚠️ URL points to K8s API, not SRE Operator.")
        if st.button("↺ Reset to default", key="reset_api_url", use_container_width=True):
            st.session_state["api_base_url"] = _DEFAULT_API_BASE
            st.rerun()

    st.caption("v0.3.0 · AI K8s SRE Operator")

    # Operator loop status & controls
    st.divider()
    _op_status = api_get("/api/v1/operator/status")
    _op_running = _op_status.get("running", False) if _op_status else False
    if _op_running:
        _cycle_count = _op_status.get("cycles_completed", 0)
        _interval = _op_status.get("interval_secs", 30)
        st.markdown(
            f'<div style="font-size:0.78rem">{status_dot("green")} '
            f'Operator running · {_interval}s · {_cycle_count} cycles</div>',
            unsafe_allow_html=True,
        )
        if st.button("⏹ Stop Operator", key="stop_op", use_container_width=True):
            api_post("/api/v1/operator/stop")
            st.rerun()
    else:
        st.markdown(
            f'<div style="font-size:0.78rem">{status_dot("gray")} '
            f'Operator stopped</div>',
            unsafe_allow_html=True,
        )
        _start_interval = st.number_input("Scan interval (s)", min_value=10, max_value=300, value=30, key="op_interval")
        if st.button("▶ Start Operator", key="start_op", type="primary", use_container_width=True):
            api_post(f"/api/v1/operator/start?interval_secs={_start_interval}")
            st.rerun()

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

_page_icons = {
    "🏠 Overview": "🏠",
    "⚡ Live Incidents": "⚡",
    "🔔 Alerts & Monitoring": "🔔",
    "📊 APM Services": "📊",
    "🏥 Health Rules": "🏥",
    "🧠 RCA Analysis": "🧠",
    "🔧 Remediation": "🔧",
    "🔍 Cluster Scan": "🔍",
    "📚 Incident History": "📚",
    "📖 Knowledge Base": "📖",
    "🧪 Learning & Feedback": "🧪",
    "📈 Learning Insights": "📈",
    "🌐 Multi-Cluster": "🌐",
}

_page_subtitles = {
    "🏠 Overview": "Real-time platform health at a glance",
    "⚡ Live Incidents": "Active incidents detected in your cluster",
    "🔔 Alerts & Monitoring": "Unified alerts across health rules, anomalies, and incidents",
    "📊 APM Services": "Latency, error rate, and service health from sidecar agents",
    "🏥 Health Rules": "Threshold-based monitoring rules and open violations",
    "🧠 RCA Analysis": "AI-powered root cause analysis with evidence correlation",
    "🔧 Remediation": "Ranked remediation plans with dry-run preview",
    "🔍 Cluster Scan": "On-demand cluster scan for new incidents",
    "📚 Incident History": "Historical incident record and failure pattern analysis",
    "📖 Knowledge Base": "Failure pattern library powering AI analysis",
    "🧪 Learning & Feedback": "Operator feedback loop that improves AI accuracy",
    "📈 Learning Insights": "Remediation outcomes, audit trail, and action rankings",
    "🌐 Multi-Cluster": "Fleet-wide health across registered clusters",
}

_ph_left, _ph_right = st.columns([5, 1])
with _ph_left:
    st.markdown(
        f'<div class="page-title">{_page}</div>'
        f'<div class="page-subtitle">{_page_subtitles.get(_page, "")}</div>',
        unsafe_allow_html=True,
    )
with _ph_right:
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    if _page == "🏠 Overview":
        if st.button("⟳ Refresh", key="hdr_refresh", use_container_width=True):
            st.rerun()
    elif _page == "🔍 Cluster Scan":
        if st.button("🚀 Run Scan", type="primary", key="hdr_scan", use_container_width=True):
            with st.spinner("Scanning..."):
                _scan_r = api_post("/api/v1/scan")
            if _scan_r:
                st.success(f"✅ {_scan_r.get('incidents_created', 0)} incidents created")

st.divider()

# ===========================================================================
# PAGE: Overview
# ===========================================================================

if _page == "🏠 Overview":
    # ── KPI row 1 ──────────────────────────────────────────────────────────
    summary = api_get("/api/v1/cluster/summary")
    score = 0
    if summary:
        score = summary.get("health_score", 0)
        _score_color = "#22C55E" if score >= 75 else ("#F59E0B" if score >= 50 else "#EF4444")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Health Score", f"{score:.0f}/100")
        k2.metric("Nodes Ready", f"{summary.get('ready_nodes', 0)}/{summary.get('total_nodes', 0)}")
        k3.metric("Pods Running", summary.get("running_pods", 0))
        k4.metric("Pending Pods", summary.get("pending_pods", 0))

    # ── KPI row 2 ──────────────────────────────────────────────────────────
    incidents_all = api_get("/api/v1/incidents?limit=200") or []
    _hr_s = api_get("/api/v1/health-rules/violations?status=open&limit=1")
    _hr_open = (_hr_s.get("summary", {}).get("open_violations", 0) if _hr_s else 0)
    _critical = sum(1 for i in incidents_all if i.get("severity") == "critical")
    _active = sum(1 for i in incidents_all if i.get("status") not in ("resolved", "closed"))

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Active Incidents", _active)
    k6.metric("Critical", _critical)
    k7.metric("CrashLoop Pods", summary.get("crashloop_pods", 0) if summary else 0)
    k8.metric("Rule Violations", _hr_open)

    st.divider()

    # ── Charts row ─────────────────────────────────────────────────────────
    _ns_clicked = ""
    _type_clicked = ""
    try:
        import pandas as pd
        import plotly.express as px
        import plotly.graph_objects as go

        ch_left, ch_mid, ch_right = st.columns([2, 1, 1])

        # Incident trend line
        with ch_left:
            st.markdown('<span class="section-header">Incident Timeline</span>', unsafe_allow_html=True)
            if incidents_all:
                df_timeline = pd.DataFrame([
                    {
                        "Detected": (i.get("detected_at") or i.get("created_at") or i.get("timestamp") or "")[:10],
                        "Severity": i.get("severity", "low"),
                    }
                    for i in incidents_all if (i.get("detected_at") or i.get("created_at") or i.get("timestamp"))
                ])
                if not df_timeline.empty:
                    df_grouped = (
                        df_timeline.groupby(["Detected", "Severity"])
                        .size()
                        .reset_index(name="Count")
                    )
                    fig_tl = px.bar(
                        df_grouped,
                        x="Detected",
                        y="Count",
                        color="Severity",
                        color_discrete_map={
                            "critical": "#EF4444",
                            "high": "#F97316",
                            "medium": "#F59E0B",
                            "low": "#22C55E",
                        },
                        barmode="stack",
                    )
                    fig_tl.update_layout(**_chart(height=280))
                    st.plotly_chart(fig_tl, use_container_width=True, key="overview_timeline")
            else:
                empty_state("📊", "No incidents yet", "Run a cluster scan to populate the timeline")

        # Namespace donut — interactive
        with ch_mid:
            st.markdown('<span class="section-header">By Namespace</span>', unsafe_allow_html=True)
            if incidents_all:
                ns_counts: dict = {}
                for i in incidents_all:
                    ns = i.get("namespace", "default")
                    ns_counts[ns] = ns_counts.get(ns, 0) + 1
                df_ns = pd.DataFrame(
                    [{"Namespace": k, "Count": v} for k, v in sorted(ns_counts.items(), key=lambda x: -x[1])[:10]]
                )
                fig_ns = go.Figure(go.Pie(
                    labels=df_ns["Namespace"],
                    values=df_ns["Count"],
                    hole=0.55,
                    textposition="inside",
                    textinfo="percent+label",
                    hovertemplate="<b>%{label}</b><br>Incidents: %{value}<br>%{percent}<extra></extra>",
                    marker=dict(
                        colors=px.colors.qualitative.Set2[:len(df_ns)],
                        line=dict(color="rgba(0,0,0,0.3)", width=1),
                    ),
                    pull=[0.03] * len(df_ns),
                ))
                fig_ns.update_layout(**_chart(height=280, showlegend=False))
                _ns_event = st.plotly_chart(
                    fig_ns, use_container_width=True, key="overview_ns_pie",
                    on_select="rerun",
                )
                # Capture click
                _ns_clicked = ""
                if _ns_event and hasattr(_ns_event, "selection") and _ns_event.selection:
                    sel = _ns_event.selection
                    pts = getattr(sel, "points", None) or (sel.get("points", []) if isinstance(sel, dict) else [])
                    if pts:
                        p = pts[0]
                        _ns_clicked = p.get("label", "") if isinstance(p, dict) else getattr(p, "label", "")
                        st.info(f"🔍 Filtering by namespace: **{_ns_clicked}**")
            else:
                empty_state("🌐", "No data", "")

        # Incident type donut — interactive
        with ch_right:
            st.markdown('<span class="section-header">By Type</span>', unsafe_allow_html=True)
            if incidents_all:
                type_counts: dict = {}
                for i in incidents_all:
                    t = i.get("incident_type", "Unknown")
                    type_counts[t] = type_counts.get(t, 0) + 1
                df_type = pd.DataFrame(
                    [{"Type": k, "Count": v} for k, v in sorted(type_counts.items(), key=lambda x: -x[1])[:10]]
                )
                fig_type = go.Figure(go.Pie(
                    labels=df_type["Type"],
                    values=df_type["Count"],
                    hole=0.55,
                    textposition="inside",
                    textinfo="percent+label",
                    hovertemplate="<b>%{label}</b><br>Incidents: %{value}<br>%{percent}<extra></extra>",
                    marker=dict(
                        colors=px.colors.qualitative.Pastel[:len(df_type)],
                        line=dict(color="rgba(0,0,0,0.3)", width=1),
                    ),
                    pull=[0.03] * len(df_type),
                ))
                fig_type.update_layout(**_chart(height=280, showlegend=False))
                _type_event = st.plotly_chart(
                    fig_type, use_container_width=True, key="overview_type_pie",
                    on_select="rerun",
                )
                # Capture click
                _type_clicked = ""
                if _type_event and hasattr(_type_event, "selection") and _type_event.selection:
                    sel = _type_event.selection
                    pts = getattr(sel, "points", None) or (sel.get("points", []) if isinstance(sel, dict) else [])
                    if pts:
                        p = pts[0]
                        _type_clicked = p.get("label", "") if isinstance(p, dict) else getattr(p, "label", "")
                        st.info(f"🔍 Filtering by type: **{_type_clicked}**")
            else:
                empty_state("📋", "No data", "")

    except ImportError:
        pass

    # ── Apply interactive filters from pie clicks ──────────────────────
    _filtered_incidents = list(incidents_all)
    _active_filter = ""
    if _ns_clicked:
        _filtered_incidents = [i for i in _filtered_incidents if i.get("namespace") == _ns_clicked]
        _active_filter = f"namespace = {_ns_clicked}"
    if _type_clicked:
        _filtered_incidents = [i for i in _filtered_incidents if i.get("incident_type") == _type_clicked]
        _active_filter += (" & " if _active_filter else "") + f"type = {_type_clicked}"

    # ── Recent incidents table ──────────────────────────────────────────
    st.markdown('<span class="section-header">Recent Incidents</span>', unsafe_allow_html=True)
    if _active_filter:
        st.caption(f"Filtered: {_active_filter} — click a chart slice to filter, refresh to clear")
    _display_incidents = _filtered_incidents if _filtered_incidents else incidents_all
    if _display_incidents:
        try:
            import pandas as pd
            recent = _display_incidents[:20]
            df_recent = pd.DataFrame([
                {
                    "Severity": i.get("severity", "").upper(),
                    "Type": i.get("incident_type", ""),
                    "Namespace": i.get("namespace", ""),
                    "Workload": i.get("workload", ""),
                    "Title": i.get("title", "")[:55],
                    "Status": i.get("status", ""),
                    "Detected": i.get("detected_at", "")[:19],
                }
                for i in recent
            ])
            st.dataframe(
                df_recent,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Severity": st.column_config.TextColumn(width="small"),
                    "Type": st.column_config.TextColumn(width="medium"),
                    "Namespace": st.column_config.TextColumn(width="small"),
                    "Workload": st.column_config.TextColumn(width="medium"),
                },
            )
            if _active_filter:
                st.caption(f"Showing {len(recent)} of {len(_display_incidents)} filtered incidents")
        except Exception:
            pass
    else:
        empty_state("✅", "All clear — no incidents detected", "Run a cluster scan to get started")

# ===========================================================================
# PAGE: Live Incidents
# ===========================================================================

if _page == "⚡ Live Incidents":
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        sev_filter = st.selectbox("Severity", ["All", "critical", "high", "medium", "low"])
    with col2:
        ns_filter = namespace_selector(key="incidents_ns")
    with col3:
        _q_cols = st.columns(3)
        if _q_cols[0].button("🚀 Run Scan", type="primary", key="li_scan"):
            with st.spinner("Scanning cluster..."):
                _sr = api_post(f"/api/v1/scan{'?namespace=' + ns_filter if ns_filter else ''}")
            if _sr:
                st.success(f"✅ {_sr.get('incidents_created', 0)} new incidents created")
                st.rerun()
        if _q_cols[1].button("🔄 Refresh", key="li_refresh"):
            st.rerun()

    params = "?"
    if sev_filter != "All":
        params += f"severity={sev_filter}&"
    if ns_filter:
        params += f"namespace={ns_filter}&"

    incidents = api_get(f"/api/v1/incidents{params}")

    if not incidents:
        empty_state("✅", "No incidents detected", "Run a cluster scan or load an example to get started.")
    else:
        # Summary counts
        _sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for inc in incidents:
            s = inc.get("severity", "low")
            if s in _sev_counts:
                _sev_counts[s] += 1
        _ic1, _ic2, _ic3, _ic4, _ic5 = st.columns(5)
        _ic1.metric("Total", len(incidents))
        _ic2.metric("Critical 🔴", _sev_counts["critical"])
        _ic3.metric("High 🟠", _sev_counts["high"])
        _ic4.metric("Medium 🟡", _sev_counts["medium"])
        _ic5.metric("Low 🟢", _sev_counts["low"])

        st.divider()

        for inc in incidents:
            sev = inc.get("severity", "info")
            status = inc.get("status", "detected")
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")

            with st.expander(
                f"{icon} [{inc.get('incident_type', '?')}]  "
                f"{inc.get('workload', '?')} / {inc.get('namespace', '?')}  —  "
                f"{inc.get('title', '')[:60]}"
            ):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Severity:** {severity_badge(sev)}", unsafe_allow_html=True)
                c2.markdown(f"**Status:** `{status}`")
                c3.markdown(f"**Detected:** `{inc.get('detected_at', '')[:19]}`")

                if inc.get("root_cause"):
                    st.info(f"🎯 **Root Cause:** {inc['root_cause']}")
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
                    st.divider()
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
                            "correct_root_cause": rca_correct.startswith("Yes"),
                            "fix_worked": fix_worked.startswith("Yes"),
                            "operator_notes": notes,
                            "better_remediation": better_fix if better_fix else None,
                        }
                        fb_result = api_post("/api/v1/feedback/structured", fb_payload)
                        if fb_result:
                            st.success(
                                f"✅ Feedback recorded! "
                                f"Learned patterns: {fb_result.get('learning_stats', {}).get('total_learned_patterns', 0)}"
                            )

# ===========================================================================
# PAGE: RCA Analysis
# ===========================================================================

if _page == "🧠 RCA Analysis":
    inc_id = st.text_input("Incident ID", key="rca_inc_id", placeholder="Paste incident UUID from Live Incidents")

    if not inc_id:
        empty_state("🧠", "Enter an incident ID above", "Paste a UUID from the Live Incidents page to begin analysis")
    else:
        inc_data = api_get(f"/api/v1/incidents/{inc_id}")
        if inc_data:
            st.markdown(f"#### {inc_data.get('title')}")
            c1, c2, c3 = st.columns(3)
            c1.markdown(
                f"**Severity:** {severity_badge(inc_data.get('severity', '?'))}",
                unsafe_allow_html=True,
            )
            c2.markdown(f"**Type:** `{inc_data.get('incident_type', '?')}`")
            c3.markdown(f"**Status:** `{inc_data.get('status', '?')}`")

            if st.button("▶️ Run Full AI Analysis", type="primary"):
                with st.spinner("Correlating signals, retrieving past incidents, calling AI..."):
                    result = api_post(f"/api/v1/incidents/{inc_id}/analyze")
                if result:
                    inc_data = result

            if inc_data.get("root_cause"):
                st.divider()
                st.markdown('<span class="section-header">🎯 Root Cause</span>', unsafe_allow_html=True)
                st.error(inc_data["root_cause"])
                if inc_data.get("confidence"):
                    st.progress(
                        inc_data["confidence"],
                        text=f"Confidence: {inc_data['confidence']:.0%}",
                    )

            if inc_data.get("ai_explanation"):
                st.markdown('<span class="section-header">📖 AI Explanation</span>', unsafe_allow_html=True)
                st.markdown(inc_data["ai_explanation"])

            if inc_data.get("contributing_factors"):
                st.markdown('<span class="section-header">🔗 Contributing Factors</span>', unsafe_allow_html=True)
                for cf in inc_data["contributing_factors"]:
                    st.markdown(f"- {cf}")

            if inc_data.get("evidence"):
                st.markdown('<span class="section-header">🔬 Evidence</span>', unsafe_allow_html=True)
                for ev in inc_data["evidence"]:
                    relevance = ev.get("relevance", 1.0)
                    source = ev.get("source", "?")
                    with st.expander(f"[{source}] relevance={relevance:.0%}"):
                        st.code(ev.get("content", ""), language="text")

            # Knowledge Base Matches
            kb_results = api_get(
                f"/api/v1/knowledge/search?q={inc_data.get('incident_type', '')}"
                f"+{inc_data.get('namespace', '')}&top_k=3"
            )
            if kb_results:
                st.markdown('<span class="section-header">📖 Knowledge Base Matches</span>', unsafe_allow_html=True)
                for kb in kb_results:
                    score = kb.get("score", 0)
                    safety = kb.get("safety_level", "suggest_only")
                    with st.expander(
                        f"[{kb.get('id', '?')}] {kb.get('title', '')} — score={score:.2f}"
                    ):
                        st.markdown(
                            f"**Safety:** {safety_badge(safety)}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**Root cause:** {kb.get('root_cause', '')}")
                        steps = kb.get("remediation_steps", [])
                        if steps:
                            st.markdown("**Remediation steps:**")
                            for i, step in enumerate(steps[:3], 1):
                                st.markdown(f"{i}. {step}")
                        tags = kb.get("tags", [])
                        if tags:
                            st.markdown(" ".join(f"`{t}`" for t in tags))

            # Similar Past Incidents
            similar_data = api_get(f"/api/v1/incidents/{inc_id}/similar")
            if similar_data:
                st.markdown('<span class="section-header">🔁 Similar Past Incidents</span>', unsafe_allow_html=True)
                for sim in similar_data[:3]:
                    outcome = sim.get("resolution_outcome") or (
                        "resolved" if sim.get("resolved") else None
                    )
                    feedback_icon = (
                        "✅" if outcome == "resolved" else ("❌" if outcome == "failed" else "—")
                    )
                    with st.expander(
                        f"{feedback_icon} similarity={sim.get('similarity', 0):.2f} | "
                        f"{sim.get('type', '?')} in {sim.get('namespace', '?')}"
                    ):
                        if sim.get("root_cause"):
                            st.markdown(f"**Root cause:** {sim['root_cause']}")
                        if sim.get("suggested_fix"):
                            st.markdown(f"**Fix:** {sim['suggested_fix']}")

# ===========================================================================
# PAGE: Remediation
# ===========================================================================

if _page == "🔧 Remediation":
    rem_inc_id = st.text_input(
        "Incident ID", key="rem_inc_id", placeholder="Paste incident UUID"
    )

    if not rem_inc_id:
        empty_state("🔧", "Enter an incident ID above", "Paste a UUID to view AI-generated remediation plans with safety levels")
    else:
        col1, col2 = st.columns(2)
        dry_run = col1.checkbox("Dry Run Mode", value=True)
        get_plan = col2.button("📋 Get Remediation Plan", type="primary")

        plan_data = None
        if get_plan:
            plan_data = api_get(f"/api/v1/incidents/{rem_inc_id}/remediation")

        if plan_data:
            st.markdown(f"**Plan:** {plan_data.get('summary')}")
            st.markdown(
                f"**Overall Safety:** {safety_badge(plan_data.get('overall_safety_level', '?'))}",
                unsafe_allow_html=True,
            )

            if plan_data.get("requires_approval"):
                st.warning("⚠️ This plan requires approval before execution.")
                if st.button("✅ Approve Plan"):
                    result = api_post(f"/api/v1/incidents/{rem_inc_id}/remediation/approve")
                    if result:
                        st.success("Plan approved!")

            st.markdown('<span class="section-header">Steps</span>', unsafe_allow_html=True)
            for step in plan_data.get("steps", []):
                level = step.get("safety_level", "?")
                level_label = {
                    "auto_fix": "L1: AUTO",
                    "approval_required": "L2: APPROVAL",
                    "suggest_only": "L3: SUGGEST",
                }.get(level, level)
                with st.expander(f"Step {step['order']}: {step['action']} [{level_label}]"):
                    st.markdown(safety_badge(level), unsafe_allow_html=True)
                    st.markdown(f"**Description:** {step.get('description', '')}")
                    if step.get("command"):
                        st.code(step["command"], language="bash")
                    st.markdown(
                        f"Reversible: {'✅' if step.get('reversible') else '❌'}  |  "
                        f"Est. Duration: {step.get('estimated_duration_secs', 0)}s"
                    )

            bc1, bc2 = st.columns(2)
            if bc1.button("▶️ Execute (Dry Run)" if dry_run else "▶️ Execute", type="primary"):
                with st.spinner("Executing remediation..."):
                    result = api_post(
                        f"/api/v1/incidents/{rem_inc_id}/remediation/execute?dry_run={str(dry_run).lower()}"
                    )
                if result:
                    st.code(result.get("output", ""), language="text")

# ===========================================================================
# PAGE: APM Services
# ===========================================================================

if _page == "📊 APM Services":
    apm_col1, apm_col2 = st.columns([3, 1])
    with apm_col1:
        apm_ns = namespace_selector(key="apm_ns_filter", label="Namespace filter")
    apm_auto_refresh = apm_col2.checkbox("Auto-refresh", value=False, key="apm_refresh")

    apm_params = f"?namespace={apm_ns}" if apm_ns else ""
    apm_data = api_get(f"/api/v1/apm/services{apm_params}")

    if apm_data:
        total_svcs = len(apm_data)
        healthy = sum(1 for s in apm_data if s.get("health_score", 0) > 80)
        degraded = sum(1 for s in apm_data if 50 < s.get("health_score", 0) <= 80)
        critical_svcs = total_svcs - healthy - degraded
        avg_err = sum(s.get("error_rate", 0) for s in apm_data) / max(total_svcs, 1)

        mm1, mm2, mm3, mm4, mm5 = st.columns(5)
        mm1.metric("Services", total_svcs)
        mm2.metric("Healthy 🟢", healthy)
        mm3.metric("Degraded 🟡", degraded)
        mm4.metric("Critical 🔴", critical_svcs)
        mm5.metric("Avg Error Rate", f"{avg_err:.1%}")

        st.divider()

        # Latency & error rate charts
        try:
            import pandas as pd
            import plotly.express as px

            latency_rows = []
            err_rate_rows = []
            for svc in apm_data:
                svc_key = f"{svc.get('namespace', '?')}/{svc.get('service_name', '?')}"
                detail = (
                    api_get(
                        f"/api/v1/apm/services/{svc.get('service_name', '?')}"
                        f"?namespace={svc.get('namespace', '')}"
                    )
                    or {}
                )
                history = detail.get("report_history", [])
                for h in history[-20:]:
                    ts = h.get("received_at", "")[:19]
                    metrics = h.get("metrics", {})
                    latency_rows.append({
                        "Time": ts,
                        "Service": svc_key,
                        "p50 (ms)": metrics.get("latency_p50_ms", 0),
                        "p95 (ms)": metrics.get("latency_p95_ms", 0),
                        "p99 (ms)": metrics.get("latency_p99_ms", 0),
                    })
                    err_rate_rows.append({
                        "Time": ts,
                        "Service": svc_key,
                        "Error Rate": h.get("error_rate", 0),
                    })

            ch_l, ch_r = st.columns(2)
            if latency_rows:
                df_lat = pd.DataFrame(latency_rows)
                with ch_l:
                    st.markdown('<span class="section-header">p95 Latency Trends</span>', unsafe_allow_html=True)
                    fig_lat = px.line(df_lat, x="Time", y="p95 (ms)", color="Service", markers=True)
                    fig_lat.add_hline(y=1000, line_dash="dot", line_color="#EF4444",
                                      annotation_text="1s SLO")
                    fig_lat.update_layout(**_chart(height=300))
                    st.plotly_chart(fig_lat, use_container_width=True)

            if err_rate_rows:
                df_err = pd.DataFrame(err_rate_rows)
                with ch_r:
                    st.markdown('<span class="section-header">Error Rate Trends</span>', unsafe_allow_html=True)
                    fig_err = px.area(df_err, x="Time", y="Error Rate", color="Service")
                    fig_err.update_yaxes(tickformat=".0%")
                    fig_err.add_hline(y=0.05, line_dash="dot", line_color="#F59E0B",
                                      annotation_text="5% threshold")
                    fig_err.update_layout(**_chart(height=300))
                    st.plotly_chart(fig_err, use_container_width=True)

        except ImportError:
            pass

        st.divider()

        # Per-service cards
        st.markdown('<span class="section-header">Service Health</span>', unsafe_allow_html=True)
        for svc in sorted(apm_data, key=lambda s: s.get("health_score", 100)):
            health = svc.get("health_score", 0)
            health_icon = "🟢" if health > 80 else ("🟡" if health > 50 else "🔴")
            with st.expander(
                f"{health_icon} {svc.get('service_name', '?')} "
                f"({svc.get('namespace', '?')}) — health {health}/100"
            ):
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("Health Score", f"{health}/100")
                sc2.metric("Error Rate", f"{svc.get('error_rate', 0):.1%}")
                sc3.metric("Error Count", svc.get("error_count", 0))
                sc4.metric("Agent", svc.get("agent_version", "?"))

                lm = svc.get("metrics", {})
                if lm.get("latency_p50_ms") or lm.get("latency_p95_ms"):
                    lc1, lc2, lc3 = st.columns(3)
                    lc1.metric("p50 Latency", f"{lm.get('latency_p50_ms', 0):.0f}ms")
                    lc2.metric("p95 Latency", f"{lm.get('latency_p95_ms', 0):.0f}ms")
                    lc3.metric("p99 Latency", f"{lm.get('latency_p99_ms', 0):.0f}ms")

                # Fetch full detail for patterns and errors
                _svc_detail = api_get(
                    f"/api/v1/apm/services/{svc.get('service_name', '?')}"
                    f"?namespace={svc.get('namespace', '')}"
                ) or {}

                # Show detected error patterns with samples
                _patterns = _svc_detail.get("patterns_detected", svc.get("patterns_detected", []))
                if _patterns:
                    st.markdown("**🚨 Detected Error Patterns:**")
                    for p in _patterns[:10]:
                        p_name = p.get("pattern_name", p.get("pattern_id", "?"))
                        p_count = p.get("count", 1)
                        p_sev = p.get("severity", "medium")
                        st.markdown(
                            f"- {severity_badge(p_sev)} **{p_name}** × {p_count}",
                            unsafe_allow_html=True,
                        )
                        p_sample = p.get("sample", "")
                        if p_sample:
                            st.code(p_sample[:800], language="text")

                # Show actual error lines / tracebacks
                _novel = _svc_detail.get("novel_errors", [])
                if _novel:
                    st.markdown("**📋 Recent Error Lines & Tracebacks:**")
                    for idx, err_line in enumerate(_novel[:10]):
                        if "\n" in err_line:
                            # Multi-line traceback
                            st.code(err_line[:1500], language="python")
                        else:
                            st.code(err_line[:500], language="text")
                elif svc.get("error_count", 0) == 0:
                    st.success("No errors detected in this reporting window")

                top = svc.get("top_patterns", [])
                if top:
                    st.markdown("**Top patterns:** " + ", ".join(f"`{p}`" for p in top[:5]))
                st.caption(f"Last report: {svc.get('last_report', '?')[:19]}")
    else:
        empty_state(
            "📡",
            "No APM data yet",
            "Deploy the sidecar agent to start monitoring application performance.",
        )

    # Anomaly alerts
    st.divider()
    st.markdown('<span class="section-header">⚡ Proactive Anomaly Alerts</span>', unsafe_allow_html=True)
    anomaly_data = api_get(
        f"/api/v1/anomaly/alerts?limit=20{('&namespace=' + apm_ns) if apm_ns else ''}"
    )
    if anomaly_data and anomaly_data.get("alerts"):
        alerts = anomaly_data["alerts"]
        st.caption(f"{len(alerts)} alert(s) — early-warning signals before incidents form")
        for alert in alerts:
            sev = alert.get("severity", "warning")
            icon = "🔴" if sev == "critical" else "🟡"
            with st.expander(
                f"{icon} [{sev.upper()}] {alert.get('alert_type', '?')} — "
                f"{alert.get('namespace', '?')}/{alert.get('service', '?')}"
            ):
                st.markdown(f"**Message:** {alert.get('message', '')}")
                ac1, ac2 = st.columns(2)
                ac1.metric("Current", f"{alert.get('current_value', 0):.1f}")
                ac2.metric("Baseline", f"{alert.get('baseline_value', 0):.1f}")
                st.caption(f"Detected: {alert.get('timestamp', '')[:19]}")
    else:
        st.success("✅ No anomalies — all services within normal parameters")

    # Error patterns
    st.divider()
    st.markdown('<span class="section-header">🚨 Error Patterns Across Services</span>', unsafe_allow_html=True)
    err_sev = st.selectbox(
        "Severity", ["All", "critical", "high", "medium", "low"], key="apm_err_sev"
    )
    err_params = "?limit=20"
    if err_sev != "All":
        err_params += f"&severity={err_sev}"
    if apm_ns:
        err_params += f"&namespace={apm_ns}"
    apm_errors = api_get(f"/api/v1/apm/errors{err_params}")
    if apm_errors:
        for err in apm_errors:
            sev = err.get("severity", "medium")
            with st.expander(
                f"{severity_badge(sev)} {err.get('pattern_name', '?')} — "
                f"{err.get('total_count', 0)} total",
            ):
                st.markdown(f"**Type:** `{err.get('incident_type', '?')}`")
                st.markdown(f"**Affected services:** {', '.join(err.get('affected_services', []))}")
                if err.get("sample"):
                    st.code(err["sample"], language="text")
                if err.get("remediation_hint"):
                    st.success(f"💡 {err['remediation_hint']}")
    else:
        st.info("No error patterns detected yet.")

# ===========================================================================
# PAGE: Health Rules
# ===========================================================================

if _page == "🏥 Health Rules":
    hr_col1, hr_col2 = st.columns([3, 1])
    if hr_col2.button("▶️ Evaluate Now", type="primary", key="hr_eval"):
        eval_result = api_post("/api/v1/health-rules/evaluate")
        if eval_result:
            new_v = eval_result.get("new_violations", 0)
            if new_v:
                st.warning(f"⚠️ {new_v} new violation(s) detected!")
            else:
                st.success("✅ All rules passed — no new violations")

    hr_data = api_get("/api/v1/health-rules")
    if hr_data:
        hr_summary = hr_data.get("summary", {})
        hm1, hm2, hm3, hm4, hm5 = st.columns(5)
        hm1.metric("Total Rules", hr_summary.get("total_rules", 0))
        hm2.metric("Enabled", hr_summary.get("enabled_rules", 0))
        hm3.metric("Open Violations", hr_summary.get("open_violations", 0))
        hm4.metric("Critical 🔴", hr_summary.get("critical_open", 0))
        hm5.metric("Warning 🟡", hr_summary.get("warning_open", 0))

        st.divider()

        # Open violations
        violations_data = api_get("/api/v1/health-rules/violations?status=open")
        if violations_data and violations_data.get("violations"):
            st.markdown('<span class="section-header">🚨 Open Violations</span>', unsafe_allow_html=True)
            for v in violations_data["violations"]:
                sev = v.get("severity", "warning")
                icon = "🔴" if sev == "critical" else "🟡"
                with st.expander(
                    f"{icon} [{sev.upper()}] {v.get('rule_name', '?')} — "
                    f"{v.get('namespace', '?')}/{v.get('service_name', '?')}"
                ):
                    vc1, vc2, vc3 = st.columns(3)
                    vc1.metric("Current", f"{v.get('current_value', 0):.4g}")
                    vc2.metric("Threshold", f"{v.get('threshold', 0):.4g}")
                    vc3.metric("Metric", v.get("metric", "?"))
                    st.markdown(f"**Message:** {v.get('message', '')}")
                    st.caption(f"Opened: {v.get('opened_at', '')[:19]}")
                    if st.button("✅ Acknowledge", key=f"ack_{v.get('id', '')[:8]}"):
                        ack = api_post(f"/api/v1/health-rules/violations/{v['id']}/acknowledge")
                        if ack:
                            st.success("Acknowledged")
                            st.rerun()
        else:
            st.success("✅ No open violations — all health rules passing")

        st.divider()

        # Rules list
        st.markdown('<span class="section-header">📋 Configured Rules</span>', unsafe_allow_html=True)
        rules = hr_data.get("rules", [])
        for rule in rules:
            enabled_icon = "✅" if rule.get("enabled") else "⏸️"
            sev = rule.get("severity", "warning")
            with st.expander(
                f"{enabled_icon} {rule.get('name', '?')} — "
                f"{rule.get('metric', '?')} {rule.get('operator', '?')} {rule.get('threshold', '?')} "
                f"[{sev.upper()}]"
            ):
                st.markdown(f"**ID:** `{rule.get('id', '?')}`")
                st.markdown(f"**Description:** {rule.get('description', 'No description')}")
                rc1, rc2, rc3 = st.columns(3)
                rc1.markdown(f"**Metric:** `{rule.get('metric', '?')}`")
                rc2.markdown(f"**Condition:** `{rule.get('operator', '?')} {rule.get('threshold', '?')}`")
                rc3.markdown(f"**Severity:** {severity_badge(sev)}", unsafe_allow_html=True)
                if rule.get("namespace_filter"):
                    st.markdown(f"**Namespace filter:** `{rule['namespace_filter']}`")
                if rule.get("service_filter"):
                    st.markdown(f"**Service filter:** `{rule['service_filter']}`")

        st.divider()

        # Create new rule form
        with st.expander("➕ Create New Health Rule"):
            nr_name = st.text_input("Rule Name", placeholder="e.g. High Error Rate - Payments", key="nr_name")
            nr_c1, nr_c2, nr_c3 = st.columns(3)
            nr_metric = nr_c1.selectbox(
                "Metric",
                ["error_rate", "latency_p95", "latency_p99", "health_score",
                 "cpu_usage", "memory_usage", "restart_count", "error_count"],
                key="nr_metric",
            )
            nr_operator = nr_c2.selectbox(
                "Operator", ["gt", "gte", "lt", "lte", "eq", "neq"], key="nr_op"
            )
            nr_threshold = nr_c3.number_input("Threshold", value=0.05, format="%f", key="nr_thresh")
            nr_c4, nr_c5 = st.columns(2)
            nr_severity = nr_c4.selectbox("Severity", ["critical", "warning", "info"], key="nr_sev")
            nr_desc = nr_c5.text_input("Description", key="nr_desc")
            nr_c6, nr_c7 = st.columns(2)
            nr_ns = nr_c6.text_input("Namespace filter (optional)", key="nr_ns")
            nr_svc = nr_c7.text_input("Service filter (optional)", key="nr_svc")

            if st.button("Create Rule", type="primary", key="nr_create"):
                if nr_name:
                    payload = {
                        "name": nr_name,
                        "metric": nr_metric,
                        "operator": nr_operator,
                        "threshold": nr_threshold,
                        "severity": nr_severity,
                        "description": nr_desc,
                        "namespace_filter": nr_ns,
                        "service_filter": nr_svc,
                    }
                    result = api_post("/api/v1/health-rules", payload)
                    if result:
                        st.success(f"✅ Rule '{nr_name}' created (ID: {result.get('id', '?')})")
                        st.rerun()
                else:
                    st.warning("Please enter a rule name")

        # Violation history
        st.divider()
        st.markdown('<span class="section-header">📜 Violation History</span>', unsafe_allow_html=True)
        hist_sev = st.selectbox("Filter severity", ["All", "critical", "warning", "info"], key="vh_sev")
        hist_params = "?limit=50"
        if hist_sev != "All":
            hist_params += f"&severity={hist_sev}"
        hist_data = api_get(f"/api/v1/health-rules/violations{hist_params}")
        if hist_data and hist_data.get("violations"):
            try:
                import pandas as pd

                df_v = pd.DataFrame([
                    {
                        "Time": v.get("opened_at", "")[:19],
                        "Rule": v.get("rule_name", ""),
                        "Severity": v.get("severity", ""),
                        "Service": f"{v.get('namespace', '')}/{v.get('service_name', '')}",
                        "Metric": v.get("metric", ""),
                        "Value": v.get("current_value", 0),
                        "Threshold": v.get("threshold", 0),
                        "Status": v.get("status", ""),
                    }
                    for v in hist_data["violations"]
                ])
                st.dataframe(df_v, use_container_width=True, hide_index=True)
            except ImportError:
                for v in hist_data["violations"]:
                    st.markdown(
                        f"- **{v.get('rule_name', '?')}** on {v.get('namespace', '?')}/"
                        f"{v.get('service_name', '?')} — {v.get('status', '?')}"
                    )
        else:
            st.info("No violation history yet. Evaluate rules to start tracking.")
    else:
        st.error("Could not load health rules — check API connection")

# ===========================================================================
# PAGE: Alerts & Monitoring
# ===========================================================================

if _page == "🔔 Alerts & Monitoring":
    al_c1, al_c2, al_c3 = st.columns([2, 1, 1])
    with al_c1:
        al_ns = namespace_selector(key="alert_ns")
    al_sev = al_c2.selectbox("Severity", ["All", "critical", "high", "warning", "medium", "low"], key="alert_sev")
    al_auto = al_c3.checkbox("Auto-evaluate rules", value=True, key="alert_auto")

    if al_auto:
        api_post("/api/v1/health-rules/evaluate")

    al_params = "?limit=100"
    if al_ns:
        al_params += f"&namespace={al_ns}"
    if al_sev != "All":
        al_params += f"&severity={al_sev}"
    unified = api_get(f"/api/v1/alerts/unified{al_params}")

    if unified:
        total = unified.get("total", 0)
        by_source = unified.get("by_source", {})
        by_severity = unified.get("by_severity", {})

        am1, am2, am3, am4, am5, am6 = st.columns(6)
        am1.metric("Total Alerts", total)
        am2.metric("Critical 🔴", by_severity.get("critical", 0))
        am3.metric("Warning 🟡", by_severity.get("warning", 0) + by_severity.get("high", 0))
        am4.metric("Health Rules", by_source.get("health_rule", 0))
        am5.metric("Anomalies", by_source.get("anomaly", 0))
        am6.metric("Incidents", by_source.get("incident", 0))

        st.divider()

        if total > 0:
            try:
                import pandas as pd
                import plotly.express as px

                src_c1, src_c2 = st.columns(2)
                with src_c1:
                    if by_source:
                        df_src = pd.DataFrame([
                            {"Source": k.replace("_", " ").title(), "Count": v}
                            for k, v in by_source.items()
                        ])
                        fig_src = px.pie(
                            df_src, names="Source", values="Count",
                            title="Alerts by Source",
                            hole=0.45,
                            color_discrete_sequence=["#EF4444", "#F59E0B", "#3B82F6"],
                        )
                        fig_src.update_layout(**_chart(height=280))
                        st.plotly_chart(fig_src, use_container_width=True)

                with src_c2:
                    if by_severity:
                        df_sev_a = pd.DataFrame([
                            {"Severity": k.title(), "Count": v}
                            for k, v in by_severity.items()
                        ])
                        color_map = {
                            "Critical": "#EF4444", "High": "#F97316",
                            "Warning": "#F59E0B", "Medium": "#22C55E",
                            "Low": "#3B82F6", "Info": "#64748B",
                        }
                        fig_sev_a = px.bar(
                            df_sev_a, x="Severity", y="Count",
                            title="Alerts by Severity",
                            color="Severity",
                            color_discrete_map=color_map,
                        )
                        fig_sev_a.update_layout(**_chart(height=280, showlegend=False))
                        st.plotly_chart(fig_sev_a, use_container_width=True)
            except ImportError:
                pass

        st.divider()

        alerts_list = unified.get("alerts", [])
        if alerts_list:
            st.markdown('<span class="section-header">Active Alerts</span>', unsafe_allow_html=True)
            for alert in alerts_list:
                sev = alert.get("severity", "info")
                source = alert.get("source", "?")
                source_icon = {
                    "health_rule": "🏥", "anomaly": "⚡", "incident": "🔴",
                }.get(source, "❓")
                sev_icon = "🔴" if sev in ("critical", "high") else ("🟡" if sev == "warning" else "🟢")

                with st.expander(
                    f"{sev_icon} {source_icon} [{source.upper()}] {alert.get('title', '?')} — "
                    f"{alert.get('namespace', '?')}/{alert.get('service', '?')}"
                ):
                    ac1, ac2, ac3, ac4 = st.columns(4)
                    ac1.markdown(f"**Severity:** {severity_badge(sev)}", unsafe_allow_html=True)
                    ac2.markdown(f"**Source:** `{source}`")
                    ac3.markdown(f"**Metric:** `{alert.get('metric', '?')}`")
                    ac4.markdown(f"**Status:** `{alert.get('status', '?')}`")
                    st.markdown(f"**Message:** {alert.get('message', '')}")
                    if alert.get("current_value"):
                        vc1, vc2 = st.columns(2)
                        vc1.metric("Current Value", f"{alert['current_value']:.4g}")
                        if alert.get("threshold"):
                            vc2.metric("Threshold", f"{alert['threshold']:.4g}")
                    st.caption(f"Time: {alert.get('timestamp', '')[:19]}")

            st.divider()
            st.markdown('<span class="section-header">📋 Alert Timeline</span>', unsafe_allow_html=True)
            try:
                import pandas as pd

                df_alerts = pd.DataFrame([
                    {
                        "Time": a.get("timestamp", "")[:19],
                        "Source": a.get("source", ""),
                        "Severity": a.get("severity", ""),
                        "Title": a.get("title", ""),
                        "Service": f"{a.get('namespace', '')}/{a.get('service', '')}",
                        "Status": a.get("status", ""),
                    }
                    for a in alerts_list
                ])
                st.dataframe(df_alerts, use_container_width=True, hide_index=True)
            except ImportError:
                pass
        else:
            empty_state("🎉", "No active alerts", "All systems are operating within normal parameters.")
    else:
        st.info("No alert data available. Ensure the API is running and services are reporting.")

# ===========================================================================
# PAGE: Cluster Scan
# ===========================================================================

if _page == "🔍 Cluster Scan":
    col1, col2 = st.columns([3, 1])
    with col1:
        scan_ns = namespace_selector(key="scan_ns", label="Namespace filter")

    if col2.button("🚀 Run Cluster Scan", type="primary", key="scan_main"):
        with st.spinner("Scanning cluster for incidents..."):
            params = f"?namespace={scan_ns}" if scan_ns else ""
            result = api_post(f"/api/v1/scan{params}")
        if result:
            st.success(
                f"✅ Scan complete: {result.get('total_detections', 0)} detections, "
                f"{result.get('incidents_created', 0)} incidents created"
            )
            if result.get("incident_ids"):
                st.markdown("**Created incidents:**")
                for iid in result["incident_ids"]:
                    st.code(iid)

    st.divider()
    st.markdown('<span class="section-header">Current Cluster Health</span>', unsafe_allow_html=True)
    summary = api_get("/api/v1/cluster/summary")
    if summary:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Health Score", f"{summary.get('health_score', 0):.0f}/100")
        c2.metric("Nodes Ready", f"{summary.get('ready_nodes', 0)}/{summary.get('total_nodes', 0)}")
        c3.metric(
            "Deployments Available",
            f"{summary.get('available_deployments', 0)}/{summary.get('total_deployments', 0)}",
        )
        c4.metric("PVCs Bound", f"{summary.get('bound_pvcs', 0)}/{summary.get('total_pvcs', 0)}")
        st.markdown(f"**Summary:** {summary.get('summary', '')}")
    else:
        empty_state("🔍", "Cluster summary unavailable", "Check your API connection and cluster access.")

# ===========================================================================
# PAGE: Incident History
# ===========================================================================

if _page == "📚 Incident History":
    stats = api_get("/api/v1/stats/accuracy")
    if stats:
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Total Analyzed", stats.get("total_analyzed", 0))
        sc2.metric("RCA Accuracy", f"{stats.get('correct_rca_pct', 0):.0f}%")
        sc3.metric("Fix Success Rate", f"{stats.get('fix_success_pct', 0):.0f}%")
        top_types = stats.get("top_failure_types", [])
        sc4.metric("Top Failure Type", top_types[0]["type"] if top_types else "—")

    st.divider()

    cluster_patterns = api_get("/api/v1/cluster/patterns?cluster_name=default&limit=5")
    if cluster_patterns:
        st.markdown('<span class="section-header">Recurring Failure Patterns</span>', unsafe_allow_html=True)
        try:
            import pandas as pd
            import plotly.express as px

            df_cp = pd.DataFrame(cluster_patterns)
            if not df_cp.empty:
                fig = px.bar(
                    df_cp,
                    x="incident_type",
                    y="count",
                    title="Top 5 Failure Types",
                    color="count",
                    color_continuous_scale=["#6366F1", "#EF4444"],
                )
                fig.update_layout(**_chart(height=260, showlegend=False))
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            for cp in cluster_patterns:
                st.markdown(
                    f"- **{cp.get('incident_type', '?')}**: {cp.get('count', 0)} occurrences"
                )

    st.divider()
    st.markdown('<span class="section-header">All Incidents</span>', unsafe_allow_html=True)
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
        st.dataframe(df, use_container_width=True, hide_index=True)

        _resolved = sum(1 for i in history if i.get("status") in ("resolved", "closed"))
        st.caption(
            f"**{len(history)} total**  ·  **{_resolved} resolved** ({_resolved / len(history):.0%})"
        )
    else:
        empty_state("📚", "No incident history", "Run a cluster scan to generate incidents.")

# ===========================================================================
# PAGE: Knowledge Base
# ===========================================================================

if _page == "📖 Knowledge Base":
    kb_patterns = api_get("/api/v1/knowledge/failures")
    stats = api_get("/api/v1/stats/accuracy")
    kb_count = len(kb_patterns) if kb_patterns else 0

    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.metric("Total Patterns", kb_count)
    if stats:
        kc2.metric("Incidents Analyzed", stats.get("total_analyzed", 0))
        kc3.metric("RCA Accuracy", f"{stats.get('correct_rca_pct', 0):.0f}%")
        kc4.metric("Fix Success Rate", f"{stats.get('fix_success_pct', 0):.0f}%")

    st.divider()

    col_search, col_tag = st.columns([3, 1])
    kb_query = col_search.text_input(
        "Search knowledge base", placeholder="e.g. secret not found crashloop"
    )

    all_tags: List[str] = []
    if kb_patterns:
        tag_set: set = set()
        for p in kb_patterns:
            for t in p.get("tags", []):
                if isinstance(t, str):
                    tag_set.add(t)
        all_tags = sorted(tag_set)

    tag_filter = col_tag.selectbox("Filter by tag", ["All"] + all_tags, key="kb_tag_filter")

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
        st.caption(f"Showing {len(display_patterns)} pattern(s)")
        for p in display_patterns:
            safety = p.get("safety_level", "suggest_only")
            score = p.get("score")
            score_str = f" — score={score:.2f}" if score is not None else ""
            tags = p.get("tags", [])
            tag_str = " ".join(f"`{t}`" for t in tags if isinstance(t, str))

            with st.expander(f"[{p.get('id', '?')}] {p.get('title', '')}{score_str}"):
                col_a, col_b = st.columns([3, 1])
                col_a.markdown(f"**Root cause:** {p.get('root_cause', '')}")
                col_b.markdown(f"**Safety:** {safety_badge(safety)}", unsafe_allow_html=True)

                steps = p.get("remediation_steps", [])
                if steps:
                    st.markdown("**Remediation steps:**")
                    for i, step in enumerate(steps, 1):
                        st.markdown(f"{i}. {step}")

                if tag_str:
                    st.markdown(f"**Tags:** {tag_str}")
    else:
        empty_state("📖", "No patterns found", "Try a different search query or tag filter.")

# ===========================================================================
# PAGE: Learning & Feedback
# ===========================================================================

if _page == "🧪 Learning & Feedback":
    learning_stats = api_get("/api/v1/stats/learning")
    accuracy_stats = api_get("/api/v1/stats/accuracy")

    if learning_stats:
        st.markdown('<span class="section-header">Learning System Status</span>', unsafe_allow_html=True)
        lc1, lc2, lc3, lc4, lc5 = st.columns(5)
        lc1.metric("Learned Patterns", learning_stats.get("total_learned_patterns", 0))
        lc2.metric("Promoted", learning_stats.get("promoted_patterns", 0))
        lc3.metric("Captured Errors", learning_stats.get("captured_error_patterns", 0))
        lc4.metric("Feedback Events", learning_stats.get("total_feedback_events", 0))
        lc5.metric("Successful Fixes", learning_stats.get("total_successful_fixes", 0))

        st.caption(
            f"Embedder refit: {learning_stats.get('incidents_since_last_refit', 0)}"
            f" / {learning_stats.get('refit_threshold', 5)} incidents until next refit"
        )

    if accuracy_stats:
        st.divider()
        st.markdown('<span class="section-header">Accuracy Over Time</span>', unsafe_allow_html=True)
        ac1, ac2, ac3 = st.columns(3)
        ac1.metric("Total Analyzed", accuracy_stats.get("total_analyzed", 0))
        ac2.metric("RCA Accuracy", f"{accuracy_stats.get('correct_rca_pct', 0):.0f}%")
        ac3.metric("Fix Success Rate", f"{accuracy_stats.get('fix_success_pct', 0):.0f}%")

        top_types = accuracy_stats.get("top_failure_types", [])
        if top_types:
            try:
                import pandas as pd
                import plotly.express as px

                df_types = pd.DataFrame(top_types)
                fig = px.bar(
                    df_types,
                    x="type",
                    y="count",
                    title="Most Frequent Incident Types",
                    color="count",
                    color_continuous_scale=["#6366F1", "#8B5CF6"],
                )
                fig.update_layout(**_chart(height=260, showlegend=False))
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                for t in top_types:
                    st.markdown(f"- **{t.get('type', '?')}**: {t.get('count', 0)}")

    st.divider()

    # Manual feedback submission
    st.markdown('<span class="section-header">📝 Submit Feedback for an Incident</span>', unsafe_allow_html=True)
    st.caption("Paste an incident ID to submit operator feedback. This directly improves future analysis.")

    fb_inc_id = st.text_input(
        "Incident ID",
        key="fb_loop_inc_id",
        placeholder="paste incident UUID from Live Incidents page",
    )

    if fb_inc_id:
        fb_inc = api_get(f"/api/v1/incidents/{fb_inc_id}")
        if fb_inc:
            st.markdown(
                f"**{fb_inc.get('title', '')}** — "
                f"{severity_badge(fb_inc.get('severity', '?'))} "
                f"`{fb_inc.get('incident_type', '?')}`",
                unsafe_allow_html=True,
            )
            if fb_inc.get("root_cause"):
                st.info(f"🎯 AI Root Cause: {fb_inc['root_cause']}")
            if fb_inc.get("suggested_fix"):
                st.success(f"💡 AI Suggested Fix: {fb_inc['suggested_fix']}")

            st.divider()

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
                placeholder="e.g. The actual fix was: kubectl create secret generic db-creds ...",
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
                    ls = result.get("learning_stats", {})
                    st.json(ls)
                    if payload["correct_root_cause"] and payload["fix_worked"]:
                        st.balloons()
        else:
            st.warning(f"Incident `{fb_inc_id}` not found. Check the ID and try again.")

    st.divider()

    with st.expander("ℹ️ How does the learning loop work?"):
        st.markdown("""
**The system improves through 5 mechanisms:**

1. **Unknown Error Capture** — When a new incident arrives with log lines containing ERROR/FATAL/PANIC patterns not seen before, the system automatically creates a new knowledge base entry in `learned.yaml`.

2. **Embedder Refit** — Every 5 new incidents, the TF-IDF similarity engine is retrained on all stored incident texts, improving future similarity matching.

3. **Feedback Scoring** — When you mark a fix as successful (+1.0) or failed (-0.5), the score is stored on the incident. Future similarity searches boost incidents with positive feedback.

4. **Pattern Promotion** — When 2+ similar incidents in the same namespace are resolved successfully, the system promotes the root cause and fix into a permanent learned pattern.

5. **Confidence Adjustment** — The AI confidence score is adjusted based on historical feedback for the same incident type + namespace.
        """)

    st.divider()
    st.markdown('<span class="section-header">📚 Learned Patterns</span>', unsafe_allow_html=True)
    learned = api_get("/api/v1/knowledge/failures?tag=learned") or []
    promoted = api_get("/api/v1/knowledge/failures?tag=promoted") or []
    all_learned = learned + promoted

    if all_learned:
        for p in all_learned:
            icon = "🎓" if "promoted" in (p.get("id") or "") else "🔍"
            with st.expander(f"{icon} [{p.get('id', '?')}] {p.get('title', '')}"):
                st.markdown(f"**Root cause:** {p.get('root_cause', '')}")
                steps = p.get("remediation_steps", [])
                if steps:
                    st.markdown("**Remediation:**")
                    for i, s in enumerate(steps[:5], 1):
                        st.markdown(f"{i}. {s}")
                tags = p.get("tags", [])
                if tags:
                    st.markdown(" ".join(f"`{t}`" for t in tags))
    else:
        empty_state(
            "🎓",
            "No learned patterns yet",
            "Submit feedback on analyzed incidents to start building the learned knowledge base.",
        )

# ===========================================================================
# PAGE: Learning Insights
# ===========================================================================

if _page == "📈 Learning Insights":
    outcomes_data = api_get("/api/v1/learning/outcomes")
    if outcomes_data and outcomes_data.get("outcomes"):
        outcomes = outcomes_data["outcomes"]
        st.caption(f"{len(outcomes)} actions tracked")

        try:
            import pandas as pd
            import plotly.express as px

            df_out = pd.DataFrame([
                {
                    "Action": v.get("action", k),
                    "Success Rate": v.get("success_rate", 0.5),
                    "Total": v.get("total", 0),
                    "Successes": v.get("successes", 0),
                }
                for k, v in outcomes.items()
            ])
            if not df_out.empty:
                fig_out = px.bar(
                    df_out.sort_values("Success Rate", ascending=True),
                    x="Success Rate",
                    y="Action",
                    orientation="h",
                    title="Remediation Success Rate by Action",
                    color="Success Rate",
                    color_continuous_scale=["#EF4444", "#F59E0B", "#22C55E"],
                    range_color=[0, 1],
                    text="Total",
                )
                fig_out.add_vline(x=0.5, line_dash="dot", line_color="#64748B",
                                  annotation_text="50% neutral prior")
                fig_out.update_layout(**_chart(height=max(200, len(df_out) * 38), showlegend=False))
                st.plotly_chart(fig_out, use_container_width=True)
        except ImportError:
            for k, v in outcomes.items():
                st.markdown(
                    f"- **{k}**: {v.get('success_rate', 0.5):.0%} "
                    f"({v.get('successes', 0)}/{v.get('total', 0)} successes)"
                )
    else:
        empty_state("📊", "No outcome data yet", "Record remediation results via the API or feedback form.")

    st.divider()

    st.markdown('<span class="section-header">Ranked Remediations by Incident Type</span>', unsafe_allow_html=True)
    rank_type = st.text_input(
        "Incident type to rank", "CrashLoopBackOff", key="rank_incident_type"
    )
    if rank_type:
        ranking = api_get(f"/api/v1/learning/ranking?incident_type={rank_type}")
        if ranking and ranking.get("ranked_steps"):
            for i, step in enumerate(ranking["ranked_steps"], 1):
                score = step.get("score", 0.5)
                bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
                st.markdown(
                    f"{i}. `{step.get('action', '?')}` — "
                    f"score `{score:.2f}` `[{bar}]` ({step.get('safety_level', '?')})"
                )
        elif ranking:
            st.info(f"No history yet for `{rank_type}` — using neutral priors")
        else:
            st.warning("Ranking endpoint not reachable")

    st.divider()

    # Audit log
    st.markdown('<span class="section-header">🗂️ Audit Log — Recent Actions</span>', unsafe_allow_html=True)
    audit_data = api_get("/api/v1/audit/events?limit=50")
    if audit_data and audit_data.get("events"):
        events = audit_data["events"]
        astats = audit_data.get("stats", {})

        sa1, sa2, sa3 = st.columns(3)
        sa1.metric("Total Events", astats.get("total_events", 0))
        by_outcome = astats.get("by_outcome", {})
        sa2.metric("Approved", by_outcome.get("approved", 0))
        sa3.metric("Blocked", by_outcome.get("blocked", 0))

        try:
            import pandas as pd

            df_audit = pd.DataFrame([
                {
                    "Time": e.get("timestamp", "")[:19],
                    "Type": e.get("event_type", ""),
                    "Namespace": e.get("namespace", ""),
                    "Workload": e.get("workload", ""),
                    "Action": e.get("action", ""),
                    "Outcome": e.get("outcome", ""),
                    "Actor": e.get("actor", ""),
                    "Risk": f"{e.get('risk_score', 0):.2f}" if e.get("risk_score") else "—",
                }
                for e in events
            ])
            st.dataframe(df_audit, use_container_width=True, hide_index=True)
        except ImportError:
            for ev in events[-10:]:
                st.markdown(
                    f"- `{ev.get('timestamp','')[:19]}` **{ev.get('event_type','')}** "
                    f"{ev.get('namespace','')}/{ev.get('workload','')} — "
                    f"*{ev.get('outcome','')}*"
                )
    else:
        empty_state(
            "🗂️",
            "No audit events yet",
            "Events are recorded when remediations are approved, blocked, or auto-executed.",
        )

# ===========================================================================
# PAGE: Multi-Cluster
# ===========================================================================

if _page == "🌐 Multi-Cluster":
    fleet_data = api_get("/api/v1/fleet/health")
    if fleet_data:
        total = fleet_data.get("total_clusters", 0)
        if total == 0:
            empty_state(
                "🌐",
                "No clusters registered yet",
                "Register a cluster using the form below or via POST /api/v1/clusters.",
            )
        else:
            fc1, fc2, fc3, fc4, fc5 = st.columns(5)
            fc1.metric("Total Clusters", total)
            fc2.metric("Healthy 🟢", fleet_data.get("healthy", 0))
            fc3.metric("Degraded 🟡", fleet_data.get("degraded", 0))
            fc4.metric("Critical 🔴", fleet_data.get("critical", 0))
            fc5.metric("Avg Health", f"{fleet_data.get('average_health_score', 0):.0f}/100")

            st.divider()

            clusters = fleet_data.get("clusters", [])
            if clusters:
                try:
                    import pandas as pd
                    import plotly.express as px

                    df_cl = pd.DataFrame(clusters)
                    fig_cl = px.bar(
                        df_cl,
                        x="name",
                        y="score",
                        color="status",
                        title="Cluster Health Scores",
                        color_discrete_map={
                            "healthy": "#22C55E",
                            "degraded": "#F59E0B",
                            "critical": "#EF4444",
                            "unknown": "#64748B",
                        },
                        text="grade",
                    )
                    fig_cl.add_hline(y=75, line_dash="dot", line_color="#64748B",
                                     annotation_text="healthy threshold")
                    fig_cl.update_layout(**_chart(height=300))
                    st.plotly_chart(fig_cl, use_container_width=True)
                except ImportError:
                    pass

                for cluster in clusters:
                    score = cluster.get("score", 0)
                    status_icon = "🟢" if cluster.get("status") == "healthy" else (
                        "🟡" if cluster.get("status") == "degraded" else "🔴"
                    )
                    with st.expander(
                        f"{status_icon} [{cluster.get('grade', '?')}] "
                        f"{cluster.get('name', cluster.get('cluster_id', '?'))} — "
                        f"score {score:.0f}/100"
                    ):
                        cc1, cc2, cc3 = st.columns(3)
                        cc1.markdown(f"**Environment:** {cluster.get('environment', '?')}")
                        cc2.markdown(f"**Last seen:** {(cluster.get('last_seen') or 'never')[:19]}")
                        cc3.markdown(f"**Incidents:** {cluster.get('incident_count', '?')}")

    st.divider()

    with st.expander("➕ Register a New Cluster"):
        rc1, rc2 = st.columns(2)
        new_cluster_id = rc1.text_input("Cluster ID", placeholder="us-east-1-prod")
        new_cluster_name = rc2.text_input("Name", placeholder="US East Production")
        rc3, rc4 = st.columns(2)
        new_api_url = rc3.text_input("API URL", placeholder="https://sre-operator.us-east-1.internal:8000")
        new_env = rc4.selectbox("Environment", ["production", "staging", "development", "unknown"])
        rc5, rc6 = st.columns(2)
        new_provider = rc5.selectbox("Provider", ["aws", "gcp", "azure", "on-prem", "unknown"])
        new_region = rc6.text_input("Region", placeholder="us-east-1")

        if st.button("Register Cluster", type="primary"):
            payload = {
                "cluster_id": new_cluster_id,
                "name": new_cluster_name,
                "api_url": new_api_url,
                "provider": new_provider,
                "region": new_region,
                "environment": new_env,
                "tags": [],
            }
            result = api_post("/api/v1/clusters", payload)
            if result:
                st.success(f"Cluster `{new_cluster_id}` registered successfully!")
                st.rerun()
            else:
                st.error("Failed to register cluster — check API logs")
