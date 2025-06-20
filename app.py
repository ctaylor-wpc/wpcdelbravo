import streamlit as st
import requests
import datetime
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------- SETUP ---------------------
st.set_page_config(page_title="Delivery Quote & Scheduler")
st.title("Wilson Plant Co Delivery Scheduler")

# Constants for locations
STORE_ADDRESSES = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509"
}

DELIVERY_TYPES = {
    "Simple": {"Frankfort": 8, "Lexington": 30},
    "Single": {"Frankfort": (2.00, 45), "Lexington": (2.00, 50)},
    "Double": {"Frankfort": (2.95, 60), "Lexington": (2.95, 70)},
    "Bulk": {"Frankfort": (2.65, 55), "Lexington": (2.65, 65)},
    "Bulk Plus": {"Frankfort": (3.15, 65), "Lexington": (3.15, 80)},
}

ADD_ON_FEE = 20  # Flat fee for "To-The-Hole"

# --------------------- FUNCTION: Calculate Distance ---------------------
def get_distance_miles(origin, destination):
    api_key = st.secrets["api"]["google_maps_api_key"]
    endpoint = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": destination,
        "units": "imperial",
        "key": api_key
    }
    response = requests.get(endpoint, params=params)
    data = response.json()

    try:
        distance_text = data["rows"][0]["elements"][0]["distance"]["text"]
        distance_miles = float(distance_text.replace(" mi", ""))
        return distance_miles
    except:
        st.error("❌ Error: Google Maps API failed to calculate distance.")
        st.stop()

# --------------------- FUNCTION: Calculate Fee ---------------------
def calculate_delivery_fee(origin_store, destination, delivery_type, add_on):
    origin_address = STORE_ADDRESSES[origin_store]
    if delivery_type == "Simple":
        if "Frankfort" in destination:
            return 0, DELIVERY_TYPES["Simple"]["Frankfort"]
        elif "Lexington" in destination:
            return 0, DELIVERY_TYPES["Simple"]["Lexington"]
        else:
            st.error("Simple delivery not available for this location.")
            st.stop()

    rate, minimum = DELIVERY_TYPES[delivery_type][origin_store]
    miles = get_distance_miles(origin_address, destination)
    roundtrip = miles * 2
    fee = max(roundtrip * rate, minimum)
    if add_on:
        fee += ADD_ON_FEE
    return roundtrip, round(fee, 2)

# --------------------- FUNCTION: Send Email ---------------------
def send_email(message):
    config = st.secrets["email"]
    msg = MIMEMultipart()
    msg["From"] = config["sender_email"]
    msg["To"] = config["notify_email"]
    msg["Subject"] = "New Delivery Scheduled"
    msg.attach(MIMEText(message, "plain"))

    with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
        server.starttls()
        server.login(config["sender_email"], config["sender_password"])
        server.sendmail(config["sender_email"], config["notify_email"], msg.as_string())

# --------------------- FUNCTION: Create Calendar Event ---------------------
def create_google_calendar_event(summary, description, date, time_pref):
    credentials_info = json.loads(st.secrets["gcp"]["service_account_json"])
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )

    service = build("calendar", "v3", credentials=credentials)
    calendar_id = "deliveries@wilsonnurseriesky.com"

    hour = 9 if time_pref == "AM" else 13 if time_pref == "PM" else 11
    start_time = datetime.datetime.combine(date, datetime.time(hour, 0))
    end_time = start_time + datetime.timedelta(hours=1)

    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_time.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "America/New_York"},
    }

    created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
    return created_event.get("htmlLink")

# --------------------- UI: Step 1 ---------------------
st.header("Step 1: Quote")
with st.form("quote_form"):
    customer_address = st.text_input("Customer Address")
    delivery_origin = st.selectbox("Delivery Origin", list(STORE_ADDRESSES.keys()))
    delivery_type = st.selectbox("Delivery Type", list(DELIVERY_TYPES.keys()))
    add_on_option = st.checkbox("Add On: To-The-Hole")
    submit_quote = st.form_submit_button("Calculate Quote")

if submit_quote and customer_address:
    mileage, quote = calculate_delivery_fee(delivery_origin, customer_address, delivery_type, add_on_option)
    st.success(f"Calculated delivery cost: **${quote}** ({round(mileage, 1)} round-trip miles)")

    # --------------------- UI: Step 2 + 3 ---------------------
    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name")
    customer_phone = st.text_input("Phone Number")
    gate_codes = st.text_area("Gate Codes / Delivery Notes")

    st.header("Step 3: Scheduling")
    preferred_date = st.date_input("Preferred Delivery Date")
    weekday = preferred_date.strftime("%A")
    formatted_date = preferred_date.strftime("%m/%d/%Y")
    st.write(f"Selected Date: **{weekday} {formatted_date}**")
    time_pref = st.selectbox("Preferred Delivery Time", ["AM", "PM", "Doesn't Matter"])

    if st.button("Send Confirmation Email & Schedule"):
        full_message = f"""
        New Delivery Scheduled:

        Name: {customer_name}
        Phone: {customer_phone}
        Address: {customer_address}
        Gate Notes: {gate_codes}

        Quote: ${quote}
        Delivery Origin: {delivery_origin}
        Delivery Type: {delivery_type}
        Add-On: {add_on_option}

        Scheduled Date: {weekday} {formatted_date}
        Time Preference: {time_pref}
        """

        try:
            send_email(full_message)
            event_link = create_google_calendar_event(
                summary=f"Delivery for {customer_name}",
                description=full_message,
                date=preferred_date,
                time_pref=time_pref
            )
            st.success("Delivery Scheduled!")
            st.markdown(f"[📅 View on Calendar]({event_link})")
            if st.button("➕ Schedule Another Delivery"):
                st.experimental_rerun()
        except Exception as e:
            st.error("❌ Something went wrong.")
            st.write(e)
