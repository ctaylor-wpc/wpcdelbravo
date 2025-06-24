import streamlit as st
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta, date
import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

st.set_page_config(page_title="Delivery Quote Calculator", layout="centered")

# Custom styling
st.markdown("""
    <style>
        body {
            background-color: #FBF8F6;
            color: #5e5e5e;
        }
        .stButton>button {
            background-color: #545A35;
            color: white;
        }
    </style>
""", unsafe_allow_html=True)

# Google Maps API Key
GOOGLE_MAPS_API_KEY = st.secrets["api"]["google_maps_api_key"]

# Email config
SMTP_SERVER = st.secrets["email"]["smtp_server"]
SMTP_PORT = st.secrets["email"]["smtp_port"]
SENDER_EMAIL = st.secrets["email"]["sender_email"]
SENDER_PASSWORD = st.secrets["email"]["sender_password"]
NOTIFY_EMAIL = st.secrets["email"]["notify_email"]

# Google Calendar setup
SERVICE_ACCOUNT_INFO = json.loads(st.secrets["gcp"]["service_account_json"])
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = "deliveries@wilsonnurseriesky.com"

credentials = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES)
calendar_service = build("calendar", "v3", credentials=credentials)

# App state
if "quote_shown" not in st.session_state:
    st.session_state.quote_shown = False
if "reset" not in st.session_state:
    st.session_state.reset = False

# Reset handler
def reset_app():
    for key in st.session_state.keys():
        del st.session_state[key]
    st.experimental_rerun()

# Step 1 – Quote calculator
st.header("Step 1: Delivery Quote")

with st.form(key="quote_form"):
    customer_address = st.text_input("Customer Address")
    origin_choice = st.radio("Select Delivery Origin", ["Frankfort", "Lexington"])
    delivery_type = st.selectbox("Select Delivery Type", ["Simple", "Single", "Double", "Bulk", "Bulk Plus"])
    add_on_option = st.checkbox("To-The-Hole")
    submit_quote = st.form_submit_button("Calculate Quote")

origin_address = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509"
}[origin_choice]

# Get roundtrip mileage from Google Maps
@st.cache_data(show_spinner=False)
def get_distance_miles(origin, destination):
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={origin}&destinations={destination}&key={GOOGLE_MAPS_API_KEY}"
    response = requests.get(url)
    data = response.json()
    if data["status"] != "OK" or data["rows"][0]["elements"][0]["status"] != "OK":
        return None
    meters = data["rows"][0]["elements"][0]["distance"]["value"]
    return round(meters / 1609.34, 2)

def calculate_delivery_fee(origin, destination, delivery_type, add_on):
    if delivery_type == "Simple":
        if "Frankfort" in destination:
            return 0, 8.00
        elif "Lexington" in destination:
            return 0, 30.00
        else:
            return None, None

    mileage = get_distance_miles(origin, destination)
    if mileage is None:
        return None, None

    rate_lookup = {
        "Single": (45, 50, 2.00),
        "Double": (60, 70, 2.95),
        "Bulk": (55, 65, 2.65),
        "Bulk Plus": (65, 80, 3.15)
    }
    frank_min, lex_min, rate = rate_lookup[delivery_type]
    base_fee = round(rate * mileage * 2, 2)
    min_fee = frank_min if origin_choice == "Frankfort" else lex_min
    final_fee = max(base_fee, min_fee)
    if add_on:
        final_fee += 20
    return mileage * 2, round(final_fee, 2)

if submit_quote and customer_address:
    mileage, quote = calculate_delivery_fee(origin_address, customer_address, delivery_type, add_on_option)
    if quote is None:
        st.error("Unable to calculate quote for this address.")
    else:
        st.session_state.quote_shown = True
        st.session_state.mileage = mileage
        st.session_state.quote = quote

if st.session_state.get("quote_shown"):
    st.success(f"Delivery Quote: ${st.session_state.quote:.2f} (Roundtrip: {st.session_state.mileage} miles)")

    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name")
    customer_phone = st.text_input("Phone Number")
    customer_notes = st.text_area("Please list plants, materials, gate codes, or other notes")

    st.header("Step 3: Scheduling")
    today = date.today()
    available_days = [today + timedelta(days=i) for i in range(1, 30) if (today + timedelta(days=i)).weekday() < 5]
    preferred_date = st.date_input("Preferred Delivery Date", min_value=today + timedelta(days=1))
    if preferred_date.weekday() >= 5:
        st.warning("Weekends are not available. Please select a weekday.")

    weekday_labels = {
        0: ("Frankfort Area", "#545A35"),
        1: ("Frankfort Area", "#545A35"),
        2: ("Frankfort Area", "#545A35"),
        3: ("Lexington Area", "#9B6554"),
        4: ("Lexington Area", "#9B6554")
    }
    label, color = weekday_labels.get(preferred_date.weekday(), ("", ""))
    if label:
        st.markdown(f"<span style='color:{color}; font-weight:bold'>{label}</span>", unsafe_allow_html=True)

    time_pref = st.radio("Preferred Delivery Time", ["Doesn't Matter", "Morning", "Afternoon"], index=0)

    if st.button("Send Confirmation Email"):

        def create_google_calendar_event(summary, description, date_str, time_pref):
            if time_pref == "Morning":
                start_time = "09:00:00"
            elif time_pref == "Afternoon":
                start_time = "13:00:00"
            else:
                start_time = "12:00:00"
            start = f"{date_str}T{start_time}-04:00"
            end = f"{date_str}T{(datetime.strptime(start_time, '%H:%M:%S') + timedelta(hours=1)).strftime('%H:%M:%S')}-04:00"

            event = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start, "timeZone": "America/New_York"},
                "end": {"dateTime": end, "timeZone": "America/New_York"},
            }
            created = calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            return created.get("htmlLink")

        def create_pdf():
            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)
            p.drawString(100, 750, f"Customer: {customer_name}")
            p.drawString(100, 735, f"Phone: {customer_phone}")
            p.drawString(100, 720, f"Address: {customer_address}")
            p.drawString(100, 705, f"Quote: ${st.session_state.quote:.2f}")
            p.drawString(100, 690, f"Preferred Date: {preferred_date.strftime('%A, %m/%d/%Y')}")
            p.drawString(100, 675, f"Preferred Time: {time_pref}")
            p.drawString(100, 660, f"Notes: {customer_notes}")
            p.save()
            buffer.seek(0)
            return buffer

        description = f"Quote: ${st.session_state.quote:.2f}\nName: {customer_name}\nPhone: {customer_phone}\nAddress: {customer_address}\nNotes: {customer_notes}"
        event_link = create_google_calendar_event(
            summary=f"Delivery for {customer_name}",
            description=description,
            date_str=preferred_date.strftime('%Y-%m-%d'),
            time_pref=time_pref
        )

        pdf_buffer = create_pdf()

        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = NOTIFY_EMAIL
        msg["Subject"] = f"Delivery Scheduled: {customer_name}"
        msg.attach(MIMEText(description + f"\n\nCalendar Event: {event_link}", "plain"))

        part = MIMEApplication(pdf_buffer.read(), Name="delivery_receipt.pdf")
        part['Content-Disposition'] = 'attachment; filename="delivery_receipt.pdf"'
        msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, NOTIFY_EMAIL, msg.as_string())

        st.success("Delivery Scheduled!")
        if st.button("Schedule another delivery"):
            reset_app()
