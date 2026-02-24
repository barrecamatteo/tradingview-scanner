# 📊 TradingView Continuation Rate Scanner

Automated extraction of **SMC Continuation Rate** values from TradingView charts across 25 assets × 3 timeframes, with database storage and a web dashboard.

## Architecture

```
┌─────────────────────────────────┐
│   Streamlit Web App (app.py)    │  ← Dashboard + controls
├─────────────────────────────────┤
│   Scanner Orchestrator          │  ← Coordinates the pipeline
├──────────┬──────────┬───────────┤
│ Selenium │ OCR/AI   │ Supabase  │  ← Browser, extraction, storage
│ Browser  │ Vision   │ Database  │
└──────────┴──────────┴───────────┘
```

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USER/tradingview-scanner.git
cd tradingview-scanner
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Create Database

Go to [Supabase](https://supabase.com), create a project, then open the **SQL Editor** and run:

```sql
-- Current continuation rates (latest values)
CREATE TABLE IF NOT EXISTS continuation_rates (
    id BIGSERIAL PRIMARY KEY,
    asset VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    cont_rate DECIMAL(5,2),
    confidence DECIMAL(3,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(asset, timeframe)
);

-- Historical data
CREATE TABLE IF NOT EXISTS continuation_rates_history (
    id BIGSERIAL PRIMARY KEY,
    asset VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    cont_rate DECIMAL(5,2),
    confidence DECIMAL(3,2) DEFAULT 0,
    scan_batch_id UUID,
    scanned_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scan log
CREATE TABLE IF NOT EXISTS scan_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    total_assets INT DEFAULT 0,
    successful INT DEFAULT 0,
    failed INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running',
    error_message TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_rates_asset_tf ON continuation_rates(asset, timeframe);
CREATE INDEX IF NOT EXISTS idx_history_asset_tf ON continuation_rates_history(asset, timeframe);
CREATE INDEX IF NOT EXISTS idx_history_scanned_at ON continuation_rates_history(scanned_at);
```

Copy your **Project URL** and **anon key** from Supabase > Settings > API into `.env`.

### 4. First Run (Non-Headless)

For the first login, run without headless mode to handle any 2FA or captchas:

```bash
python -c "
from src.scraper.browser import TradingViewBrowser
browser = TradingViewBrowser(headless=False)
browser.login()
input('Press Enter after login is confirmed...')
browser.close()
"
```

This saves session cookies so subsequent headless runs don't need manual login.

### 5. Launch Dashboard

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## Usage

### Web Dashboard (Streamlit)

1. Open the app in your browser
2. Configure credentials in the sidebar (or use `.env`)
3. Click **🔄 Aggiorna Dati** to start scanning
4. Watch the progress bar as it cycles through all 75 combinations
5. View results in the filterable/sortable table
6. Download CSV export

### CLI / Automation

```bash
# One-off scan
python run_scan.py

# With custom extraction method
EXTRACTION_METHOD=ai_vision python run_scan.py
```

### GitHub Actions (Scheduled)

1. Add secrets to your GitHub repo: `TV_USERNAME`, `TV_PASSWORD`, `SUPABASE_URL`, `SUPABASE_KEY`
2. The workflow runs every Monday at 06:00 UTC
3. Trigger manually from Actions tab > "Scheduled TradingView Scan" > "Run workflow"

## Extraction Methods

### OCR (Default)
Uses **EasyOCR** to read the "Cont. Rate" value from screenshots. Free, runs locally, ~80-90% accuracy.

### AI Vision
Uses the **Claude API** to analyze screenshots with computer vision. More accurate (~95%+), costs API credits (~$0.01/image).

Set via `EXTRACTION_METHOD=ai_vision` in `.env` or the sidebar dropdown.

## Project Structure

```
tradingview-scanner/
├── app.py                    # Streamlit web dashboard
├── run_scan.py               # CLI runner for cron/CI
├── requirements.txt
├── .env.example
├── .gitignore
├── .github/workflows/
│   └── scheduled_scan.yml    # GitHub Actions automation
├── .streamlit/
│   └── secrets.toml.example
└── src/
    ├── scanner.py            # Main orchestrator
    ├── config/
    │   └── assets.py         # Asset list & settings
    ├── scraper/
    │   ├── browser.py        # Selenium + TradingView auth
    │   ├── navigator.py      # Chart navigation
    │   └── extractor.py      # OCR / AI Vision extraction
    └── database/
        └── supabase_client.py  # Supabase CRUD
```

## Assets Monitored (25)

| Category | Assets |
|----------|--------|
| Yen Crosses | USDJPY, GBPJPY, AUDJPY, EURJPY, CADJPY |
| Commodity Currencies | AUDUSD, AUDCAD, AUDCHF, GBPAUD, EURAUD, EURCAD, GBPCAD |
| Safe Haven | USDCHF, EURCHF, GBPCHF, CADCHF |
| Europe Economy | EURUSD, EURGBP, GBPUSD |
| Crypto | ETHUSD |
| Commodities | XAUUSD, XAGUSD, XPTUSD |
| Indices | SPX500, NAS100 |

## Timeframes

- **4H** (240 min)
- **1H** (60 min)  
- **15min**

## Troubleshooting

**Login fails**: Run once with `headless=False` to handle captcha/2FA manually.

**OCR returns wrong values**: Check debug screenshots in `data/screenshots/`. Try switching to `ai_vision` method.

**TradingView rate limiting**: The scanner uses 2-5 second random delays between requests. Increase `delay_between_requests_max` in `src/config/assets.py` if needed.

**Chrome crashes in headless**: Ensure you have enough RAM (2GB+). Try `--disable-gpu` flag (already included).

## Adding/Removing Assets

Edit `src/config/assets.py` to modify the `ASSETS` dictionary. The symbol format must match TradingView's convention (e.g., `FX:EURUSD`, `OANDA:XAUUSD`, `BINANCE:ETHUSDT`).

## License

MIT
