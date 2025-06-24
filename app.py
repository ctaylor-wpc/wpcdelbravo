import streamlit as st
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Styling
st.set_page_config(page_title="Delivery Quote Tool", layout="centered")
st.markdown("""
    <style>
        body {
            background-color: #FBF8F6;
            color: #5e5e5e;
        }
        .stButton>button {
            background-color: #545A35;
            color: white;
            border-radius: 5px;
            height: 3em;
            width: 100%;
        }
        .stRadio>div>label {
            color: #5e5e5e;
        }
        .fc td.fc-day.fc-day-tue {
            background-color: #545A35 !important;
        }
        .fc td.fc-day.fc-day-wed {
            background-color: #9B6554 !important;
        }
    </style>
""", unsafe_allow_html=True)

# Constants
ORIGIN_ADDRESSES = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509"
}

# Delivery Pricing Rules
def calculate_delivery_fee(origin, destination, delivery_type, add_on):
    try:
        api_key = st.secrets["api"]["google_maps_api_key"]
        url = f"https://maps.googleapis.com/maps/api/distancematrix/json?units=imperial&origins={origin}&destinations={destination}&key={api_key}"
        response = requests.get(url)
        data = response.json()

        distance_text = data["rows"][0]["elements"][0]["distance"]["text"]
        distance = float(distance_text.replace(" mi", ""))
        round_trip_miles = round(distance * 2, 2)

        location = "Frankfort" if "Frankfort" in destination else "Lexington" if "Lexington" in destination else "Other"

        fee = 0
        if delivery_type == "Simple":
            fee = 8 if location == "Frankfort" else 30 if location == "Lexington" else None
        elif delivery_type == "Single":
            minimum = 45 if origin == ORIGIN_ADDRESSES["Frankfort"] else 50
            fee = max(minimum, round(2.00 * round_trip_miles, 2))
        elif delivery_type == "Double":
            minimum = 60 if origin == ORIGIN_ADDRESSES["Frankfort"] else 70
            fee = max(minimum, round(2.95 * round_trip_miles, 2))
        elif delivery_type == "Bulk":
            minimum = 55 if origin == ORIGIN_ADDRESSES["Frankfort"] else 65
            fee = max(minimum, round(2.65 * round_trip_miles, 2))
        elif delivery_type == "Bulk Plus":
            minimum = 65 if origin == ORIGIN_ADDRESSES["Frankfort"] else 80
            fee = max(minimum, round(3.15 * round_trip_miles, 2))

        if add_on == "To-The-Hole":
            fee += 15

        return round_trip_miles, fee

    except Exception as e:
        st.error("Failed to calculate delivery fee. Please check address and try again.")
        return 0, 0

# Create PDF confirmation

def generate_pdf(customer_name, customer_phone, customer_notes, quote, date, time):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.drawString(100, 750, f"Delivery Confirmation for {customer_name}")
    p.drawString(100, 730, f"Phone: {customer_phone}")
    p.drawString(100, 710, f"Scheduled Date: {date} {time}")
    p.drawString(100, 690, f"Delivery Notes: {customer_notes}")
    p.drawString(100, 670, f"Total Quote: ${quote:.2f}")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()

# Google Calendar event

def create_google_calendar_event(summary, description, date, time_pref):
    credentials_info = json.loads(st.secrets["gcp"]["service_account_json"])
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    service = build("calendar", "v3", credentials=credentials)

    calendar_id = "deliveries@wilsonnurseriesky.com"

    hour = 10 if time_pref == "Morning" else 14 if time_pref == "Afternoon" else 12
    event_start = datetime.combine(date, datetime.min.time()) + timedelta(hours=hour)
    event_end = event_start + timedelta(hours=1)

    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": event_start.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": event_end.isoformat(), "timeZone": "America/New_York"}
    }

    event_result = service.events().insert(calendarId=calendar_id, body=event).execute()
    return event_result.get("htmlLink")

# Email function

def send_email(to_email, subject, body, pdf_content):
    smtp_server = st.secrets["email"]["smtp_server"]
    smtp_port = st.secrets["email"]["smtp_port"]
    sender_email = st.secrets["email"]["sender_email"]
    password = st.secrets["email"]["sender_password"]

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))
    attachment = MIMEApplication(pdf_content, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename="confirmation.pdf")
    msg.attach(attachment)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(sender_email, password)
        server.send_message(msg)

# Main App UI
if "quote_submitted" not in st.session_state:
    st.session_state.quote_submitted = False

st.title("Wilson Plant Co. Delivery Quote Tool")

# Step 1: Quote Builder
st.header("Step 1: Delivery Quote")

customer_address = st.text_input("Customer Address")
origin_choice = st.radio("Sold From", list(ORIGIN_ADDRESSES.keys()), index=0)
delivery_origin = ORIGIN_ADDRESSES[origin_choice]
delivery_type = st.radio("Select Delivery Type", ["Simple", "Single", "Double", "Bulk", "Bulk Plus"], index=1)
add_on_option = st.checkbox("To-The-Hole")

if st.button("Calculate Quote"):
    mileage, quote = calculate_delivery_fee(delivery_origin, customer_address, delivery_type, "To-The-Hole" if add_on_option else None)
    if quote:
        st.success(f"Delivery Quote: ${quote:.2f} ({mileage} miles roundtrip)")
        st.session_state.quote_submitted = True

# Step 2 & 3 combined
if st.session_state.quote_submitted:
    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name")
    customer_phone = st.text_input("Customer Phone")
    customer_notes = st.text_area("Please list plants, materials, gate codes, or other notes")

    st.header("Step 3: Scheduling")
    preferred_date = st.date_input("Preferred Delivery Date", min_value=datetime.today())
    preferred_time = st.radio("Preferred Delivery Time", ["Doesn't Matter", "Morning", "Afternoon"], index=0)

    if st.button("Send Confirmation Email & Schedule Delivery"):
        pdf = generate_pdf(customer_name, customer_phone, customer_notes, quote, preferred_date.strftime("%A %m/%d/%Y"), preferred_time)
        event_link = create_google_calendar_event(
            summary=f"Delivery for {customer_name}",
            description=f"Phone: {customer_phone}\nNotes: {customer_notes}",
            date=preferred_date,
            time_pref=preferred_time
        )
        send_email(
            to_email=st.secrets["email"]["notify_email"],
            subject="New Delivery Scheduled",
            body=f"Customer: {customer_name}\nPhone: {customer_phone}\nQuote: ${quote:.2f}\nDate: {preferred_date.strftime('%A %m/%d/%Y')} {preferred_time}\nNotes: {customer_notes}\nCalendar: {event_link}",
            pdf_content=pdf
        )
        st.success("Delivery Scheduled!")
        if st.button("Schedule Another Delivery"):
            for key in st.session_state.keys():
                del st.session_state[key]
            st.experimental_rerun()
