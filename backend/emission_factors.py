"""
Emission factor reference data.

Factors are kg CO2e per unit, sourced from widely cited public datasets
(EPA, DEFRA, IPCC averages). These are reasonable estimates for an
awareness tool, not audit-grade figures — the UI labels them as such.

Keeping this as a single typed table (rather than scattered magic
numbers in route handlers) is what lets /api/activities validate input
and /api/insights compute suggestions from the same source of truth.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityType:
    key: str
    label: str
    category: str          # "transport" | "energy" | "food" | "waste"
    unit: str               # the unit the user enters a quantity in
    kg_co2e_per_unit: float
    icon: str                # emoji, used by frontend — keeps backend/frontend in sync on meaning


ACTIVITY_TYPES: dict[str, ActivityType] = {
    a.key: a for a in [
        # Transport
        ActivityType("car_petrol_km", "Car (petrol) — km driven", "transport", "km", 0.192, "🚗"),
        ActivityType("car_diesel_km", "Car (diesel) — km driven", "transport", "km", 0.171, "🚗"),
        ActivityType("car_electric_km", "Car (electric) — km driven", "transport", "km", 0.053, "🔌"),
        ActivityType("bus_km", "Bus — km travelled", "transport", "km", 0.105, "🚌"),
        ActivityType("train_km", "Train — km travelled", "transport", "km", 0.041, "🚆"),
        ActivityType("flight_short_km", "Flight (short-haul) — km flown", "transport", "km", 0.255, "✈️"),
        ActivityType("flight_long_km", "Flight (long-haul) — km flown", "transport", "km", 0.150, "✈️"),
        ActivityType("bike_walk_km", "Bike / walk — km travelled", "transport", "km", 0.0, "🚲"),

        # Energy
        ActivityType("electricity_kwh", "Electricity used — kWh", "energy", "kWh", 0.475, "💡"),
        ActivityType("natural_gas_kwh", "Natural gas used — kWh", "energy", "kWh", 0.203, "🔥"),
        ActivityType("lpg_kg", "LPG cylinder — kg used", "energy", "kg", 2.983, "🛢️"),

        # Food (per meal/serving, average footprint)
        ActivityType("meal_beef", "Meal with beef", "food", "meal", 6.61, "🥩"),
        ActivityType("meal_chicken", "Meal with chicken", "food", "meal", 1.57, "🍗"),
        ActivityType("meal_vegetarian", "Vegetarian meal", "food", "meal", 0.89, "🥗"),
        ActivityType("meal_vegan", "Vegan meal", "food", "meal", 0.51, "🌱"),
        ActivityType("dairy_litre", "Dairy milk — litre", "food", "litre", 1.39, "🥛"),

        # Waste
        ActivityType("waste_landfill_kg", "Household waste to landfill — kg", "waste", "kg", 0.467, "🗑️"),
        ActivityType("waste_recycled_kg", "Recycled waste — kg", "waste", "kg", 0.021, "♻️"),
    ]
}


def get_activity(key: str) -> ActivityType | None:
    return ACTIVITY_TYPES.get(key)


def list_activities() -> list[ActivityType]:
    return list(ACTIVITY_TYPES.values())
