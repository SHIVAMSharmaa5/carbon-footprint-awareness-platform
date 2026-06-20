"""
Unit tests for insights.py — pure functions, no DB/HTTP required.
Run with: python3 -m unittest tests.test_insights -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import insights  # noqa: E402


def make_entry(activity_key: str, kg_co2e: float, entry_date: str = "2026-06-15") -> dict:
    return {"activity_key": activity_key, "kg_co2e": kg_co2e, "entry_date": entry_date}


class TestTotals(unittest.TestCase):
    def test_empty_list_returns_zero(self):
        self.assertEqual(insights.total_for_entries([]), 0)

    def test_sums_correctly(self):
        entries = [make_entry("car_petrol_km", 5.0), make_entry("electricity_kwh", 2.5)]
        self.assertEqual(insights.total_for_entries(entries), 7.5)

    def test_rounds_to_two_decimals(self):
        entries = [make_entry("car_petrol_km", 1.111), make_entry("electricity_kwh", 2.222)]
        self.assertEqual(insights.total_for_entries(entries), 3.33)


class TestBreakdownByCategory(unittest.TestCase):
    def test_groups_by_category(self):
        entries = [
            make_entry("car_petrol_km", 10.0),   # transport
            make_entry("train_km", 2.0),          # transport
            make_entry("electricity_kwh", 5.0),   # energy
        ]
        result = insights.breakdown_by_category(entries)
        self.assertEqual(result["transport"], 12.0)
        self.assertEqual(result["energy"], 5.0)

    def test_unknown_activity_key_goes_to_other(self):
        entries = [make_entry("not_a_real_activity", 3.0)]
        result = insights.breakdown_by_category(entries)
        self.assertEqual(result["other"], 3.0)

    def test_empty_entries_returns_empty_dict(self):
        self.assertEqual(insights.breakdown_by_category([]), {})


class TestBiggestContributor(unittest.TestCase):
    def test_returns_none_for_empty(self):
        self.assertIsNone(insights.biggest_contributor([]))

    def test_finds_largest_total(self):
        entries = [
            make_entry("car_petrol_km", 3.0),
            make_entry("car_petrol_km", 3.0),  # total 6.0, should win
            make_entry("electricity_kwh", 5.0),
        ]
        result = insights.biggest_contributor(entries)
        self.assertEqual(result["activity_key"], "car_petrol_km")
        self.assertEqual(result["kg_co2e"], 6.0)


class TestSuggestions(unittest.TestCase):
    def test_empty_state_message_when_no_data(self):
        result = insights.generate_suggestions([])
        self.assertEqual(len(result), 1)
        self.assertIn("log", result[0].lower())

    def test_high_car_usage_triggers_suggestion(self):
        entries = [make_entry("car_petrol_km", 10.0) for _ in range(4)]
        result = insights.generate_suggestions(entries)
        self.assertTrue(any("car" in s.lower() or "trip" in s.lower() for s in result))

    def test_always_returns_at_least_one_suggestion(self):
        entries = [make_entry("bike_walk_km", 0.0)]
        result = insights.generate_suggestions(entries)
        self.assertGreaterEqual(len(result), 1)

    def test_never_returns_more_than_three_suggestions(self):
        entries = (
            [make_entry("car_petrol_km", 10.0) for _ in range(4)]
            + [make_entry("meal_beef", 10.0) for _ in range(4)]
            + [make_entry("electricity_kwh", 15.0)]
            + [make_entry("flight_long_km", 60.0)]
        )
        result = insights.generate_suggestions(entries)
        self.assertLessEqual(len(result), 3)


class TestTreesEquivalent(unittest.TestCase):
    def test_zero_emissions_zero_trees(self):
        self.assertEqual(insights.trees_equivalent(0), 0.0)

    def test_known_value(self):
        # 21 kg/year per tree -> 21 kg should equal ~1 tree
        self.assertEqual(insights.trees_equivalent(21.0), 1.0)


if __name__ == "__main__":
    unittest.main()
