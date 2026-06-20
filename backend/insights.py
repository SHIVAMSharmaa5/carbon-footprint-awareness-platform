"""
Insights engine.

Pure functions that turn raw log entries into the "personalized
insights" the challenge brief asks for. Kept free of database/HTTP
concerns so they can be unit tested directly (see tests/test_insights.py).
"""

from collections import defaultdict
from emission_factors import get_activity

# Comparison anchors so numbers mean something to a non-expert.
# Source: commonly cited averages (IPCC/EPA-style figures), presented
# as approximate "roughly equal to" comparisons, not precise claims.
TREE_ABSORPTION_KG_PER_YEAR = 21.0  # kg CO2 absorbed by one mature tree/year


def total_for_entries(entries: list[dict]) -> float:
    return round(sum(e["kg_co2e"] for e in entries), 2)


def breakdown_by_category(entries: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for e in entries:
        activity = get_activity(e["activity_key"])
        category = activity.category if activity else "other"
        totals[category] += e["kg_co2e"]
    return {k: round(v, 2) for k, v in totals.items()}


def biggest_contributor(entries: list[dict]) -> dict | None:
    """Find the single activity type responsible for the most emissions."""
    totals: dict[str, float] = defaultdict(float)
    for e in entries:
        totals[e["activity_key"]] += e["kg_co2e"]
    if not totals:
        return None
    key = max(totals, key=totals.get)
    activity = get_activity(key)
    return {
        "activity_key": key,
        "label": activity.label if activity else key,
        "kg_co2e": round(totals[key], 2),
    }


# Each rule: (trigger activity_key, message template, suggested swap)
SUGGESTION_RULES = [
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
    Generate 1-3 plain-language, personalized suggestions based on
    which activities contributed most. Returns an empty-state message
    if there's no data yet.
    """
    if not entries:
        return ["Log a few activities to get personalized suggestions."]

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        totals[e["activity_key"]] += e["kg_co2e"]
        counts[e["activity_key"]] += 1

    suggestions = []
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
    """How many mature trees (for a year) it'd take to absorb this much CO2e."""
    if TREE_ABSORPTION_KG_PER_YEAR == 0:
        return 0.0
    return round(total_kg / TREE_ABSORPTION_KG_PER_YEAR, 2)
