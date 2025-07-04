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
import base64
from pdfrw import PdfObject
from pdfrw import PdfName
from pdfrw import PdfReader
from pdfrw import PdfWriter
from pdfrw import PageMerge
import fitz
from datetime import date
from datetime import datetime, timedelta
from googleapiclient.errors import HttpError


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
    customer_street = st.text_input("Street Address")
    customer_city = st.text_input("City")
    customer_zip = st.text_input("Zip Code")
    customer_address = f"{customer_street}, {customer_city}, KY {customer_zip}"
    origin_choice = st.radio("Select Delivery Origin", ["Frankfort", "Lexington"])
    delivery_type = st.selectbox("Select Delivery Type", ["Single", "Double", "Bulk", "Bulk Plus", "Simple"])
    add_on_option = st.checkbox("To-The-Hole")
    submit_quote = st.form_submit_button("Calculate Quote")

origin_address = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509"
}[origin_choice]

@st.cache_data(show_spinner=False)
def get_distance_miles(origin, destination):
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={origin}&destinations={destination}&key={GOOGLE_MAPS_API_KEY}"
    response = requests.get(url)
    data = response.json()
    if data["status"] != "OK" or data["rows"][0]["elements"][0]["status"] != "OK":
        return None
    meters = data["rows"][0]["elements"][0]["distance"]["value"]
    return round(meters / 1609.34, 2)

def calculate_delivery_fee(origin, destination, delivery_type, add_on, customer_city):
    mileage = get_distance_miles(origin, destination)
    if mileage is None:
        return None, None

    round_trip = mileage * 2

    if delivery_type == "Simple":
        city_clean = customer_city.strip().lower()
        if city_clean == "frankfort":
            return round_trip, 8.00
        elif city_clean == "lexington":
            return round_trip, 30.00
        else:
            return None, None
     
    if add_on and delivery_type not in ["Double", "Bulk Plus"]:
        return None, None

    rate_lookup = {
        "Single": (45, 50, 2.00),
        "Double": (60, 70, 2.95),
        "Bulk": (55, 65, 2.65),
        "Bulk Plus": (65, 80, 3.05)
    }
    frank_min, lex_min, rate = rate_lookup[delivery_type]
    base_fee = round(rate * round_trip, 2)
    min_fee = frank_min if origin_choice == "Frankfort" else lex_min
    final_fee = max(base_fee, min_fee)
    if add_on:
        final_fee += 20

    return round_trip, round(final_fee, 2)

if submit_quote and customer_address:
    mileage, quote = calculate_delivery_fee(origin_address, customer_address, delivery_type, add_on_option, customer_city)
    if quote is None:
        st.error("Unable to calculate quote. Check delivery type, address, & to-the-hole options.")
    else:
        st.session_state.quote_shown = True
        st.session_state.mileage = mileage
        st.session_state.quote = quote

if st.session_state.get("quote_shown"):
    st.success(f"Delivery Quote: ${st.session_state.quote:.2f} (Roundtrip: {st.session_state.mileage} miles)")

    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name")
    customer_phone = st.text_input("Phone Number")
    delivery_details = st.text_area("Please list all plants, materials, and items to be delivered")
    customer_notes = st.text_area("Delivery location, gate codes, or other notes")

    st.header("Step 3: Scheduling")
    cashier_initials = st.text_input("Your Initials")
    today = date.today()
    preferred_date = st.date_input("Preferred Delivery Date", min_value=today + timedelta(days=1))
    if preferred_date.weekday() >= 5:
        st.warning("Weekends are not available. Please select a weekday.")

    weekday_labels = {
        0: ("Frankfort Area", "#545A35"),
        1: ("Frankfort Area", "#545A35"),
        2: ("Lexington Area", "#9B6554"),
        3: ("Frankfort Area", "#545A35"),
        4: ("Lexington Area", "#9B6554")
    }
    label, color = weekday_labels.get(preferred_date.weekday(), ("", ""))
    if label:
        st.markdown(f"<span style='color:{color}; font-weight:bold'>{label}</span>", unsafe_allow_html=True)

    if st.button("Send Confirmation Email"):

        def create_google_calendar_event(summary, description, date_str):
            data = {
                "add_on_option": "Yes" if add_on_option else "No",
            }

            try:
                start_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                end_date = start_date + timedelta(days=1)

                event = {
                    "summary": summary,
                    "description": description,
                    "start": {"date": str(start_date)},
                    "end": {"date": str(end_date)},
                }

                created = calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
                return created.get("htmlLink")

            except HttpError as e:
                st.error("📅 Google Calendar API error. See details in logs.")
                st.text(e.content.decode())  # Shows actual error from Google in Streamlit output
                raise

        def create_pdf_filled():
            template_path = "delivery_template.pdf"
            filled_path = "/tmp/filled_temp.pdf"
            output_buffer = io.BytesIO()

            ANNOT_KEY = "/Annots"
            ANNOT_FIELD_KEY = "/T"
            ANNOT_VAL_KEY = "/V"
            ANNOT_RECT_KEY = "/Rect"
            SUBTYPE_KEY = "/Subtype"
            WIDGET_SUBTYPE_KEY = "/Widget"

            data = {
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "customer_street": customer_street,
                "customer_city": customer_city,
                "customer_zip": customer_zip,
                "origin_choice": origin_choice,
                "delivery_type": delivery_type,
                "quote": f"${st.session_state.quote:.2f}",
                "customer_notes": customer_notes,
                "delivery_details": delivery_details,
                "preferred_date": preferred_date.strftime('%A, %m/%d/%Y'),
                "cashier_initials": cashier_initials,
                "add_on_option": "Yes" if add_on_option else "No",
            }

            def sanitize_for_pdf(value):
                if not isinstance(value, str):
                    value = str(value)
                return (
                    value.replace("(", "[")
                         .replace(")", "]")
                         .replace("&", "and")
                         .replace("\n", "  /  ")
                         .replace("\r", "")
                         .replace(":", "-")
                         .replace("\"", " ' ")
                         .replace("\\", "/")
                         .strip()
                )


            template_pdf = PdfReader(template_path)
            for page in template_pdf.pages:
                annotations = page.get(ANNOT_KEY)
                if annotations:
                    for annotation in annotations:
                        if annotation.get(SUBTYPE_KEY) == WIDGET_SUBTYPE_KEY:
                            key = annotation.get(ANNOT_FIELD_KEY)
                            if key:
                                if isinstance(key, str):
                                    key_name = key.strip("()")
                                else:
                                    key_name = str(key)[1:-1]
                                if key_name in data:
                                    value = sanitize_for_pdf(data[key_name])
                                    annotation[PdfName("V")] = PdfObject(f"({value})")

            PdfWriter(filled_path, trailer=template_pdf).write()

            doc = fitz.open(filled_path)
            for page in doc:
                widgets = page.widgets()
                if widgets:
                    for widget in widgets:
                        widget.update()  # Forces rendering
                        widget.field_flags |= 1 << 0  # Set field to ReadOnly (optional)
            doc.save(output_buffer, deflate=True)
            output_buffer.seek(0)

            return output_buffer

        description = f"Customer Name: {customer_name}\nPhone Number: {customer_phone}\nDelivery Address: {customer_address}\n\nPlants and Materials: {delivery_details}\nTo The Hole?: {add_on_option}\n\nNotes: {customer_notes}\n\nQuote: ${st.session_state.quote:.2f}\n\nCashier: {cashier_initials}\nDate: {date.today().strftime('%A, %B %d, %Y')}"
    
        event_link = create_google_calendar_event(
            summary=f"Delivery: {customer_name}",
            description=description,
            date_str=preferred_date.strftime('%Y-%m-%d'),
        )

        pdf_buffer = create_pdf_filled()
        pdf_filename = f"DELIVERY-{preferred_date.strftime('%m-%d-%Y')}.pdf"

        try:
            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = NOTIFY_EMAIL
            msg["Subject"] = f"Delivery Scheduled: {customer_name}"
            msg.attach(MIMEText(description + f"\n\nCalendar Event: {event_link}", "plain"))

            part = MIMEApplication(pdf_buffer.read(), Name=pdf_filename)
            part['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
            msg.attach(part)

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.sendmail(SENDER_EMAIL, NOTIFY_EMAIL, msg.as_string())

            st.success("Delivery Scheduled!")

            pdf_buffer.seek(0)
            b64_pdf = base64.b64encode(pdf_buffer.read()).decode()
            href = f'<a href="data:application/octet-stream;base64,{b64_pdf}" download="{pdf_filename}" target="_blank">Download PDF Receipt</a>'
            st.markdown(href, unsafe_allow_html=True)

            if st.button("Schedule another delivery"):
                reset_app()

        except Exception as e:
            st.error(f"Failed to send email: {e}")
