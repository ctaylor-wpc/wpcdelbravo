import streamlit as st
import requests
import smtplib
import json
import datetime
from email.mime.text import MIMEText
from google.oauth2 import service_account
from googleapiclient.discovery import build

# -------------------- CONFIGURATION -------------------- #

API_KEY = st.secrets["api"]["google_maps_api_key"]
EMAIL_CONFIG = st.secrets["email"]
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
CALENDAR_ID = 'deliveries@wilsonnurseriesky.com'

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
            st.error(f"Google Maps API request failed ({response.status_code})")
            return None
        data = response.json()
        if data["status"] != "OK":
            st.error(f"Google Maps API error: {data.get('error_message', 'Unknown error')}")
            return None
        if data["rows"][0]["elements"][0]["status"] != "OK":
            st.error("Could not calculate distance for the given address.")
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

    if delivery_type == "Simple":
        if "frankfort" in destination.lower():
            fee = city_simple_lookup["Frankfort"]
        elif "lexington" in destination.lower():
            fee = city_simple_lookup["Lexington"]
        else:
            return None, None
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
        fee += 10

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

def create_google_calendar_event(summary, description, date, time_pref):
    service_info = json.loads(st.secrets["gcp"]["service_account_json"])
    creds = service_account.Credentials.from_service_account_info(service_info, scopes=SCOPES)
    service = build("calendar", "v3", credentials=creds)

    if time_pref == "AM":
        hour = 9
    elif time_pref == "PM":
        hour = 13
    else:
        hour = 12

    start_dt = datetime.datetime.combine(date, datetime.time(hour, 0))
    end_dt = start_dt + datetime.timedelta(hours=1)

    event = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/New_York'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/New_York'},
    }

    created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    return created_event.get("htmlLink")

# -------------------- UI -------------------- #

st.title("📦 Wilson Plant Co. Delivery Quote Tool")

if st.session_state.get("delivery_complete"):
    st.balloons()
    st.header("✅ Delivery Scheduled!")

    if st.button("Would you like to complete another delivery?"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

else:
    st.header("Step 1: Delivery Quote")
    with st.form("quote_form"):
        customer_address = st.text_input("Customer's Full Address")
        delivery_origin_label = st.selectbox("Select Delivery Origin", ["Frankfort Store", "Lexington Store"])
        delivery_origin = FRANKFORT_ADDRESS if delivery_origin_label == "Frankfort Store" else LEXINGTON_ADDRESS
        delivery_type = st.selectbox("Select Delivery Type", ["Simple", "Single", "Double", "Bulk", "Bulk Plus"])
        add_on = st.selectbox("Add-On Options (optional)", ["None", "To-The-Hole"])
        quote_submit = st.form_submit_button("Calculate Quote")

    if quote_submit:
        add_on_option = add_on if add_on != "None" else None
        mileage, quote = calculate_delivery_fee(delivery_origin, customer_address, delivery_type, add_on_option)

        if quote is not None:
            st.success(f"Estimated delivery cost: **${quote:.2f}** for ~{mileage:.1f} miles round-trip")

            # Step 2: Customer Details & Scheduling
            st.header("Step 2: Customer Details + Scheduling")
            with st.form("intake_form"):
                customer_name = st.text_input("Customer Name")
                phone = st.text_input("Phone Number")
                notes = st.text_area("Gate codes, location notes, or special instructions")

                st.markdown("### Schedule Delivery")
                delivery_date = st.date_input("Preferred Delivery Date")
                formatted_date = delivery_date.strftime("%A %m/%d/%Y")
                delivery_time_pref = st.selectbox(
                    "Preferred Delivery Time",
                    ["AM", "PM", "Doesn’t Matter"]
                )

                confirm = st.form_submit_button("Send Confirmation Email")

            if confirm:
                full_message = f"""
                NEW DELIVERY BOOKED:

                Name: {customer_name}
                Phone: {phone}
                Address: {customer_address}
                Origin: {delivery_origin_label}
                Type: {delivery_type}
                Add-On: {add_on_option or "None"}
                Quote: ${quote:.2f}
                Distance: {mileage:.1f} miles roundtrip
                Notes: {notes}

                Scheduled for: {formatted_date} — {delivery_time_pref}
                """

                send_email(full_message)
                event_link = create_google_calendar_event(
                    summary=f"Delivery for {customer_name}",
                    description=full_message,
                    date=delivery_date,
                    time_pref=delivery_time_pref
                )

                st.session_state["delivery_complete"] = True
                st.success("✅ Confirmation email sent and event added to calendar!")
                st.markdown(f"🗓 [View Calendar Event]({event_link})", unsafe_allow_html=True)
                st.rerun()
        else:
            st.error("Could not calculate delivery. Please check the address or delivery type.")
