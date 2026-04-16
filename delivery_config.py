# delivery_config.py
from datetime import date
from pricing_engine import (
    SIMPLE_RATE, SIMPLE_LOAD_COST,
    SINGLE_RATE, SINGLE_LOAD_COST,
    DOUBLE_RATE, DOUBLE_LOAD_COST,
    BULK_RATE, BULK_LOAD_COST,
    BULK_PLUS_RATE, BULK_PLUS_LOAD_COST,
)

# ── Christmas Tree seasonal availability ──────────────────────────────────────
# Christmas tree delivery types appear automatically between Nov 10 and Dec 24.
# To force them on year-round (e.g. for testing), set FORCE_CHRISTMAS_TREES = True.
FORCE_CHRISTMAS_TREES = False

def _christmas_season():
    today = date.today()
    start = date(today.year, 11, 10)
    end   = date(today.year, 12, 24)
    return FORCE_CHRISTMAS_TREES or (start <= today <= end)

# ── Delivery type definitions ─────────────────────────────────────────────────
# Minimums are set to cover a short local trip + loading labor at the calculated rate.
_BASE_DELIVERY_TYPES = {
    "Single": {
        "frankfort_minimum": 42,
        "lexington_minimum": 50,
        "rate_per_mile": SINGLE_RATE,
        "load_cost": SINGLE_LOAD_COST,
        "allows_to_the_hole": True,
        "pricing_type": "standard",
    },
    "Double": {
        "frankfort_minimum": 67,
        "lexington_minimum": 80,
        "rate_per_mile": DOUBLE_RATE,
        "load_cost": DOUBLE_LOAD_COST,
        "allows_to_the_hole": True,
        "pricing_type": "standard",
    },
    "Bulk": {
        "frankfort_minimum": 56,
        "lexington_minimum": 65,
        "rate_per_mile": BULK_RATE,
        "load_cost": BULK_LOAD_COST,
        "allows_to_the_hole": True,
        "pricing_type": "standard",
    },
    "Bulk Plus": {
        "frankfort_minimum": 81,
        "lexington_minimum": 95,
        "rate_per_mile": BULK_PLUS_RATE,
        "load_cost": BULK_PLUS_LOAD_COST,
        "allows_to_the_hole": True,
        "pricing_type": "standard",
    },
    "Simple": {
        "frankfort_price": 8.00,
        "lexington_price": 30.00,
        "allows_to_the_hole": False,
        "pricing_type": "simple",
    },
}

_CHRISTMAS_DELIVERY_TYPES = {
    "Christmas Tree (7-8ft and smaller)": {
        "minimum": 35,
        "allows_to_the_hole": False,
        "pricing_type": "christmas_tree_small",
        "rate_per_mile": 1.20,
        "setup_fee": 16.50,
    },
    "Christmas Tree (8-9ft and larger)": {
        "minimum": 55,
        "allows_to_the_hole": False,
        "pricing_type": "christmas_tree_large",
        "first_20_miles_rate": 1.60,
        "after_20_miles_rate": 0.75,
        "setup_fee": 30.50,
    },
}

def get_delivery_types():
    types = dict(_BASE_DELIVERY_TYPES)
    if _christmas_season():
        types.update(_CHRISTMAS_DELIVERY_TYPES)
    return types

DELIVERY_TYPES = get_delivery_types()

# ── Delivery type descriptions (shown as reference chart in the app) ───────────
DELIVERY_TYPE_DESCRIPTIONS = {
    "Single": [
        "Container Plants: 1 gal (max 30), 3 gal (max 15), 5–7 gal (max 6)",
        "Bagged Hardgoods: max 20 bags",
        "B&B Plants: 1.25\" (max 10), 1.5\" (max 4)",
    ],
    "Double": [
        "Container Plants: 1 gal (max 50), 3 gal (max 35), 5–7 gal (max 15), 10+ gal (max 5)",
        "Bagged Hardgoods: max 120 bags",
        "B&B Plants: 1.25\" (max 18), 1.5\" (max 15), 1.75\" (max 10), 2\" (max 5)",
        "Statues & Fountains: Price is an estimate — call Hugo (502-892-9605) to confirm",
    ],
    "Bulk": [
        "Compost (max 6 scoops), Top Soil (max 7 scoops), Mulch (max 10 scoops)",
        "⚠️ Scoops WILL mix. If materials must stay separate, each type needs its own delivery.",
    ],
    "Bulk Plus": [
        "Scoops of bulk material AND plants/other items combined (e.g. 1 scoop top soil + 3 trees)",
    ],
    "Simple": [
        "Floral arrangements and gift items only — funeral home deliveries",
        "Available within Frankfort or Lexington city limits only",
    ],
    "Christmas Tree (7-8ft and smaller)": [
        "Seasonal delivery for trees 7–8ft and smaller",
    ],
    "Christmas Tree (8-9ft and larger)": [
        "Seasonal delivery for trees 8–9ft and larger",
    ],
}

# ── Other config ──────────────────────────────────────────────────────────────
TO_THE_HOLE_FEE = 20.00

ORIGIN_ADDRESSES = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_delivery_type_names():
    return list(get_delivery_types().keys())

def is_to_the_hole_allowed(delivery_type):
    return get_delivery_types()[delivery_type].get("allows_to_the_hole", False)

def calculate_christmas_tree_small_price(roundtrip_mileage):
    config = _CHRISTMAS_DELIVERY_TYPES["Christmas Tree (7-8ft and smaller)"]
    price = (roundtrip_mileage * config["rate_per_mile"]) + config["setup_fee"]
    return max(price, config["minimum"])

def calculate_christmas_tree_large_price(roundtrip_mileage):
    config = _CHRISTMAS_DELIVERY_TYPES["Christmas Tree (8-9ft and larger)"]
    if roundtrip_mileage <= 20:
        mileage_cost = roundtrip_mileage * config["first_20_miles_rate"]
    else:
        mileage_cost = (20 * config["first_20_miles_rate"]) + ((roundtrip_mileage - 20) * config["after_20_miles_rate"])
    return max(mileage_cost + config["setup_fee"], config["minimum"])

def calculate_standard_price(roundtrip_mileage, delivery_type, origin_name):
    config = get_delivery_types()[delivery_type]
    base_fee = config["rate_per_mile"] * roundtrip_mileage + config.get("load_cost", 0)
    min_fee = config[f"{origin_name.lower()}_minimum"]
    return max(base_fee, min_fee)
