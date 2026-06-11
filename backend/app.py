"""FastAPI application exposing live Betfair × Polymarket data."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.service import run_live_scan

app = FastAPI(title="Betfair × Polymarket Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/dashboard/scan")
def dashboard_scan(
    sport: str = Query("all"),
    threshold: float = Query(0.35, ge=0.0, le=1.0),
    investment: float = Query(100.0, gt=0.0),
    gbp_usd_rate: float = Query(1.27, gt=0.0),
    betfair_days_ahead: int = Query(7, ge=1, le=30),
    betfair_min_hours_ahead: float = Query(0.0, ge=0.0, le=72.0),
    polymarket_active_only: bool = Query(True),
    polymarket_min_volume: float = Query(0.0, ge=0.0),
) -> dict:
    try:
        return run_live_scan(
            sport=sport,
            threshold=threshold,
            investment=investment,
            gbp_usd_rate=gbp_usd_rate,
            betfair_days_ahead=betfair_days_ahead,
            betfair_min_hours_ahead=betfair_min_hours_ahead,
            polymarket_active_only=polymarket_active_only,
            polymarket_min_volume=polymarket_min_volume,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
