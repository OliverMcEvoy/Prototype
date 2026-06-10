# Backend API Guide

This document describes how the React frontend calls the Python backend.

## Base URL

- Local backend: `http://127.0.0.1:8000`
- Frontend dev mode uses Vite proxy, so frontend can call relative `/api/...`.

## Endpoints

### `GET /api/health`

Health check endpoint.

**Response**

```json
{
  "ok": true
}
```

---

### `GET /api/dashboard/scan`

Runs a live scan against Betfair + Polymarket, then returns matched pairs,
opportunities, and event samples.

**Query params**

- `sport` (string, default: `all`)
  - examples: `all`, `soccer`, `basketball`, `tennis`, `politics`
- `threshold` (float, default: `0.35`, range: `0.0..1.0`)
- `investment` (float, default: `100.0`, must be `> 0`)
- `gbp_usd_rate` (float, default: `1.27`, must be `> 0`)
- `betfair_days_ahead` (int, default: `7`, range: `1..30`)
- `betfair_min_hours_ahead` (float, default: `0.0`, range: `0.0..72.0`)
- `polymarket_active_only` (bool, default: `true`)
- `polymarket_min_volume` (float, default: `0.0`, must be `>= 0`)

**Example**

```http
GET /api/dashboard/scan?sport=all&threshold=0.35&investment=100&gbp_usd_rate=1.27
```

Extended example:

```http
GET /api/dashboard/scan?sport=soccer&threshold=0.35&investment=100&gbp_usd_rate=1.27&betfair_days_ahead=7&betfair_min_hours_ahead=0&polymarket_active_only=true&polymarket_min_volume=0
```

**Response shape**

```json
{
  "ok": true,
  "sport": "all",
  "threshold": 0.35,
  "investment": 100.0,
  "gbp_usd_rate": 1.27,
  "betfair_days_ahead": 7,
  "betfair_min_hours_ahead": 0.0,
  "polymarket_active_only": true,
  "polymarket_min_volume": 0.0,
  "generated_at": "2026-06-10T12:34:56+00:00",
  "betfair_event_count": 393,
  "polymarket_event_count": 1109,
  "matched_pair_count": 147,
  "unmatched_betfair_count": 246,
  "unmatched_polymarket_count": 962,
  "matched_pairs": [
    {
      "betfair": {
        "id": "...",
        "home_team": "...",
        "away_team": "...",
        "outcomes": []
      },
      "polymarket": {
        "id": "...",
        "question": "...",
        "outcomes": [],
        "prices": []
      },
      "similarity": 0.91
    }
  ],
  "opportunity_count": 19,
  "opportunities": [
    {
      "event": { "id": "...", "description": "..." },
      "best_outcomes": [],
      "total_stake": 100.0,
      "stake_distribution": {},
      "profit": 6.4,
      "profit_percentage": 6.4,
      "roi": 6.4
    }
  ],
  "sample_betfair_events": [],
  "sample_polymarket_markets": []
}
```

## Error handling

If upstream requests fail (e.g., Betfair login/network), API returns:

- Status: `502`
- Body:

```json
{
  "detail": "...error message..."
}
```

## Frontend usage

Current frontend call pattern in `frontend/src/App.tsx`:

```js
fetch("/api/dashboard/scan?sport=all");
```

In production, configure your reverse proxy/load balancer so `/api/*` routes to
the FastAPI service.

## Opportunity permalinks

Opportunity detail links are handled entirely in the frontend. The dashboard
uses hash routes like `#/opportunity/<id>` and saves a browser snapshot of the
clicked opportunity in `localStorage` before navigating.

That means the backend does not expose a separate opportunity-detail endpoint;
the permalink is a client-side view over the latest scan payload.
