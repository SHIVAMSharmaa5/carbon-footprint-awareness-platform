# Ledger — Carbon Footprint Awareness Platform

A personal carbon ledger: log daily activities (transport, energy, food, waste),
see a running "balance" against a daily target, and get personalized,
rule-based suggestions on what to change.

Built for **[Challenge 3] Carbon Footprint Awareness Platform** —
*"Design a solution that helps individuals understand, track, and reduce
their carbon footprint through simple actions and personalized insights."*

## Why this design

Most footprint trackers reach for leaf icons and a circular progress gauge.
This one is framed as a **financial ledger** instead — activities are line
items, there's a running balance, a daily "budget," and over/under-target
deltas — because people already have strong intuition for tracking a budget,
and that intuition transfers directly to a carbon budget.

## Architecture

```
carbon-platform/
├── backend/
│   ├── main.py              # HTTP server + routes (Python stdlib only)
│   ├── database.py          # SQLite connection + schema
│   ├── emission_factors.py  # Single source of truth for activity → kg CO2e
│   └── insights.py          # Pure functions: totals, breakdown, suggestions
├── frontend/
│   └── index.html           # Single-file UI (HTML/CSS/JS, no build step)
├── tests/
│   ├── test_insights.py     # Unit tests for the insights engine
│   └── test_api.py          # Integration tests against a live server instance
└── README.md
```

**No pip install, no npm, no Docker.** The backend uses only the Python
standard library (`http.server`, `sqlite3`, `json`) so it runs anywhere
Python 3.10+ is installed, with zero dependency resolution. The frontend is
one HTML file you open directly — no build tooling.

### Design decisions worth knowing about

- **Server computes all emissions.** The client never sends a `kg_co2e`
  value that gets trusted — `main.py` always recalculates
  `quantity × emission_factor` server-side from `emission_factors.py`.
  This closes the obvious "client sends a fake low number" exploit.
- **All SQL uses parameter binding** (`?` placeholders), never string
  formatting — no SQL injection surface.
- **CORS is allow-listed**, not wildcarded, to local dev origins only.
- **Input validation is explicit** (date format, future-date rejection,
  quantity bounds, unknown-activity rejection) rather than trusting the client.
- **Insights logic (`insights.py`) is pure** — no DB or HTTP — specifically
  so it's trivial to unit test in isolation from the web layer.

## How to run

### 1. Start the backend

Requires Python 3.10+. No pip install needed.

```bash
cd backend
python3 main.py
```

You should see:
```
Carbon Footprint Awareness Platform API running at http://127.0.0.1:8000
```

Leave this running in its own terminal.

### 2. Open the frontend

Just open `frontend/index.html` directly in a browser (double-click it, or
`open frontend/index.html` / `start frontend/index.html` depending on your OS).

That's it — no second server, no build step. The page talks to the API at
`http://127.0.0.1:8000`.

> If your browser blocks local file → localhost requests, serve the frontend
> folder instead: `cd frontend && python3 -m http.server 5500`, then visit
> `http://127.0.0.1:5500`. (Port 5500 is already in the backend's CORS allow-list.)

### 3. Try it

- Pick an activity (e.g. "Car (petrol) — km driven"), enter a quantity, hit **Add entry**.
- Watch the balance card, category bar, and suggestions update.
- Set a daily target under "Daily target" to see over/under-budget tracking.

## Running the tests

From the project root:

```bash
python3 -m unittest tests.test_insights -v
python3 -m unittest tests.test_api -v
```

Both suites use only the Python standard library (`unittest`, `urllib`) —
no `pytest` or `httpx` install required. `test_api.py` spins up a real
instance of the server on a separate port (8091) against a temporary SQLite
file, so it never touches your real data or collides with a dev server
running on 8000.

**30 tests total**, covering: emission math, category grouping, suggestion
rules, input validation (negative/oversized quantities, future dates,
malformed dates, unknown activities), the "server always recomputes
emissions" security property, delete/404 handling, and target-setting bounds.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/activities` | List loggable activity types + emission factors |
| GET | `/api/log?days=30` | Recent log entries |
| POST | `/api/log` | Create an entry — `{activity_key, quantity, entry_date}` |
| DELETE | `/api/log/{id}` | Remove an entry |
| GET | `/api/insights?days=7` | Totals, category breakdown, suggestions, trees-equivalent |
| POST | `/api/target` | Set daily target — `{daily_target_kg}` |
| GET | `/api/health` | Health check |

## Data source note

Emission factors in `emission_factors.py` are reasonable public averages
(EPA/DEFRA-style figures) intended for **awareness and comparison**, not
audit-grade carbon accounting. This is disclosed in the UI footer.

## Extending it

- Swap the single demo user for real accounts (the schema already has a
  `users` table with a foreign key from `log_entries` — just add auth).
- Add a `/api/insights/trend` endpoint that returns daily totals over time
  for a line chart.
- The suggestion engine (`SUGGESTION_RULES` in `insights.py`) is a simple
  list of trigger rules — add more activity-specific tips by appending to it.
