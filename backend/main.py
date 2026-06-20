"""
Carbon Footprint Awareness Platform — API server.

Built entirely on the Python standard library (http.server + sqlite3) —
no pip install required. Run with: python main.py
Then open frontend/index.html in a browser (or serve via http.server 5500).

Security posture (summary):
- Server always recomputes kg_co2e from trusted emission_factors.py; the
  client value is ignored entirely.
- All SQL uses parameterised queries — no string-formatted SQL anywhere.
- CORS is allow-listed to specific local dev origins only.
- All inputs are explicitly validated before touching the database.
- OWASP-recommended security headers are set on every response.
"""

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Union
from urllib.parse import urlparse, parse_qs

import insights
from database import get_connection, init_db
from emission_factors import get_activity, list_activities

PORT: int = 8000

# CORS: allow local dev origins only, not "*" — this is a deliberate
# security choice over the lazy wildcard default.
ALLOWED_ORIGINS: frozenset[str] = frozenset({
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:3000", "http://127.0.0.1:3000",
    "null",  # browsers send this Origin when a page is opened as a local file
})

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# OWASP-recommended security headers applied to every response.
# Content-Security-Policy allows only trusted sources for fonts.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "font-src https://fonts.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;"
    ),
}


# ---------- Validation helpers (the hand-rolled equivalent of Pydantic) ----------

class ValidationError(Exception):
    """Raised when client-supplied input fails validation."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def validate_log_entry(payload: dict) -> tuple[str, float, str]:
    """
    Validate and extract fields for a new log entry.

    Validates that:
    - activity_key is a known key in emission_factors.
    - quantity is a positive, realistic number (<= 100,000).
    - entry_date is a valid ISO 8601 date string that is not in the future.

    Args:
        payload: Decoded JSON body from the request.

    Returns:
        Tuple of (activity_key, quantity, entry_date) ready for DB insertion.

    Raises:
        ValidationError: If any field is missing, malformed, or out of range.
    """
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
    """
    Validate and extract the daily CO2e target value.

    Args:
        payload: Decoded JSON body from the request.

    Returns:
        Validated daily_target_kg as a float.

    Raises:
        ValidationError: If the value is missing, non-numeric, or out of range.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Body must be a JSON object")
    target = payload.get("daily_target_kg")
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        raise ValidationError("daily_target_kg must be a number")
    if target <= 0 or target > 1000:
        raise ValidationError("daily_target_kg must be between 0 and 1000")
    return float(target)


def clamp_days(raw: Optional[str], default: int = 7) -> int:
    """
    Parse and clamp a 'days' query parameter to the range [1, 365].

    Args:
        raw: Raw string value from the query string, or None if absent.
        default: Value to use when raw is None or unparseable.

    Returns:
        An integer in the inclusive range [1, 365].
    """
    try:
        days = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        days = default
    return max(1, min(days, 365))


# ---------- Data access (route logic kept thin, talks to database.py only) ----------

def ensure_demo_user() -> None:
    """Insert the single demo user (id=1) if it does not already exist."""
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (id, display_name, daily_target_kg) VALUES (1, ?, ?)",
                ("You", 12.0),
            )


def create_log_entry(activity_key: str, quantity: float, entry_date: str) -> dict:
    """
    Insert a new log entry and return its serialised form.

    The server always recomputes kg_co2e from the trusted emission_factors
    table; any client-supplied value is deliberately ignored.

    Args:
        activity_key: Validated activity identifier.
        quantity: Validated quantity in the activity's native unit.
        entry_date: Validated ISO 8601 date string.

    Returns:
        Dict with id, activity_key, label, quantity, kg_co2e, entry_date.
    """
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
    """
    Delete a log entry by ID, scoped to the demo user.

    Args:
        entry_id: Primary key of the log entry to remove.

    Returns:
        True if a row was deleted, False if no matching entry was found.
    """
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM log_entries WHERE id = ? AND user_id = ?", (entry_id, 1)
        )
        return result.rowcount > 0


def get_log_entries(days: int) -> list[dict]:
    """
    Fetch recent log entries for the demo user.

    Args:
        days: How many past days to include (1–365).

    Returns:
        List of entry dicts ordered by date desc, then id desc.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, activity_key, quantity, kg_co2e, entry_date FROM log_entries "
            "WHERE user_id = ? AND entry_date >= ? ORDER BY entry_date DESC, id DESC",
            (1, since),
        ).fetchall()
    out: list[dict] = []
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
    """
    Build the full insights payload for the given time window.

    Retrieves raw entries from the DB, then delegates all calculation
    to the pure functions in insights.py.

    Args:
        days: Window size in days (1–365).

    Returns:
        Dict containing totals, breakdown, suggestions, and derived metrics.
    """
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
    """
    Persist the user's daily carbon budget.

    Args:
        daily_target_kg: Validated target in kg CO2e per day.

    Returns:
        Dict echoing the saved value for the client to confirm.
    """
    with get_connection() as conn:
        conn.execute("UPDATE users SET daily_target_kg = ? WHERE id = 1", (daily_target_kg,))
    return {"daily_target_kg": daily_target_kg}


# ---------- HTTP layer ----------

class Handler(BaseHTTPRequestHandler):
    """
    Request handler for the Carbon Platform HTTP API.

    Routes:
        GET  /api/health       — Liveness probe.
        GET  /api/activities   — List all loggable activity types.
        GET  /api/log          — Fetch recent log entries (?days=N).
        POST /api/log          — Create a new log entry.
        DELETE /api/log/{id}   — Remove a log entry by ID.
        GET  /api/insights     — Get computed insights (?days=N).
        POST /api/target       — Set the daily CO2e budget.
    """

    server_version = "CarbonPlatform/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        """Override to use a cleaner timestamp format."""
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _cors_origin(self) -> Optional[str]:
        """
        Return the request Origin if it is in the allow-list, else None.

        Returns:
            Validated origin string, or None if the origin is not allowed.
        """
        origin = self.headers.get("Origin")
        return origin if origin in ALLOWED_ORIGINS else None

    def _send_security_headers(self) -> None:
        """Write all OWASP security headers to the current response."""
        for header, value in SECURITY_HEADERS.items():
            self.send_header(header, value)

    def _send_json(self, status: int, payload: object) -> None:
        """
        Serialise payload as JSON and write a complete HTTP response.

        Args:
            status: HTTP status code.
            payload: Any JSON-serialisable Python object.
        """
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_json_cached(self, status: int, payload: object, max_age: int = 0) -> None:
        """
        Serialise payload as JSON with Cache-Control headers.

        Args:
            status: HTTP status code.
            payload: Any JSON-serialisable Python object.
            max_age: Cache max-age in seconds. 0 means no-store (dynamic data).
        """
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        if max_age > 0:
            self.send_header("Cache-Control", f"public, max-age={max_age}")
        else:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        """
        Read and decode the JSON request body.

        Returns:
            Parsed JSON as a dict (empty dict if Content-Length is 0).

        Raises:
            ValidationError: If the body exceeds 1 MB or is not valid JSON.
        """
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > 1_000_000:  # 1 MB cap — guard against oversized payloads
            raise ValidationError("Request body too large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON body")

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_security_headers()
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Handle all GET requests and route to the appropriate handler."""
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                self._send_json_cached(200, {"status": "ok"}, max_age=0)
            elif path == "/api/activities":
                # Activity types are static data — safe to cache for 1 hour.
                self._send_json_cached(200, [a.__dict__ for a in list_activities()], max_age=3600)
            elif path == "/api/log":
                days = clamp_days(qs.get("days", [None])[0], default=30)
                self._send_json_cached(200, get_log_entries(days), max_age=0)
            elif path == "/api/insights":
                days = clamp_days(qs.get("days", [None])[0], default=7)
                self._send_json_cached(200, get_insights_payload(days), max_age=0)
            else:
                self._send_json(404, {"detail": "Not found"})
        except Exception as e:  # noqa: BLE001 — top-level safety net
            print(f"ERROR handling GET {path}: {e}")
            self._send_json(500, {"detail": "Internal server error"})

    def do_POST(self) -> None:
        """Handle all POST requests and route to the appropriate handler."""
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

    def do_DELETE(self) -> None:
        """Handle DELETE /api/log/{id} requests."""
        parsed = urlparse(self.path)
        match = re.match(r"^/api/log/(\d+)$", parsed.path)
        try:
            if match:
                entry_id = int(match.group(1))
                deleted = delete_log_entry(entry_id)
                if deleted:
                    self.send_response(204)
                    self._send_security_headers()
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


def main() -> None:
    """
    Entry point: initialise the database and start the HTTP server.

    Binds to 127.0.0.1 (loopback only) — not 0.0.0.0 — to limit
    exposure to the local machine during development.
    """
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
