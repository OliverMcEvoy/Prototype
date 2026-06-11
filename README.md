# Betfair × Polymarket Arbitrage Scanner

Cross-platform arbitrage between Betfair Exchange and Polymarket sports markets.

## How It Works

- **Back-back**: Best Betfair back price + best Polymarket implied odds. Combined implied probability < 1.0 = locked profit regardless of outcome.
- **Lay-back**: Lay on Betfair, back on Polymarket. Profitable when Polymarket's implied probability exceeds Betfair's lay-implied probability.

## Setup

**Requirements:** Python 3.8+, Betfair account with a Delayed App Key.

````bash
python3 -m venv .venv
# Betfair × Polymarket Arbitrage Scanner

Cross-platform arbitrage between Betfair Exchange and Polymarket.

## Stack

- Frontend: React + Vite + TypeScript (`frontend/`)
- Backend: FastAPI + Python services (`backend/`)
- Data providers: Betfair Exchange API and Polymarket API

## Quick Start

### 1) Start backend (terminal A)

```bash
cd /home/omcevoy/Prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
````

### 2) Start frontend (terminal B)

```bash
cd /home/omcevoy/Prototype/frontend
npm install
npm run dev
```

Frontend runs on http://127.0.0.1:5173 and proxies `/api/*` to backend `:8000`.

## Repository Structure

```text
backend/                     # Source-of-truth Python backend
	app.py                     # FastAPI routes
	service.py                 # Live scan orchestration
	betfair_client.py          # Betfair integration
	polymarket_client.py       # Polymarket integration
	arbitrage_engine.py        # Arbitrage calculations
	market_matcher.py          # Cross-platform matching
	matchers/                  # Sport-specific matchers
	tests/                     # Backend tests + diagnostics

frontend/                    # React app for UI development
	src/App.tsx                # Dashboard UI and API fetch
	src/main.tsx               # Frontend entrypoint
	src/styles.css             # Shared CSS styles
	vite.config.js             # Dev proxy (/api -> backend)
	tsconfig.json              # TypeScript config

docs/
	API_README.md              # API contract and payload shape
	ARCHITECTURE.md            # Layering and design notes

app.py                       # Legacy CLI notice (no Streamlit)
*.py at root                 # Compatibility shims -> backend.*
```

## Documentation

- API structure: [docs/API_README.md](docs/API_README.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Notes

- Betfair credentials are required for live Betfair scans.
- Polymarket is public read-only for market data.
- Odds move quickly; always re-check before execution.

## Opportunity Permalinks

- Each opportunity row opens a client-side permalink in the form `#/opportunity/<id>`.
- The opportunity ID is derived from the opportunity label plus a small fingerprint of the market data, so the link stays stable for the same scan result.
- When a user opens an opportunity, the dashboard saves a snapshot in browser `localStorage` so the detail page can render even after a refresh.
- If the snapshot is missing, the detail page falls back to the currently loaded scan results and shows a loading state until the opportunity can be recovered.
