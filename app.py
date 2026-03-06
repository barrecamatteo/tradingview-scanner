"""
TradingView Continuation Rate Scanner - Streamlit Web App
"""

import os
import sys
import hashlib
import logging
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    initial_sidebar_state="collapsed",
)

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# AUTH SYSTEM
# ══════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash a password with SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def get_db() -> SupabaseDB:
    """Get or create Supabase client from session state."""
    if "db" not in st.session_state:
        try:
            st.session_state.db = SupabaseDB()
        except ValueError as e:
            st.error(f"⚠️ Database not configured: {e}")
            return None
    return st.session_state.db


def check_login(username: str, password: str) -> bool:
    """Verify username and password against database."""
    db = get_db()
    if not db:
        return False
    try:
        result = db.client.table("users").select("password_hash").eq(
            "username", username
        ).execute()
        if result.data:
            stored_hash = result.data[0]["password_hash"]
            return stored_hash == hash_password(password)
        return False
    except Exception as e:
        logger.error(f"Login check failed: {e}")
        return False


def register_user(username: str, password: str) -> bool:
    """Register a new user in the database."""
    db = get_db()
    if not db:
        return False
    try:
        db.client.table("users").insert({
            "username": username,
            "password_hash": hash_password(password),
        }).execute()
        return True
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        return False


def show_login_page():
    """Display the login/registration page."""
    st.markdown("""
    <style>
        .login-container {
            max-width: 400px;
            margin: 0 auto;
            padding-top: 5rem;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("## 📊 Continuation Rate Scanner")
        st.markdown("*SMC Market Structure Analysis*")
        st.markdown("---")

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Accedi", use_container_width=True)

            if submit:
                if not username or not password:
                    st.error("Inserisci username e password")
                elif check_login(username, password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.rerun()
                else:
                    st.error("Username o password errati")


# ── Check Auth ────────────────────────────────────────────────────────

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    show_login_page()
    st.stop()


# ══════════════════════════════════════════════════════════════════════
# MAIN APP (only shown after login)
# ══════════════════════════════════════════════════════════════════════

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }

    /* Table styling */
    .dataframe td { text-align: center !important; }
    .dataframe th { text-align: center !important; background-color: #1f2937 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helper Functions ──────────────────────────────────────────────────

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


# ── Header with logout ────────────────────────────────────────────────

header_col1, header_col2 = st.columns([6, 1])
with header_col1:
    st.markdown('<div class="main-header">📊 Continuation Rates</div>', unsafe_allow_html=True)
with header_col2:
    if st.button("Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.pop("username", None)
        st.rerun()

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

# ── Results Table ─────────────────────────────────────────────────────

data = None

if db:
    try:
        data = db.get_rates_pivot()
    except Exception as e:
        logger.warning(f"Could not load from database: {e}")

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

    # Format ALL percentage columns
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

    # ── Trading session info per asset (for 5min/1min tables) ────────
    TRADING_SESSIONS = {
        # Major Forex
        "EURUSD": ("14:00 - 18:00", "Overlap EU/US: massima liquidità. Segue i dati macro USA."),
        "GBPUSD": ("14:00 - 18:00", "Overlap EU/US: massima liquidità. Segue i dati macro USA."),
        "USDCHF": ("14:00 - 18:00", "Overlap EU/US: massima liquidità. Segue i dati macro USA."),
        # Cross Europei
        "EURGBP": ("09:00 - 12:00", "Sessione Londra: movimenti tecnici e puliti. Spesso laterale nel pomeriggio."),
        "EURCHF": ("09:00 - 12:00", "Sessione Londra: movimenti tecnici e puliti. Spesso laterale nel pomeriggio."),
        "GBPCHF": ("09:00 - 12:00", "Sessione Londra: movimenti tecnici e puliti. Spesso laterale nel pomeriggio."),
        "CADCHF": ("09:00 - 12:00", "Sessione Londra: movimenti tecnici e puliti. Spesso laterale nel pomeriggio."),
        # Yen Crosses
        "USDJPY": ("09:00-11:00 / 15:30-18:00", "Mattina segue flussi EU. Pomeriggio reagisce a Risk-On/Off azionario."),
        "GBPJPY": ("09:00-11:00 / 15:30-18:00", "Mattina segue flussi EU. Pomeriggio reagisce a Risk-On/Off azionario."),
        "EURJPY": ("09:00-11:00 / 15:30-18:00", "Mattina segue flussi EU. Pomeriggio reagisce a Risk-On/Off azionario."),
        "AUDJPY": ("09:00-11:00 / 15:30-18:00", "Mattina segue flussi EU. Pomeriggio reagisce a Risk-On/Off azionario."),
        "CADJPY": ("09:00-11:00 / 15:30-18:00", "Mattina segue flussi EU. Pomeriggio reagisce a Risk-On/Off azionario."),
        # Commodity FX
        "AUDUSD": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        "AUDCAD": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        "AUDCHF": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        "GBPAUD": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        "EURAUD": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        "EURCAD": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        "GBPCAD": ("09:00 - 10:30", "London Fade: spesso inverte il movimento fatto in Asia."),
        # Metalli
        "XAUUSD": ("14:30 - 18:30", "Reagisce al Dollaro e inflazione USA. Molto nervoso."),
        "XAGUSD": ("14:30 - 18:30", "Reagisce al Dollaro e inflazione USA. Molto nervoso."),
        "XPTUSD": ("14:30 - 18:30", "Reagisce al Dollaro e inflazione USA. Molto nervoso."),
        # Indici
        "SPX500": ("15:30 - 22:00", "Apertura Wall Street. Evitare la mattina. Alta volatilità."),
        "NAS100": ("15:30 - 22:00", "Apertura Wall Street. Evitare la mattina. Alta volatilità."),
        # Crypto
        "ETHUSD": ("15:30 - 20:00", "Correlato al NAS100. Se il Nasdaq sale, ETH tende a seguirlo."),
    }

    # ── Top Continuation Rate (>= 67%) per timeframe ──────────────
    st.markdown("### 🏆 Top Continuation Rate (≥ 67%)")

    # Timeframe colors matching TradingView watchlist
    TF_COLORS = {
        "4H": "#9C27B0",     # Viola
        "1H": "#FFC107",     # Giallo
        "15min": "#4CAF50",  # Verde
        "5min": "#2196F3",   # Blu
        "1min": "#F44336",   # Rosso
    }

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

                # Add trading session columns for 5min and 1min only
                if tf in ("5min", "1min"):
                    top_df["Orario Migliore"] = top_df["Asset"].map(
                        lambda x: TRADING_SESSIONS.get(x, ("—", "—"))[0]
                    )
                    top_df["Note"] = top_df["Asset"].map(
                        lambda x: TRADING_SESSIONS.get(x, ("—", "—"))[1]
                    )

                # Colored timeframe title
                color = TF_COLORS.get(tf, "#FFFFFF")
                st.markdown(
                    f'<span style="color:{color}; font-size:1.3rem; font-weight:700;">● {tf}</span>',
                    unsafe_allow_html=True,
                )

                if tf in ("5min", "1min"):
                    st.dataframe(
                        top_df,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Asset": st.column_config.TextColumn(width="small"),
                            "Categoria": st.column_config.TextColumn(width="medium"),
                            "Cont. Rate": st.column_config.TextColumn(width="small"),
                            "Orario Migliore": st.column_config.TextColumn(width="medium"),
                            "Note": st.column_config.TextColumn(width="large"),
                        },
                    )
                else:
                    st.dataframe(
                        top_df,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Asset": st.column_config.TextColumn(width="large"),
                            "Categoria": st.column_config.TextColumn(width="large"),
                            "Cont. Rate": st.column_config.TextColumn(width="large"),
                        },
                    )
            else:
                color = TF_COLORS.get(tf, "#FFFFFF")
                st.markdown(
                    f'<span style="color:{color}; font-size:1.3rem; font-weight:700;">● {tf}</span>'
                    f' — Nessun asset ≥ 67%',
                    unsafe_allow_html=True,
                )

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
        "📭 Nessun dato. Le scansioni automatiche popoleranno questa pagina."
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
