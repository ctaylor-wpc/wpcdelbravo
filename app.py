import streamlit as st
import requests
import smtplib
from email.mime.text import MIMEText

# -------------------- CONFIGURATION -------------------- #

API_KEY = st.secrets["api"]["google_maps_api_key"]
EMAIL_CONFIG = st.secrets["email"]

FRANKFORT_ADDRESS = "3690 East West Connector, Frankfort, KY 40601"
LEXINGTON_ADDRESS = "2700 Palumbo Drive, Lexington, KY 40509"

# -------------------- FUNCTIONS -------------------- #

def get_distance_miles(origin, destination):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": destination,
        "key": API_KEY,
        "units": "imperial"
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            st.error(f"Google Maps API request failed with status code {response.status_code}.")
            return None

        data = response.json()

        if data["status"] != "OK":
            st.error(f"Google Maps API error: {data.get('error_message', 'Unknown error')}")
            return None

        element_status = data["rows"][0]["elements"][0]["status"]
        if element_status != "OK":
            st.error(f"Could not calculate distance: {element_status}")
            return None

        distance_text = data["rows"][0]["elements"][0]["distance"]["text"]
        miles = float(distance_text.replace(" mi", "").replace(",", ""))
        return miles

    except Exception as e:
        st.error(f"Unexpected error during distance lookup: {e}")
        return None

def calculate_delivery_fee(origin, destination, delivery_type, add_on):
    city_simple_lookup = {
        "Frankfort": 8,
        "Lexington": 30
    }

    one_way_miles = get_distance_miles(origin, destination)

    if one_way_miles is None:
        return None, None

    round_trip_miles = one_way_miles * 2

    fee = None
    min_fee = None

    if delivery_type == "Simple":
        if "frankfort" in destination.lower():
            fee = city_simple_lookup["Frankfort"]
        elif "lexington" in destination.lower():
            fee = city_simple_lookup["Lexington"]
        else:
            return None, None  # Simple delivery not allowed outside these cities
    else:
        rules = {
            "Single": {"rate": 2.00, "min": 45 if origin == FRANKFORT_ADDRESS else 50},
            "Double": {"rate": 2.95, "min": 60 if origin == FRANKFORT_ADDRESS else 70},
            "Bulk": {"rate": 2.65, "min": 55 if origin == FRANKFORT_ADDRESS else 65},
            "Bulk Plus": {"rate": 3.15, "min": 65 if origin == FRANKFORT_ADDRESS else 80},
        }
        rule = rules[delivery_type]
        fee = round(rule["rate"] * round_trip_miles, 2)
        fee = max(fee, rule["min"])

    if add_on == "To-The-Hole":
        fee += 10  # Flat add-on

    return round_trip_miles, fee

def send_email(data):
    msg = MIMEText(data)
    msg["Subject"] = "New Delivery Scheduled"
    msg["From"] = EMAIL_CONFIG["sender_email"]
    msg["To"] = EMAIL_CONFIG["notify_email"]

    try:
        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.send_message(msg)
    except Exception as e:
        st.error(f"Email failed to send: {e}")

# -------------------- UI -------------------- #

st.title("Wilson Plant Co. Delivery Quote Tool")

# Step 1 & Step 2 combined flow
st.header("Step 1 & 2: Delivery Quote + Customer Intake")

with st.form("quote_and_intake_form"):
    # Step 1 inputs
    customer_address = st.text_input("Customer's Full Address")
    delivery_origin_label = st.selectbox("Select Delivery Origin", ["Frankfort Store", "Lexington Store"])
    delivery_origin = FRANKFORT_ADDRESS if delivery_origin_label == "Frankfort Store" else LEXINGTON_ADDRESS
    delivery_type = st.selectbox("Select Delivery Type", ["Simple", "Single", "Double", "Bulk", "Bulk Plus"])
    add_on = st.selectbox("Add-On Options (optional)", ["None", "To-The-Hole"])

    # Step 2 inputs (intake)
    customer_name = st.text_input("Customer Name")
    phone = st.text_input("Phone Number")
    notes = st.text_area("Gate codes, location notes, or special instructions")

    quote_requested = st.form_submit_button("Calculate Quote")

if quote_requested:
    add_on_option = add_on if add_on != "None" else None
    mileage, quote = calculate_delivery_fee(delivery_origin, customer_address, delivery_type, add_on_option)

    if quote is not None:
        st.success(f"Estimated delivery cost: **${quote:.2f}** for ~{mileage:.1f} miles round-trip")

        # Store intake info for later steps
        st.session_state["customer_name"] = customer_name
        st.session_state["phone"] = phone
        st.session_state["notes"] = notes
        st.session_state["quote"] = quote
        st.session_state["mileage"] = mileage
        st.session_state["delivery_origin_label"] = delivery_origin_label
        st.session_state["customer_address"] = customer_address
        st.session_state["delivery_type"] = delivery_type
        st.session_state["add_on_option"] = add_on_option

    else:
        st.error("Could not calculate delivery. Please check the address or delivery type.")

# Only show Step 3 & 4 if quote calculation succeeded
if quote_requested and "quote" in st.session_state:
    # Step 3: Scheduling
    st.header("Step 3: Schedule Delivery")
    st.warning("Google Calendar integration coming soon. Please select manually.")
    delivery_date = st.date_input("Preferred Delivery Date")
    delivery_time = st.time_input("Preferred Delivery Time")

    # Step 4: Send Notification
    st.header("Step 4: Send Notification")
    if st.button("Send Confirmation Email"):
        full_message = f"""
        NEW DELIVERY BOOKED:

        Name: {st.session_state['customer_name']}
        Phone: {st.session_state['phone']}
        Address: {st.session_state['customer_address']}
        Origin: {st.session_state['delivery_origin_label']}
        Type: {st.session_state['delivery_type']}
        Add-On: {st.session_state['add_on_option'] or "None"}
        Quote: ${st.session_state['quote']:.2f}
        Distance: {st.session_state['mileage']:.1f} miles roundtrip
        Notes: {st.session_state['notes']}

        Scheduled for: {delivery_date} at {delivery_time}
        """
        send_email(full_message)
        st.success("Confirmation email sent!")