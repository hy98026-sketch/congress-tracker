# 🏛️ Congress Trade Tracker

Automatically tracks stock trades by **every trading member of US Congress** and builds a Trading 212 pie weighted by conviction — the more members buying a stock, the higher its allocation.

## How It Works

```
House Stock Watcher API  +  Senate Stock Watcher API
              ↓                        ↓
         [scraper.py] — Fetches ALL members' trades
                    ↓
         [portfolio.py] — Builds conviction-weighted allocation
                    ↓
         [t212.py] — Syncs to your Trading 212 pie
                    ↓
         [notifier.py] — Telegram alerts on changes
```

**Why "conviction" weighting?**  
If 15 different Congress members are all buying NVDA, that's a way stronger signal than 1 member buying some random small-cap. The pie automatically weights by how many members hold each stock.

## Example Output

```
NVDA    35.4%  (8 members buying)
AAPL    21.5%  (5 members buying)
GOOGL   13.0%  (3 members buying)
MSFT    12.9%  (3 members buying)
AMZN     8.7%  (2 members buying)
PLTR     8.5%  (2 members buying)
```

Stocks only make it into the pie if **2+ members** are independently buying them. Single-member plays are filtered out.

## Setup

### 1. Clone and install
```bash
git clone <your-repo>
cd congress-tracker
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
cp .env.example .env
# Fill in your Telegram bot token, chat ID, and T212 API keys
```

### 3. Test locally
```bash
# Verify the portfolio logic works
python test_portfolio.py

# Dry run — fetches real data, builds portfolio, doesn't touch T212
python main.py --dry-run

# Single run with T212 sync
python main.py

# Continuous loop (what Railway runs)
python main.py --loop
```

### 4. Deploy to Railway
Same as your Vinted bots:
1. Push to GitHub
2. Connect in Railway
3. Add env vars in Railway dashboard
4. Procfile handles the rest

## Trading 212 API Setup

1. Open Trading 212 app → **Settings → API (beta)**
2. Generate API key + secret
3. **Start with `T212_ENVIRONMENT=demo`** (paper trading)
4. Verify everything works, then switch to `live`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL` | `3600` | Seconds between checks |
| `WEIGHTING_METHOD` | `conviction` | `conviction`, `volume`, or `equal` |
| `MIN_MEMBER_OVERLAP` | `2` | Minimum members buying for inclusion |
| `MAX_PIE_STOCKS` | `50` | T212 pie limit |
| `LOOKBACK_DAYS` | `180` | Trade history window |
| `PIE_NAME` | `Congress Tracker` | Name shown in T212 |

## File Structure

```
congress-tracker/
├── config.py           # All settings + env vars
├── scraper.py          # Fetches trades from House + Senate APIs
├── portfolio.py        # Builds weighted allocations
├── t212.py             # Trading 212 pie management
├── notifier.py         # Telegram alerts
├── main.py             # Entry point + main loop
├── test_portfolio.py   # Tests with mock data
├── requirements.txt
├── Procfile            # Railway deployment
├── .env.example
└── data/               # Auto-created
    ├── trades.json
    ├── portfolio.json
    └── history.json
```

## Data Sources

| Source | Coverage | Format | Cost |
|--------|----------|--------|------|
| House Stock Watcher | All House members | JSON (S3) | Free |
| Senate Stock Watcher | All Senate members | JSON (S3) | Free |

Both sources pull from official STOCK Act disclosures.

## Disclaimers

- Congress members have up to **45 days** to report trades
- This is an automation project, **not financial advice**
- Past performance ≠ future results
- Not all US stocks are available on Trading 212
- The 2025 top 10 had **zero overlap** with the 2024 top 10

## Security

- **Never hardcode API keys** — always use environment variables
- Start with T212 demo mode before using real money
- The bot only reads trade data and manages one pie — it can't withdraw money
