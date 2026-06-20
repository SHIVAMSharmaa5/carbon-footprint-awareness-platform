"""
Carbon Footprint Awareness Platform — API server.

Built entirely on the Python standard library (http.server + sqlite3) —
no pip install required. Run with: python3 main.py
Then open frontend/index.html in a browser.
"""

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import insights
from database import get_connection, init_db
from emission_factors import get_activity, list_activities

PORT = 8000

# CORS: allow local dev origins only, not "*" — this is a deliberate
# security choice over the lazy wildcard default.
ALLOWED_ORIGINS = {
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:3000", "http://127.0.0.1:3000",
    "null",  # browsers send this Origin when a page is opened as a local file
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- Validation helpers (the hand-rolled equivalent of Pydantic) ----------

class ValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def validate_log_entry(payload: dict) -> tuple[str, float, str]:
    if not isinstance(payload, dict):
        raise ValidationError("Body must be a JSON object")

    activity_key = payload.get("activity_key")
    if not isinstance(activity_key, str) or not activity_key.strip():
        raise ValidationError("activity_key is required")
    if get_activity(activity_key) is None:
        raise ValidationError(f"Unknown activity_key: {activity_key}")

    quantity = payload.get("quantity")
    if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
        raise ValidationError("quantity must be a number")
    if quantity <= 0 or quantity > 100_000:
        raise ValidationError("quantity must be greater than 0 and realistic (<= 100000)")

    entry_date = payload.get("entry_date")
    if not isinstance(entry_date, str) or not DATE_RE.match(entry_date):
        raise ValidationError("entry_date must be in YYYY-MM-DD format")
    try:
        parsed = datetime.strptime(entry_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError("entry_date is not a valid calendar date")
    if parsed > date.today():
        raise ValidationError("entry_date cannot be in the future")

    return activity_key, float(quantity), entry_date


def validate_target(payload: dict) -> float:
    if not isinstance(payload, dict):
        raise ValidationError("Body must be a JSON object")
    target = payload.get("daily_target_kg")
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        raise ValidationError("daily_target_kg must be a number")
    if target <= 0 or target > 1000:
        raise ValidationError("daily_target_kg must be between 0 and 1000")
    return float(target)


def clamp_days(raw: str | None, default: int = 7) -> int:
    try:
        days = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        days = default
    return max(1, min(days, 365))


# ---------- Data access (route logic kept thin, talks to database.py only) ----------

def ensure_demo_user() -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (id, display_name, daily_target_kg) VALUES (1, ?, ?)",
                ("You", 12.0),
            )


def create_log_entry(activity_key: str, quantity: float, entry_date: str) -> dict:
    activity = get_activity(activity_key)
    kg_co2e = round(activity.kg_co2e_per_unit * quantity, 3)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO log_entries (user_id, activity_key, quantity, kg_co2e, entry_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, activity_key, quantity, kg_co2e, entry_date),
        )
        new_id = cursor.lastrowid
    return {
        "id": new_id, "activity_key": activity_key, "label": activity.label,
        "quantity": quantity, "kg_co2e": kg_co2e, "entry_date": entry_date,
    }


def delete_log_entry(entry_id: int) -> bool:
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM log_entries WHERE id = ? AND user_id = ?", (entry_id, 1)
        )
        return result.rowcount > 0


def get_log_entries(days: int) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, activity_key, quantity, kg_co2e, entry_date FROM log_entries "
            "WHERE user_id = ? AND entry_date >= ? ORDER BY entry_date DESC, id DESC",
            (1, since),
        ).fetchall()
    out = []
    for r in rows:
        activity = get_activity(r["activity_key"])
        out.append({
            "id": r["id"], "activity_key": r["activity_key"],
            "label": activity.label if activity else r["activity_key"],
            "icon": activity.icon if activity else "•",
            "quantity": r["quantity"], "kg_co2e": r["kg_co2e"], "entry_date": r["entry_date"],
        })
    return out


def get_insights_payload(days: int) -> dict:
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT activity_key, kg_co2e, entry_date FROM log_entries "
            "WHERE user_id = ? AND entry_date >= ?",
            (1, since),
        ).fetchall()
        target_row = conn.execute("SELECT daily_target_kg FROM users WHERE id = 1").fetchone()

    entries = [dict(r) for r in rows]
    total = insights.total_for_entries(entries)
    daily_target = target_row["daily_target_kg"] if target_row else 12.0
    period_target = round(daily_target * days, 2)

    return {
        "period_days": days,
        "total_kg_co2e": total,
        "daily_average_kg_co2e": round(total / days, 2) if days else 0,
        "period_target_kg_co2e": period_target,
        "over_under_target_kg": round(total - period_target, 2),
        "breakdown_by_category": insights.breakdown_by_category(entries),
        "biggest_contributor": insights.biggest_contributor(entries),
        "suggestions": insights.generate_suggestions(entries),
        "trees_equivalent": insights.trees_equivalent(total),
    }


def set_target(daily_target_kg: float) -> dict:
    with get_connection() as conn:
        conn.execute("UPDATE users SET daily_target_kg = ? WHERE id = 1", (daily_target_kg,))
    return {"daily_target_kg": daily_target_kg}


# ---------- HTTP layer ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "CarbonPlatform/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        return origin if origin in ALLOWED_ORIGINS else None

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > 1_000_000:  # 1MB cap — basic guard against oversized payloads
            raise ValidationError("Request body too large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON body")

    def do_OPTIONS(self):
        self.send_response(204)
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                self._send_json(200, {"status": "ok"})
            elif path == "/api/activities":
                self._send_json(200, [a.__dict__ for a in list_activities()])
            elif path == "/api/log":
                days = clamp_days(qs.get("days", [None])[0], default=30)
                self._send_json(200, get_log_entries(days))
            elif path == "/api/insights":
                days = clamp_days(qs.get("days", [None])[0], default=7)
                self._send_json(200, get_insights_payload(days))
            else:
                self._send_json(404, {"detail": "Not found"})
        except Exception as e:  # noqa: BLE001 — top-level safety net, never leak tracebacks to client
            print(f"ERROR handling GET {path}: {e}")
            self._send_json(500, {"detail": "Internal server error"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/log":
                body = self._read_json_body()
                activity_key, quantity, entry_date = validate_log_entry(body)
                result = create_log_entry(activity_key, quantity, entry_date)
                self._send_json(201, result)
            elif path == "/api/target":
                body = self._read_json_body()
                target = validate_target(body)
                self._send_json(200, set_target(target))
            else:
                self._send_json(404, {"detail": "Not found"})
        except ValidationError as e:
            self._send_json(422, {"detail": e.message})
        except Exception as e:  # noqa: BLE001
            print(f"ERROR handling POST {path}: {e}")
            self._send_json(500, {"detail": "Internal server error"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        match = re.match(r"^/api/log/(\d+)$", parsed.path)
        try:
            if match:
                entry_id = int(match.group(1))
                deleted = delete_log_entry(entry_id)
                if deleted:
                    self.send_response(204)
                    origin = self._cors_origin()
                    if origin:
                        self.send_header("Access-Control-Allow-Origin", origin)
                    self.end_headers()
                else:
                    self._send_json(404, {"detail": "Entry not found"})
            else:
                self._send_json(404, {"detail": "Not found"})
        except Exception as e:  # noqa: BLE001
            print(f"ERROR handling DELETE {parsed.path}: {e}")
            self._send_json(500, {"detail": "Internal server error"})


def main():
    init_db()
    ensure_demo_user()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Carbon Footprint Awareness Platform API running at http://127.0.0.1:{PORT}")
    print("Open frontend/index.html in your browser to use the app.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
