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
from googleapiclient.errors import HttpError
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import base64
from pdfrw import PdfObject, PdfName, PdfReader, PdfWriter, PageMerge
import fitz

# Import delivery configuration
from delivery_config import (
    DELIVERY_TYPES, 
    TO_THE_HOLE_FEE, 
    ORIGIN_ADDRESSES,
    get_delivery_type_names,
    is_to_the_hole_allowed,
    calculate_christmas_tree_small_price,
    calculate_christmas_tree_large_price,
    calculate_standard_price
)

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

# API and Email configuration from Streamlit secrets
GOOGLE_MAPS_API_KEY = st.secrets["api"]["google_maps_api_key"]
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

# Initialize session state
if "quote_shown" not in st.session_state:
    st.session_state.quote_shown = False

def reset_app():
    """Reset the entire application state"""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

@st.cache_data(show_spinner=False)
def get_distance_miles(origin, destination):
    """Get distance in miles using Google Maps API"""
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={origin}&destinations={destination}&key={GOOGLE_MAPS_API_KEY}"
    response = requests.get(url)
    data = response.json()
    
    if data["status"] != "OK" or data["rows"][0]["elements"][0]["status"] != "OK":
        return None
    
    meters = data["rows"][0]["elements"][0]["distance"]["value"]
    return round(meters / 1609.34, 2)

def calculate_delivery_fee(origin, destination, delivery_type, add_on, customer_city):
    """Calculate delivery fee based on type and distance"""
    config = DELIVERY_TYPES[delivery_type]
    pricing_type = config.get("pricing_type", "standard")
    
    # Handle Simple delivery type (fixed pricing by city)
    if pricing_type == "simple":
        city_clean = customer_city.strip().lower()
        if city_clean == "frankfort":
            mileage = get_distance_miles(origin, destination)
            return mileage * 2 if mileage else None, config["frankfort_price"]
        elif city_clean == "lexington":
            mileage = get_distance_miles(origin, destination)
            return mileage * 2 if mileage else None, config["lexington_price"]
        else:
            return None, None
    
    # Validate to-the-hole option
    if add_on and not is_to_the_hole_allowed(delivery_type):
        return None, None
    
    # Calculate mileage
    mileage = get_distance_miles(origin, destination)
    if mileage is None:
        return None, None
    
    round_trip = mileage * 2
    
    # Calculate price based on pricing type
    if pricing_type == "christmas_tree_small":
        final_fee = calculate_christmas_tree_small_price(round_trip)
    elif pricing_type == "christmas_tree_large":
        final_fee = calculate_christmas_tree_large_price(round_trip)
    elif pricing_type == "standard":
        # Determine origin name for minimum calculation
        origin_name = [k for k, v in ORIGIN_ADDRESSES.items() if v == origin][0]
        final_fee = calculate_standard_price(round_trip, delivery_type, origin_name)
    else:
        return None, None
    
    # Add to-the-hole fee if selected
    if add_on:
        final_fee += TO_THE_HOLE_FEE
    
    return round_trip, round(final_fee, 2)

def create_google_calendar_event(summary, description, date_str):
    """Create event on Google Calendar"""
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
        st.text(e.content.decode())
        raise

def create_pdf_filled(data):
    """Fill PDF template with delivery data"""
    template_path = "delivery_template.pdf"
    filled_path = "/tmp/filled_temp.pdf"
    output_buffer = io.BytesIO()

    ANNOT_KEY = "/Annots"
    ANNOT_FIELD_KEY = "/T"
    SUBTYPE_KEY = "/Subtype"
    WIDGET_SUBTYPE_KEY = "/Widget"

    def sanitize_for_pdf(value):
        """Clean value for PDF field insertion"""
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
                        key_name = key.strip("()") if isinstance(key, str) else str(key)[1:-1]
                        if key_name in data:
                            value = sanitize_for_pdf(data[key_name])
                            annotation[PdfName("V")] = PdfObject(f"({value})")

    PdfWriter(filled_path, trailer=template_pdf).write()

    # Flatten PDF fields
    doc = fitz.open(filled_path)
    for page in doc:
        widgets = page.widgets()
        if widgets:
            for widget in widgets:
                widget.update()
                widget.field_flags |= 1 << 0  # Set field to ReadOnly
    doc.save(output_buffer, deflate=True)
    output_buffer.seek(0)

    return output_buffer

# ============================================
# MAIN APPLICATION UI
# ============================================

st.header("Step 1: Delivery Quote")

with st.form(key="quote_form"):
    customer_street = st.text_input("Street Address")
    customer_city = st.text_input("City")
    customer_zip = st.text_input("Zip Code")
    customer_address = f"{customer_street}, {customer_city}, KY {customer_zip}"
    
    origin_choice = st.radio("Select Delivery Origin", list(ORIGIN_ADDRESSES.keys()))
    delivery_type = st.selectbox("Select Delivery Type", get_delivery_type_names())
    add_on_option = st.checkbox("To-The-Hole")
    
    submit_quote = st.form_submit_button("Calculate Quote")

origin_address = ORIGIN_ADDRESSES[origin_choice]

if submit_quote and customer_address:
    # Validate to-the-hole option
    if add_on_option and not is_to_the_hole_allowed(delivery_type):
        st.error(f"'To-The-Hole' option is not available for {delivery_type} delivery type.")
    else:
        mileage, quote = calculate_delivery_fee(
            origin_address, 
            customer_address, 
            delivery_type, 
            add_on_option, 
            customer_city
        )
        
        if quote is None:
            st.error("Unable to calculate quote. Please check the address and try again.")
        else:
            st.session_state.quote_shown = True
            st.session_state.mileage = mileage
            st.session_state.quote = quote
            st.session_state.customer_street = customer_street
            st.session_state.customer_city = customer_city
            st.session_state.customer_zip = customer_zip
            st.session_state.customer_address = customer_address
            st.session_state.origin_choice = origin_choice
            st.session_state.delivery_type = delivery_type
            st.session_state.add_on_option = add_on_option

# Step 2 & 3: Show after quote is calculated
if st.session_state.get("quote_shown"):
    st.success(f"💵 Delivery Quote: ${st.session_state.quote:.2f} (Roundtrip: {st.session_state.mileage} miles)")

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
        st.warning("⚠️ Weekends are not available. Please select a weekday.")

    # Show delivery area for selected date
    weekday_labels = {
        0: ("Frankfort Area", "#545A35"),
        1: ("Frankfort Area", "#545A35"),
        2: ("Lexington Area", "#9B6554"),
        3: ("Frankfort Area", "#545A35"),
        4: ("Lexington Area", "#9B6554")
    }
    label, color = weekday_labels.get(preferred_date.weekday(), ("", ""))
    if label:
        st.markdown(f"<span style='color:{color}; font-weight:bold'>📍 {label}</span>", unsafe_allow_html=True)

    if st.button("📧 Send Confirmation Email"):
        if not all([customer_name, customer_phone, delivery_details, cashier_initials]):
            st.error("Please fill in all required fields.")
        else:
            # Prepare data for PDF
            pdf_data = {
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "customer_street": st.session_state.customer_street,
                "customer_city": st.session_state.customer_city,
                "customer_zip": st.session_state.customer_zip,
                "origin_choice": st.session_state.origin_choice,
                "delivery_type": st.session_state.delivery_type,
                "quote": f"${st.session_state.quote:.2f}",
                "customer_notes": customer_notes,
                "delivery_details": delivery_details,
                "preferred_date": preferred_date.strftime('%A, %m/%d/%Y'),
                "cashier_initials": cashier_initials,
                "add_on_option": "Yes" if st.session_state.add_on_option else "No",
            }

            # Create calendar description
            description = (
                f"Customer Name: {customer_name}\n"
                f"Phone Number: {customer_phone}\n"
                f"Delivery Address: {st.session_state.customer_address}\n\n"
                f"Plants and Materials: {delivery_details}\n"
                f"To The Hole?: {st.session_state.add_on_option}\n\n"
                f"Notes: {customer_notes}\n\n"
                f"Quote: ${st.session_state.quote:.2f}\n\n"
                f"Cashier: {cashier_initials}\n"
                f"Date: {date.today().strftime('%A, %B %d, %Y')}"
            )

            try:
                # Create calendar event
                event_link = create_google_calendar_event(
                    summary=f"Delivery: {customer_name}",
                    description=description,
                    date_str=preferred_date.strftime('%Y-%m-%d'),
                )

                # Create PDF
                pdf_buffer = create_pdf_filled(pdf_data)
                pdf_filename = f"DELIVERY-{preferred_date.strftime('%m-%d-%Y')}.pdf"

                # Send email
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

                st.success("✅ Delivery Scheduled Successfully!")

                # Provide PDF download
                pdf_buffer.seek(0)
                b64_pdf = base64.b64encode(pdf_buffer.read()).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64_pdf}" download="{pdf_filename}" target="_blank">📥 Download PDF Receipt</a>'
                st.markdown(href, unsafe_allow_html=True)

                if st.button("🔄 Schedule another delivery"):
                    reset_app()

            except Exception as e:
                st.error(f"❌ Failed to process delivery: {e}")
