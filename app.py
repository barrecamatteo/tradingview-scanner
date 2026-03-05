"""
TradingView Continuation Rate Scanner - Streamlit Web App
"""

import os
import sys
import time
import logging
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scanner import TradingViewScanner
from src.database.supabase_client import SupabaseDB
from src.config.assets import ASSETS, TIMEFRAMES, get_total_combinations

# All timeframe labels in display order
ALL_TF_LABELS = ["4H", "1H", "15min", "5min", "1min"]
WEEKLY_TF = ["4H", "1H", "15min"]
DAILY_TF = ["5min", "1min"]

# ── Page Config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="TV Continuation Rate Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem 1.5rem;
        border-radius: 10px;
        color: white;
        text-align: center;
    }

    /* Table styling */
    .dataframe td { text-align: center !important; }
    .dataframe th { text-align: center !important; background-color: #1f2937 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helper Functions ──────────────────────────────────────────────────

def get_db() -> SupabaseDB:
    """Get or create Supabase client from session state."""
    if "db" not in st.session_state:
        try:
            st.session_state.db = SupabaseDB()
        except ValueError as e:
            st.error(f"⚠️ Database not configured: {e}")
            st.info("Set SUPABASE_URL and SUPABASE_KEY in your environment or .env file.")
            return None
    return st.session_state.db


def format_rate(val):
    """Format rate value with percentage sign."""
    if pd.isna(val) or val is None:
        return "—"
    return f"{float(val):.1f}%"


def get_last_scan_date(db, timeframes):
    """Get the most recent scan date for a set of timeframes."""
    try:
        rates = db.client.table("continuation_rates").select(
            "updated_at"
        ).in_("timeframe", timeframes).order(
            "updated_at", desc=True
        ).limit(1).execute()

        if rates.data and rates.data[0].get("updated_at"):
            return rates.data[0]["updated_at"][:16].replace("T", " ")
    except Exception:
        pass
    return "Mai"


# ── Sidebar ───────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Configuration")

    st.markdown("### 🔑 Credentials")

    # Check for environment variables
    tv_user = os.getenv("TV_USERNAME", "")
    tv_pass = os.getenv("TV_PASSWORD", "")

    if not tv_user:
        tv_user = st.text_input("TradingView Username", type="default")
    if not tv_pass:
        tv_pass = st.text_input("TradingView Password", type="password")

    st.markdown("---")

    st.markdown("### 🔧 Scan Settings")

    extraction_method = st.selectbox(
        "Extraction Method",
        ["csv", "ocr", "ai_vision"],
        help="CSV downloads chart data (fastest, 100% accurate). "
             "OCR uses EasyOCR. AI Vision uses Claude API.",
    )

    headless_mode = st.checkbox("Headless Mode", value=True, help="Run browser without GUI")

    # Timeframe selection for manual scan
    st.markdown("### 📐 Timeframes")
    scan_tfs = st.multiselect(
        "Select timeframes to scan",
        ALL_TF_LABELS,
        default=ALL_TF_LABELS,
    )

    st.markdown("---")

    st.markdown("### 📋 Assets")
    total = get_total_combinations()
    st.metric("Total Combinations (all TF)", f"{total}")

    for cat, assets_list in ASSETS.items():
        with st.expander(f"{cat} ({len(assets_list)})"):
            for a in assets_list:
                st.text(f"  {a['name']}")

# ── Main Content ──────────────────────────────────────────────────────

st.markdown('<div class="main-header">📊 Continuation Rates</div>', unsafe_allow_html=True)

db = get_db()

# Top metrics: Assets, Timeframes, Weekly Update, Daily Update
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Assets", len([a for cat in ASSETS.values() for a in cat]))
with col2:
    st.metric("Timeframes", len(TIMEFRAMES))
with col3:
    weekly_date = get_last_scan_date(db, WEEKLY_TF) if db else "Mai"
    st.metric("Weekly Update", weekly_date)
with col4:
    daily_date = get_last_scan_date(db, DAILY_TF) if db else "Mai"
    st.metric("Daily Update", daily_date)

st.markdown("---")

# ── Scan Controls ─────────────────────────────────────────────────────

scan_col1, scan_col2 = st.columns([1, 3])

with scan_col1:
    scan_button = st.button("🔄 Aggiorna Dati", type="primary", use_container_width=True)

with scan_col2:
    last_scan = None
    if db:
        try:
            last_scan = db.get_last_scan()
        except Exception:
            pass
    if last_scan:
        status_icon = "✅" if last_scan["status"] == "completed" else "⚠️"
        st.info(
            f"{status_icon} Last scan: {last_scan.get('successful', 0)} successful, "
            f"{last_scan.get('failed', 0)} failed"
        )

# ── Run Scan ──────────────────────────────────────────────────────────

if scan_button:
    if not tv_user or not tv_pass:
        st.error("⚠️ Please provide TradingView credentials in the sidebar.")
    elif not scan_tfs:
        st.error("⚠️ Please select at least one timeframe.")
    else:
        os.environ["TV_USERNAME"] = tv_user
        os.environ["TV_PASSWORD"] = tv_pass

        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.expander("📋 Scan Log", expanded=True)

        def progress_callback(current, total, message):
            progress = current / total if total > 0 else 0
            progress_bar.progress(progress)
            status_text.text(f"[{current}/{total}] {message}")
            with log_container:
                st.text(f"{datetime.now().strftime('%H:%M:%S')} | {message}")

        try:
            scanner = TradingViewScanner(
                headless=headless_mode,
                extraction_method=extraction_method,
                use_database=db is not None,
                timeframe_filter=scan_tfs,
            )
            scanner.set_progress_callback(progress_callback)

            with st.spinner("🔄 Scanning in progress..."):
                results = scanner.run_full_scan()

            st.success(
                f"✅ Scan complete! "
                f"{len([r for r in results if r.status == 'success'])} "
                f"successful extractions."
            )

            st.session_state.scan_results = scanner.get_results_as_pivot()
            st.rerun()

        except Exception as e:
            st.error(f"❌ Scan failed: {str(e)}")
            logger.exception("Scan failed")

# ── Results Table ─────────────────────────────────────────────────────

st.markdown("## 📊 Continuation Rates")

data = None

if db:
    try:
        data = db.get_rates_pivot()
    except Exception as e:
        logger.warning(f"Could not load from database: {e}")

if not data and "scan_results" in st.session_state:
    data = st.session_state.scan_results

if data:
    df = pd.DataFrame(data)

    # ── Filters ───────────────────────────────────────────────────
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        categories = ["Tutti"] + sorted(df["category"].unique().tolist())
        selected_cat = st.selectbox("Filtra per Categoria", categories)

    with filter_col2:
        sort_options = ["Categoria", "Asset"] + ALL_TF_LABELS + ["Avg (desc)", "Avg (asc)"]
        sort_by = st.selectbox("Ordina per", sort_options)

    # Apply filters
    if selected_cat != "Tutti":
        df = df[df["category"] == selected_cat]

    # Apply sorting
    sort_map = {
        "Categoria": ("category", True),
        "Asset": ("asset", True),
        "Avg (desc)": ("avg", False),
        "Avg (asc)": ("avg", True),
    }
    for tf in ALL_TF_LABELS:
        sort_map[tf] = (tf, False)

    sort_col, sort_asc = sort_map.get(sort_by, ("category", True))
    if sort_col in df.columns:
        df = df.sort_values(sort_col, ascending=sort_asc, na_position="last")

    # ── Display Table ─────────────────────────────────────────────

    display_df = df.copy()

    # Select and order columns: Asset, Category, 4H, 1H, 15min, 5min, 1min
    display_columns = ["asset", "category"] + ALL_TF_LABELS
    available_cols = [c for c in display_columns if c in display_df.columns]
    display_df = display_df[available_cols]

    # Rename
    display_df.rename(columns={
        "category": "Categoria",
        "asset": "Asset",
    }, inplace=True)

    # Format ALL percentage columns (including 5min and 1min)
    for col in ALL_TF_LABELS:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(format_rate)

    # Column config
    col_config = {
        "Categoria": st.column_config.TextColumn(width="medium"),
        "Asset": st.column_config.TextColumn(width="small"),
    }
    for tf in ALL_TF_LABELS:
        if tf in display_df.columns:
            col_config[tf] = st.column_config.TextColumn(width="small")

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
    )

    # ── Summary Stats ─────────────────────────────────────────────
    st.markdown("### 📈 Summary Statistics")

    stat_cols = st.columns(len(ALL_TF_LABELS))
    for i, tf in enumerate(ALL_TF_LABELS):
        with stat_cols[i]:
            if tf in df.columns:
                avg_val = df[tf].dropna().mean()
                st.metric(
                    f"Avg {tf}",
                    f"{avg_val:.1f}%" if pd.notna(avg_val) else "—"
                )
            else:
                st.metric(f"Avg {tf}", "—")

    # ── Top Continuation Rate (>= 67%) per timeframe ──────────────
    st.markdown("### 🏆 Top Continuation Rate (≥ 67%)")

    for tf in ALL_TF_LABELS:
        if tf in df.columns:
            top_df = df[df[tf].notna() & (df[tf] >= 67)][["asset", "category", tf]].copy()
            if not top_df.empty:
                top_df = top_df.sort_values(tf, ascending=False)
                top_df[tf] = top_df[tf].apply(lambda x: f"{x:.1f}%")
                top_df.rename(columns={
                    "asset": "Asset",
                    "category": "Categoria",
                    tf: "Cont. Rate"
                }, inplace=True)
                st.markdown(f"**{tf}**")
                st.dataframe(top_df, hide_index=True, use_container_width=True)
            else:
                st.markdown(f"**{tf}** — Nessun asset ≥ 67%")

    # ── Export ────────────────────────────────────────────────────
    st.markdown("---")
    csv = df.to_csv(index=False)
    st.download_button(
        "📥 Download CSV",
        data=csv,
        file_name=f"continuation_rates_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )

else:
    st.info(
        "📭 No data yet. Click **🔄 Aggiorna Dati** to run your first scan, "
        "or configure the database to load saved results."
    )

# ── History Chart (if database connected) ─────────────────────────────

if db:
    try:
        st.markdown("---")
        st.markdown("## 📉 Historical Trends")

        hist_col1, hist_col2 = st.columns(2)

        with hist_col1:
            all_assets = sorted(
                set(a["name"] for cat in ASSETS.values() for a in cat)
            )
            hist_asset = st.selectbox("Select Asset", all_assets, key="hist_asset")

        with hist_col2:
            hist_tf = st.selectbox(
                "Select Timeframe", ALL_TF_LABELS, key="hist_tf"
            )

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
            st.info("No historical data available yet for this asset/timeframe.")
    except Exception:
        pass

# ── Footer ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #6c757d; font-size: 0.8rem;'>"
    "TradingView Continuation Rate Scanner | SMC Market Structure Analysis | "
    "CSV Extraction v3.0"
    "</div>",
    unsafe_allow_html=True,
)
