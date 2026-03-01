# Betfair × Polymarket Arbitrage Scanner

Cross-platform arbitrage between Betfair Exchange and Polymarket sports markets.

## How It Works

- **Back-back**: Best Betfair back price + best Polymarket implied odds. Combined implied probability < 1.0 = locked profit regardless of outcome.
- **Lay-back**: Lay on Betfair, back on Polymarket. Profitable when Polymarket's implied probability exceeds Betfair's lay-implied probability.

## Setup

**Requirements:** Python 3.8+, Betfair account with a Delayed App Key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

**Betfair App Key:** My Account → API Access → Create Developer Application Key. The free Delayed key is sufficient.

**Polymarket:** Public API — no key required.

## Project Structure

```
app.py                # Streamlit dashboard
config.py             # Configuration
models.py             # Data models
betfair_client.py     # Betfair Exchange API client
polymarket_client.py  # Polymarket API client
arbitrage_engine.py   # Arbitrage detection logic
market_matcher.py     # Cross-platform event matching
utils.py              # Odds conversion utilities
```

## Notes

- Betfair charges ~5% commission on exchange winnings.
- Polymarket requires USDC on the Polygon network.
- Odds change fast — verify before placing.
- Match quality below 80% warrants manual confirmation.
- `match_debug.txt` is written on each scan — use it to tune the alias table in `market_matcher.py`.
