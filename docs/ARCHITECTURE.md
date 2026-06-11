# Architecture Overview

## Goals

- Keep market-fetching and matching logic in Python.
- Use React for frontend development velocity.
- Keep backend API thin and explicit.

## Layers

1. **Frontend (Node.js + React + Vite)**
   - Location: `frontend/`
   - Responsibilities:
     - Render dashboard UI
     - Trigger scans
     - Display matched pairs and opportunities
       - Build opportunity permalinks and restore saved opportunity snapshots
   - Talks to backend over HTTP (`/api/...`)

2. **Backend API (FastAPI)**
   - Location: `backend/app.py`
   - Responsibilities:
     - Expose API endpoints
     - Validate request parameters
     - Return JSON responses

3. **Domain services / engine**
   - Location: `backend/service.py`, `backend/arbitrage_engine.py`, `backend/market_matcher.py`
   - Responsibilities:
     - Fetch live data from providers
     - Match events across platforms
     - Compute arbitrage opportunities

4. **External integrations**
   - Betfair: `backend/betfair_client.py`
   - Polymarket: `backend/polymarket_client.py`

5. **Matcher subsystem**
   - Location: `backend/matchers/`
   - Responsibilities:
     - Sport-specific matching logic and aliasing

6. **Tests**
   - Location: `backend/tests/`
   - Contains API tests, service tests, diagnostics, and politics/matching tests.

## Migration note

Root-level Python modules are now compatibility shims that re-export
`backend.*` modules. New development should target backend files directly.

## Request flow

```text
React UI -> GET /api/dashboard/scan -> FastAPI route
       -> backend.service.run_live_scan()
       -> BetfairClient + PolymarketClient
       -> MarketMatcher + ArbitrageEngine
       -> JSON payload -> React render
```

## Opportunity detail flow

Opportunity rows on the dashboard open a hash route like `#/opportunity/<id>`.
The frontend stores a snapshot in browser `localStorage` before navigation so the
detail page can render immediately on return or refresh.

If the snapshot is not cached, the detail page attempts to resolve the same
opportunity from the latest scan data already loaded in memory. This keeps the
permalink client-side and avoids needing a backend route for each opportunity.

## Why Node.js is used here

Node.js is used for frontend tooling/runtime:

- Vite dev server
- TypeScript/JS bundling
- Hot reload during UI development

Node.js does not replace Python in this design; Python remains the source of
truth for market logic and live provider integrations.
