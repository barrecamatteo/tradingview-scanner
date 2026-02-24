"""
TradingView Continuation Rate Scanner - Streamlit Web App
"""

import os
import sys
import time
import logging
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

# Load Streamlit Cloud secrets into environment variables
try:
    for key in ["SUPABASE_URL", "SUPABASE_KEY", "GITHUB_TOKEN"]:
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = st.secrets[key]
except Exception:
    pass

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.supabase_client import SupabaseDB
from src.config.assets import ASSETS, TIMEFRAMES, get_total_combinations

# ── Page Config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TV Continuation Rate Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── GitHub Actions Config ─────────────────────────────────────────────────
GITHUB_REPO = "barrecamatteo/tradingview-scanner"
GITHUB_WORKFLOW = "scheduled_scan.yml"

# ── Custom CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .dataframe td { text-align: center !important; }
    .dataframe th { text-align: center !important; background-color: #1f2937 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helper Functions ──────────────────────────────────────────────────────

def get_db() -> SupabaseDB:
    """Get or create Supabase client from session state."""
    if "db" not in st.session_state:
        try:
            st.session_state.db = SupabaseDB()
        except ValueError as e:
            st.error(f"⚠️ Database non configurato: {e}")
            st.info("Configura SUPABASE_URL e SUPABASE_KEY nei Secrets di Streamlit.")
            return None
    return st.session_state.db


def format_rate(val):
    """Format rate value with percentage sign."""
    if pd.isna(val) or val is None:
        return "—"
    return f"{float(val):.1f}%"


def trigger_github_scan() -> bool:
    """Trigger the GitHub Actions workflow via API."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        st.error("⚠️ GITHUB_TOKEN non configurato nei Secrets.")
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"ref": "main"}

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 204:
            return True
        else:
            st.error(f"Errore GitHub API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        st.error(f"Errore connessione GitHub: {e}")
        return False


def get_workflow_status() -> dict:
    """Get the latest GitHub Actions workflow run status."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        response = requests.get(url, headers=headers, params={"per_page": 1})
        if response.status_code == 200:
            runs = response.json().get("workflow_runs", [])
            if runs:
                run = runs[0]
                return {
                    "status": run["status"],
                    "conclusion": run.get("conclusion"),
                    "created_at": run["created_at"],
                    "url": run["html_url"],
                }
        return None
    except Exception:
        return None


# ── Main Content ──────────────────────────────────────────────────────────

st.markdown('<div class="main-header">📊 TradingView Continuation Rate Scanner</div>', unsafe_allow_html=True)
st.markdown("Scansione automatica dei Continuation Rate SMC su 25 asset × 3 timeframe")

# Top metrics row
col1, col2, col3, col4 = st.columns(4)

db = get_db()
last_scan = None
if db:
    try:
        last_scan = db.get_last_scan()
    except Exception:
        pass

with col1:
    st.metric("Asset", len([a for cat in ASSETS.values() for a in cat]))
with col2:
    st.metric("Timeframe", len(TIMEFRAMES))
with col3:
    st.metric("Combinazioni", get_total_combinations())
with col4:
    if last_scan and last_scan.get("completed_at"):
        ts = last_scan["completed_at"][:16].replace("T", " ")
        st.metric("Ultimo Aggiornamento", ts)
    else:
        st.metric("Ultimo Aggiornamento", "Mai")

st.markdown("---")

# ── Scan Controls ─────────────────────────────────────────────────────────

scan_col1, scan_col2, scan_col3 = st.columns([1, 1, 2])

with scan_col1:
    if st.button("🚀 Avvia Scansione", type="primary", use_container_width=True):
        if trigger_github_scan():
            st.success("✅ Scansione avviata! Ci vorranno circa 45-60 minuti. I dati si aggiorneranno automaticamente su questa pagina.")
        else:
            st.error("❌ Impossibile avviare la scansione.")

with scan_col2:
    if st.button("🔄 Aggiorna Pagina", use_container_width=True):
        st.rerun()

with scan_col3:
    # Show last scan status
    if last_scan:
        status_icon = "✅" if last_scan["status"] == "completed" else "⏳" if last_scan["status"] == "running" else "⚠️"
        st.info(
            f"{status_icon} Ultima scansione: {last_scan.get('successful', 0)} riuscite, "
            f"{last_scan.get('failed', 0)} fallite"
        )

    # Show GitHub Actions status
    workflow = get_workflow_status()
    if workflow:
        if workflow["status"] == "in_progress":
            st.warning("⏳ Scansione GitHub in corso...")
        elif workflow["status"] == "completed":
            icon = "✅" if workflow["conclusion"] == "success" else "❌"
            st.caption(f"{icon} Ultimo workflow: {workflow['created_at'][:16].replace('T', ' ')}")

# ── Results Table ─────────────────────────────────────────────────────────

st.markdown("## 📊 Continuation Rates")

data = None
if db:
    try:
        data = db.get_rates_pivot()
    except Exception as e:
        logger.warning(f"Errore caricamento dati: {e}")

if data:
    df = pd.DataFrame(data)

    # ── Filters ───────────────────────────────────────────────────────
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        categories = ["Tutti"] + sorted(df["category"].unique().tolist())
        selected_cat = st.selectbox("Filtra per Categoria", categories)

    with filter_col2:
        min_rate = st.slider("Media Minima (%)", 0.0, 100.0, 0.0, 0.5)

    with filter_col3:
        sort_by = st.selectbox(
            "Ordina per",
            ["Categoria", "Asset", "4H", "1H", "15min", "Media (desc)", "Media (asc)"],
        )

    # Apply filters
    if selected_cat != "Tutti":
        df = df[df["category"] == selected_cat]

    if min_rate > 0:
        df = df[df["avg"].fillna(0) >= min_rate]

    # Apply sorting
    sort_map = {
        "Categoria": ("category", True),
        "Asset": ("asset", True),
        "4H": ("4H", False),
        "1H": ("1H", False),
        "15min": ("15min", False),
        "Media (desc)": ("avg", False),
        "Media (asc)": ("avg", True),
    }
    sort_col, sort_asc = sort_map.get(sort_by, ("category", True))
    df = df.sort_values(sort_col, ascending=sort_asc, na_position="last")

    # ── Display Table ─────────────────────────────────────────────────

    display_df = df.copy()
    display_df.rename(columns={
        "category": "Categoria",
        "asset": "Asset",
        "4H": "4H",
        "1H": "1H",
        "15min": "15min",
        "avg": "Media",
        "updated_at": "Ultimo Aggiornamento",
    }, inplace=True)

    # Format percentage columns
    rate_cols = ["4H", "1H", "15min", "Media"]
    for col in rate_cols:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(format_rate)

    # Format timestamp
    if "Ultimo Aggiornamento" in display_df.columns:
        display_df["Ultimo Aggiornamento"] = display_df["Ultimo Aggiornamento"].apply(
            lambda x: str(x)[:16].replace("T", " ") if x else "—"
        )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Categoria": st.column_config.TextColumn(width="medium"),
            "Asset": st.column_config.TextColumn(width="small"),
            "4H": st.column_config.TextColumn(width="small"),
            "1H": st.column_config.TextColumn(width="small"),
            "15min": st.column_config.TextColumn(width="small"),
            "Media": st.column_config.TextColumn(width="small"),
            "Ultimo Aggiornamento": st.column_config.TextColumn(width="medium"),
        },
    )

    # ── Summary Stats ─────────────────────────────────────────────────
    st.markdown("### 📈 Statistiche Riassuntive")

    stats_col1, stats_col2, stats_col3 = st.columns(3)

    with stats_col1:
        avg_4h = df["4H"].dropna().mean()
        st.metric("Media 4H", f"{avg_4h:.1f}%" if pd.notna(avg_4h) else "—")

    with stats_col2:
        avg_1h = df["1H"].dropna().mean()
        st.metric("Media 1H", f"{avg_1h:.1f}%" if pd.notna(avg_1h) else "—")

    with stats_col3:
        avg_15 = df["15min"].dropna().mean()
        st.metric("Media 15min", f"{avg_15:.1f}%" if pd.notna(avg_15) else "—")

    # ── Top/Bottom performers ─────────────────────────────────────────
    if "avg" in df.columns and df["avg"].notna().any():
        perf_col1, perf_col2 = st.columns(2)

        with perf_col1:
            st.markdown("#### 🏆 Top 5 (per Media)")
            top5 = df.nlargest(5, "avg")[["asset", "category", "avg"]]
            top5["avg"] = top5["avg"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(top5, hide_index=True, use_container_width=True)

        with perf_col2:
            st.markdown("#### ⚠️ Bottom 5 (per Media)")
            bottom5 = df.nsmallest(5, "avg")[["asset", "category", "avg"]]
            bottom5["avg"] = bottom5["avg"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(bottom5, hide_index=True, use_container_width=True)

    # ── Export ────────────────────────────────────────────────────────
    st.markdown("---")
    csv = df.to_csv(index=False)
    st.download_button(
        "📥 Scarica CSV",
        data=csv,
        file_name=f"continuation_rates_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )

else:
    st.info(
        "📭 Nessun dato disponibile. Clicca **🚀 Avvia Scansione** per lanciare "
        "la prima raccolta dati."
    )

# ── History Chart ─────────────────────────────────────────────────────────

if db:
    try:
        st.markdown("---")
        st.markdown("## 📉 Storico Variazioni")

        hist_col1, hist_col2 = st.columns(2)

        with hist_col1:
            all_assets = sorted(
                set(a["name"] for cat in ASSETS.values() for a in cat)
            )
            hist_asset = st.selectbox("Seleziona Asset", all_assets, key="hist_asset")

        with hist_col2:
            hist_tf = st.selectbox("Seleziona Timeframe", list(TIMEFRAMES.keys()), key="hist_tf")

        history = db.get_history(asset=hist_asset, timeframe=hist_tf, limit=50)

        if history:
            hist_df = pd.DataFrame(history)
            hist_df["scanned_at"] = pd.to_datetime(hist_df["scanned_at"])
            hist_df = hist_df.sort_values("scanned_at")

            st.line_chart(
                hist_df.set_index("scanned_at")["cont_rate"],
                use_container_width=True,
            )
        else:
            st.info("Nessun dato storico disponibile per questo asset/timeframe.")
    except Exception:
        pass

# ── Sidebar (info) ────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ℹ️ Info")

    st.markdown("### 📋 Asset Monitorati")
    for cat, assets_list in ASSETS.items():
        with st.expander(f"{cat} ({len(assets_list)})"):
            for a in assets_list:
                st.text(f"  {a['name']}")

    st.markdown("---")
    st.markdown(
        "**Come funziona:** Clicca 🚀 Avvia Scansione per lanciare "
        "la raccolta dati su GitHub Actions. I risultati appariranno "
        "qui dopo circa 45-60 minuti."
    )

# ── Footer ────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #6c757d; font-size: 0.8rem;'>"
    "TradingView Continuation Rate Scanner | SMC Market Structure Analysis"
    "</div>",
    unsafe_allow_html=True,
)
