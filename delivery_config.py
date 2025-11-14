# delivery_config.py
# This file contains all delivery types, pricing, and minimums
# Edit this file to update pricing without touching the main app

import math

# Delivery type configurations
# Format: "Type Name": configuration dictionary
DELIVERY_TYPES = {
    "Single": {
        "frankfort_minimum": 45,
        "lexington_minimum": 50,
        "rate_per_mile": 2.00,
        "allows_to_the_hole": True,
        "pricing_type": "standard"
    },
    "Double": {
        "frankfort_minimum": 60,
        "lexington_minimum": 70,
        "rate_per_mile": 2.95,
        "allows_to_the_hole": True,
        "pricing_type": "standard"
    },
    "Bulk": {
        "frankfort_minimum": 55,
        "lexington_minimum": 65,
        "rate_per_mile": 2.65,
        "allows_to_the_hole": True,
        "pricing_type": "standard"
    },
    "Bulk Plus": {
        "frankfort_minimum": 65,
        "lexington_minimum": 80,
        "rate_per_mile": 3.05,
        "allows_to_the_hole": True,
        "pricing_type": "standard"
    },
    "Christmas Tree (7-8ft and smaller)": {
        "minimum": 35,
        "allows_to_the_hole": False,
        "pricing_type": "christmas_tree_small",
        "rate_per_mile": 1.20,
        "setup_fee": 16.50
    },
    "Christmas Tree (8-9ft and larger)": {
        "minimum": 55,
        "allows_to_the_hole": False,
        "pricing_type": "christmas_tree_large",
        "first_20_miles_rate": 1.60,
        "after_20_miles_rate": 0.75,
        "setup_fee": 30.50
    },
    "Simple": {
        # Simple type uses fixed pricing by city, not mileage-based
        "frankfort_price": 8.00,
        "lexington_price": 30.00,
        "allows_to_the_hole": False,
        "pricing_type": "simple"
    }
}

# To-The-Hole add-on pricing
TO_THE_HOLE_FEE = 20.00

# Origin addresses
ORIGIN_ADDRESSES = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509"
}

# Helper function to get delivery type names for dropdown
def get_delivery_type_names():
    return list(DELIVERY_TYPES.keys())

# Helper function to validate to-the-hole option
def is_to_the_hole_allowed(delivery_type):
    return DELIVERY_TYPES[delivery_type].get("allows_to_the_hole", False)

# Pricing calculation functions
def calculate_christmas_tree_small_price(roundtrip_mileage):
    """
    Calculate price for Christmas Tree (7-8ft and smaller)
    Formula: (miles × $0.90) + $25 setup fee
    Minimum: $35
    
    Examples:
    - 10 miles: $34.00 → $35 (minimum)
    - 20 miles: $43.00
    - 40 miles: $61.00
    """
    config = DELIVERY_TYPES["Christmas Tree (7-8ft and smaller)"]
    
    if roundtrip_mileage <= 0:
        return config["minimum"]
    
    price = (roundtrip_mileage * config["rate_per_mile"]) + config["setup_fee"]
    return max(price, config["minimum"])

def calculate_christmas_tree_large_price(roundtrip_mileage):
    """
    Calculate price for Christmas Tree (8-9ft and larger)
    Tiered pricing:
    - First 20 miles: $1.30/mile
    - Miles 21+: $0.65/mile
    - Setup fee: $58.50
    Minimum: $60
    
    Examples:
    - 10 miles: (10 × $1.30) + $58.50 = $71.50
    - 20 miles: (20 × $1.30) + $58.50 = $84.50
    - 40 miles: (20 × $1.30) + (20 × $0.65) + $58.50 = $97.50
    """
    config = DELIVERY_TYPES["Christmas Tree (8-9ft and larger)"]
    
    if roundtrip_mileage <= 0:
        return config["minimum"]
    
    # Calculate tiered mileage cost
    if roundtrip_mileage <= 20:
        mileage_cost = roundtrip_mileage * config["first_20_miles_rate"]
    else:
        # First 20 miles at full rate
        first_20_cost = 20 * config["first_20_miles_rate"]
        # Remaining miles at reduced rate
        remaining_miles = roundtrip_mileage - 20
        remaining_cost = remaining_miles * config["after_20_miles_rate"]
        mileage_cost = first_20_cost + remaining_cost
    
    price = mileage_cost + config["setup_fee"]
    return max(price, config["minimum"])

def calculate_standard_price(roundtrip_mileage, delivery_type, origin_name):
    """
    Calculate price for standard delivery types (Single, Double, Bulk, Bulk Plus)
    Formula: rate_per_mile * roundtrip_mileage OR minimum (whichever is higher)
    """
    config = DELIVERY_TYPES[delivery_type]
    base_fee = config["rate_per_mile"] * roundtrip_mileage
    min_fee = config[f"{origin_name.lower()}_minimum"]
    return max(base_fee, min_fee)
