"""
Emission factor reference data.

Factors are kg CO2e per unit, sourced from widely cited public datasets
(EPA, DEFRA, IPCC averages). These are reasonable estimates for an
awareness tool, not audit-grade figures — the UI labels them as such.

Keeping this as a single typed table (rather than scattered magic
numbers in route handlers) is what lets /api/activities validate input
and /api/insights compute suggestions from the same source of truth.

Design choice: ActivityType is a frozen dataclass (immutable) to make
it safe to return instances directly from the module-level dict without
defensive copying. Callers cannot mutate the reference data.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ActivityType:
    """
    Represents a single loggable activity with its emission factor.

    Attributes:
        key: Unique machine-readable identifier used in API payloads.
        label: Human-readable display name shown in the UI.
        category: Grouping used for breakdown charts. One of:
            'transport' | 'energy' | 'food' | 'waste'.
        unit: The physical unit in which quantity is measured (e.g. 'km', 'kWh').
        kg_co2e_per_unit: CO2-equivalent emissions per unit of activity (kg).
        icon: Emoji icon kept in sync between backend and frontend via this table.
    """

    key: str
    label: str
    category: str
    unit: str
    kg_co2e_per_unit: float
    icon: str


ACTIVITY_TYPES: dict[str, ActivityType] = {
    a.key: a for a in [
        # ── Transport ─────────────────────────────────────────────────────
        ActivityType("car_petrol_km",   "Car (petrol) — km driven",          "transport", "km",    0.192, "🚗"),
        ActivityType("car_diesel_km",   "Car (diesel) — km driven",          "transport", "km",    0.171, "🚗"),
        ActivityType("car_electric_km", "Car (electric) — km driven",        "transport", "km",    0.053, "🔌"),
        ActivityType("bus_km",          "Bus — km travelled",                "transport", "km",    0.105, "🚌"),
        ActivityType("train_km",        "Train — km travelled",              "transport", "km",    0.041, "🚆"),
        ActivityType("flight_short_km", "Flight (short-haul) — km flown",   "transport", "km",    0.255, "✈️"),
        ActivityType("flight_long_km",  "Flight (long-haul) — km flown",    "transport", "km",    0.150, "✈️"),
        ActivityType("bike_walk_km",    "Bike / walk — km travelled",        "transport", "km",    0.0,   "🚲"),

        # ── Energy ────────────────────────────────────────────────────────
        ActivityType("electricity_kwh", "Electricity used — kWh",            "energy",    "kWh",  0.475, "💡"),
        ActivityType("natural_gas_kwh", "Natural gas used — kWh",            "energy",    "kWh",  0.203, "🔥"),
        ActivityType("lpg_kg",          "LPG cylinder — kg used",            "energy",    "kg",   2.983, "🛢️"),

        # ── Food (per meal/serving, average footprint) ───────────────────
        ActivityType("meal_beef",       "Meal with beef",                    "food",     "meal",  6.61,  "🥩"),
        ActivityType("meal_chicken",    "Meal with chicken",                 "food",     "meal",  1.57,  "🍗"),
        ActivityType("meal_vegetarian", "Vegetarian meal",                   "food",     "meal",  0.89,  "🥗"),
        ActivityType("meal_vegan",      "Vegan meal",                        "food",     "meal",  0.51,  "🌱"),
        ActivityType("dairy_litre",     "Dairy milk — litre",                "food",     "litre", 1.39,  "🥛"),

        # ── Waste ─────────────────────────────────────────────────────────
        ActivityType("waste_landfill_kg", "Household waste to landfill — kg", "waste",  "kg",    0.467, "🗑️"),
        ActivityType("waste_recycled_kg", "Recycled waste — kg",              "waste",  "kg",    0.021, "♻️"),
    ]
}


def get_activity(key: str) -> Optional[ActivityType]:
    """
    Look up an activity type by its unique key.

    Args:
        key: The machine-readable activity identifier (e.g. 'car_petrol_km').

    Returns:
        The matching ActivityType, or None if the key is not recognised.
    """
    return ACTIVITY_TYPES.get(key)


def list_activities() -> list[ActivityType]:
    """
    Return all registered activity types in insertion order.

    Returns:
        List of all ActivityType instances available for logging.
    """
    return list(ACTIVITY_TYPES.values())
