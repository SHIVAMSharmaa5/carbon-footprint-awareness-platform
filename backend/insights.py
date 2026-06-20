"""
Insights engine.

Pure functions that turn raw log entries into the "personalized
insights" the challenge brief asks for. Kept free of database/HTTP
concerns so they can be unit tested directly (see tests/test_insights.py).

All functions accept plain dicts so they are decoupled from both the
SQLite row type and any HTTP framework — the caller is responsible for
converting database rows to dicts before passing them here.
"""

from collections import defaultdict
from typing import Optional
from emission_factors import get_activity

# Comparison anchors so numbers mean something to a non-expert.
# Source: commonly cited averages (IPCC/EPA-style figures), presented
# as approximate "roughly equal to" comparisons, not precise claims.
TREE_ABSORPTION_KG_PER_YEAR: float = 21.0  # kg CO2 absorbed by one mature tree/year


def total_for_entries(entries: list[dict]) -> float:
    """
    Compute the total CO2e (kg) emitted across all log entries.

    Args:
        entries: List of log entry dicts, each containing a 'kg_co2e' key.

    Returns:
        Rounded total of all emissions to 2 decimal places.
    """
    return round(sum(e["kg_co2e"] for e in entries), 2)


def breakdown_by_category(entries: list[dict]) -> dict[str, float]:
    """
    Group total CO2e emissions by activity category.

    Unknown activity keys are grouped under the 'other' category so
    bad data never raises an exception in the hot path.

    Args:
        entries: List of log entry dicts with 'activity_key' and 'kg_co2e' keys.

    Returns:
        Dict mapping category name → rounded total kg CO2e.
    """
    totals: dict[str, float] = defaultdict(float)
    for e in entries:
        activity = get_activity(e["activity_key"])
        category = activity.category if activity else "other"
        totals[category] += e["kg_co2e"]
    return {k: round(v, 2) for k, v in totals.items()}


def biggest_contributor(entries: list[dict]) -> Optional[dict]:
    """
    Find the single activity type responsible for the most CO2e in the period.

    Args:
        entries: List of log entry dicts with 'activity_key' and 'kg_co2e' keys.

    Returns:
        Dict with 'activity_key', 'label', and 'kg_co2e', or None if entries is empty.
    """
    totals: dict[str, float] = defaultdict(float)
    for e in entries:
        totals[e["activity_key"]] += e["kg_co2e"]
    if not totals:
        return None
    key = max(totals, key=lambda k: totals[k])
    activity = get_activity(key)
    return {
        "activity_key": key,
        "label": activity.label if activity else key,
        "kg_co2e": round(totals[key], 2),
    }


# Each rule: (trigger activity_key, message template, suggested swap)
# The rule list is intentionally data-driven so new tips can be added
# without touching function logic — just append a new dict.
SUGGESTION_RULES: list[dict] = [
    {
        "trigger": "car_petrol_km",
        "min_kg": 5.0,
        "message": "Short car trips are your top source this period. Swapping {swap_count} of them for "
                    "a bus or bike could cut roughly {savings} kg CO2e.",
        "swap_to": "bus_km",
    },
    {
        "trigger": "meal_beef",
        "min_kg": 5.0,
        "message": "Beef meals are a major contributor. Replacing {swap_count} with a vegetarian meal "
                    "could save roughly {savings} kg CO2e.",
        "swap_to": "meal_vegetarian",
    },
    {
        "trigger": "electricity_kwh",
        "min_kg": 8.0,
        "message": "Electricity use is high this period. Small habits (LED bulbs, unplugging idle "
                    "devices) compound — even a 10% cut saves roughly {savings} kg CO2e.",
        "swap_to": None,
    },
    {
        "trigger": "flight_long_km",
        "min_kg": 50.0,
        "message": "Long-haul flights dominate your footprint. There's no easy swap here — consider "
                    "offsetting or combining trips where possible.",
        "swap_to": None,
    },
]


def generate_suggestions(entries: list[dict]) -> list[str]:
    """
    Generate 1–3 plain-language, personalised suggestions based on
    which activities contributed most.

    Returns an empty-state message if there is no data yet, so callers
    always receive at least one non-empty string.

    Args:
        entries: List of log entry dicts with 'activity_key' and 'kg_co2e' keys.

    Returns:
        List of 1–3 human-readable suggestion strings.
    """
    if not entries:
        return ["Log a few activities to get personalized suggestions."]

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        totals[e["activity_key"]] += e["kg_co2e"]
        counts[e["activity_key"]] += 1

    suggestions: list[str] = []
    for rule in SUGGESTION_RULES:
        key = rule["trigger"]
        if totals.get(key, 0) >= rule["min_kg"]:
            swap_activity = get_activity(rule["swap_to"]) if rule["swap_to"] else None
            trigger_activity = get_activity(key)
            if swap_activity and trigger_activity:
                per_unit_savings = trigger_activity.kg_co2e_per_unit - swap_activity.kg_co2e_per_unit
                swap_count = max(1, counts[key] // 2)
                savings = round(per_unit_savings * swap_count, 1)
                suggestions.append(rule["message"].format(swap_count=swap_count, savings=savings))
            else:
                suggestions.append(rule["message"])

    if not suggestions:
        suggestions.append("Your footprint looks balanced — keep logging to track trends over time.")

    return suggestions[:3]


def trees_equivalent(total_kg: float) -> float:
    """
    Convert a total CO2e amount into a "trees for a year" equivalent.

    This is a comparison anchor, not a precise offset calculation.
    One mature tree absorbs approximately 21 kg CO2 per year (IPCC average).

    Args:
        total_kg: Total CO2e in kilograms.

    Returns:
        Equivalent number of mature trees required to absorb this CO2e in one year,
        rounded to 2 decimal places.
    """
    if TREE_ABSORPTION_KG_PER_YEAR == 0:
        return 0.0
    return round(total_kg / TREE_ABSORPTION_KG_PER_YEAR, 2)
