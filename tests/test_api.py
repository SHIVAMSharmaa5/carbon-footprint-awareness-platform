"""
API-level integration tests. Spins up the actual http.server instance
on a separate test port (so it never collides with a dev server you
might have running on 8000) and exercises it with urllib — no extra
HTTP client library needed.

Run with: python3 -m unittest tests.test_api -v
"""

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import database  # noqa: E402

# Redirect the DB to a throwaway temp file before importing main,
# so tests never touch a real carbon_platform.db on disk.
_tmp_dir = tempfile.mkdtemp()
database.DB_PATH = Path(_tmp_dir) / "test.db"

import main  # noqa: E402

TEST_PORT = 8091
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

_server = None
_thread = None


def setUpModule():
    global _server, _thread
    main.init_db()
    main.ensure_demo_user()
    _server = main.ThreadingHTTPServer(("127.0.0.1", TEST_PORT), main.Handler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    time.sleep(0.2)  # give the server a moment to bind


def tearDownModule():
    _server.shutdown()
    _thread.join(timeout=2)


def request(method: str, path: str, body: dict | None = None):
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read()
        parsed = json.loads(raw) if raw else None
        return e.code, parsed


class TestActivitiesEndpoint(unittest.TestCase):
    def test_returns_list_of_activities(self):
        status, body = request("GET", "/api/activities")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 0)
        self.assertIn("key", body[0])
        self.assertIn("kg_co2e_per_unit", body[0])


class TestLogEndpoint(unittest.TestCase):
    def test_create_valid_entry(self):
        status, body = request("POST", "/api/log", {
            "activity_key": "car_petrol_km", "quantity": 10, "entry_date": "2026-06-15",
        })
        self.assertEqual(status, 201)
        self.assertEqual(body["kg_co2e"], round(0.192 * 10, 3))

    def test_rejects_unknown_activity(self):
        status, body = request("POST", "/api/log", {
            "activity_key": "made_up_activity", "quantity": 10, "entry_date": "2026-06-15",
        })
        self.assertEqual(status, 422)

    def test_rejects_negative_quantity(self):
        status, _ = request("POST", "/api/log", {
            "activity_key": "car_petrol_km", "quantity": -5, "entry_date": "2026-06-15",
        })
        self.assertEqual(status, 422)

    def test_rejects_future_date(self):
        status, _ = request("POST", "/api/log", {
            "activity_key": "car_petrol_km", "quantity": 5, "entry_date": "2099-01-01",
        })
        self.assertEqual(status, 422)

    def test_rejects_malformed_date(self):
        status, _ = request("POST", "/api/log", {
            "activity_key": "car_petrol_km", "quantity": 5, "entry_date": "not-a-date",
        })
        self.assertEqual(status, 422)

    def test_server_computes_emissions_not_client(self):
        """Client cannot pass kg_co2e directly — server always recomputes it server-side."""
        status, body = request("POST", "/api/log", {
            "activity_key": "bike_walk_km",  # 0 kg CO2e per km
            "quantity": 100, "entry_date": "2026-06-15", "kg_co2e": 99999,
        })
        self.assertEqual(status, 201)
        self.assertEqual(body["kg_co2e"], 0.0)

    def test_rejects_oversized_quantity(self):
        status, _ = request("POST", "/api/log", {
            "activity_key": "car_petrol_km", "quantity": 999_999_999, "entry_date": "2026-06-15",
        })
        self.assertEqual(status, 422)


class TestDeleteEndpoint(unittest.TestCase):
    def test_delete_nonexistent_entry_returns_404(self):
        status, _ = request("DELETE", "/api/log/999999")
        self.assertEqual(status, 404)

    def test_delete_existing_entry(self):
        _, created = request("POST", "/api/log", {
            "activity_key": "train_km", "quantity": 5, "entry_date": "2026-06-15",
        })
        status, _ = request("DELETE", f"/api/log/{created['id']}")
        self.assertEqual(status, 204)


class TestInsightsEndpoint(unittest.TestCase):
    def test_insights_returns_expected_shape(self):
        status, body = request("GET", "/api/insights?days=7")
        self.assertEqual(status, 200)
        for key in ["total_kg_co2e", "breakdown_by_category", "suggestions", "trees_equivalent"]:
            self.assertIn(key, body)

    def test_days_param_is_clamped(self):
        status, body = request("GET", "/api/insights?days=99999")
        self.assertEqual(status, 200)
        self.assertEqual(body["period_days"], 365)


class TestTargetEndpoint(unittest.TestCase):
    def test_set_valid_target(self):
        status, body = request("POST", "/api/target", {"daily_target_kg": 8.5})
        self.assertEqual(status, 200)
        self.assertEqual(body["daily_target_kg"], 8.5)

    def test_rejects_negative_target(self):
        status, _ = request("POST", "/api/target", {"daily_target_kg": -1})
        self.assertEqual(status, 422)


class TestHealthEndpoint(unittest.TestCase):
    def test_health_ok(self):
        status, body = request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})


class TestUnknownRoutes(unittest.TestCase):
    def test_unknown_get_returns_404(self):
        status, _ = request("GET", "/api/does-not-exist")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
