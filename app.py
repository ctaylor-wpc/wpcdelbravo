import streamlit as st
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import base64
import smtplib
from email.message import EmailMessage
import googlemaps
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta, date, time
import json

st.set_page_config(page_title="Delivery Scheduler", page_icon="🚚", layout="centered")

# --- Style overrides ---
st.markdown(
    """
    <style>
    /* Background */
    .stApp {
        background-color: #FBF8F6;
        color: #5e5e5e;
        font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    }
    /* Primary button */
    div.stButton > button:first-child {
        background-color: #545A35;
        color: white;
        border-radius: 8px;
        padding: 8px 20px;
        font-weight: 600;
    }
    /* Primary button hover */
    div.stButton > button:first-child:hover {
        background-color: #434927;
        color: white;
    }
    /* Error messages red replaced */
    .stExceptionText {
        color: #9B6554 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- Constants ---
FRANKFORT_ADDR = "3690 East West Connector, Frankfort, KY 40601"
LEXINGTON_ADDR = "2700 Palumbo Drive, Lexington, KY 40509"

DELIVERY_TYPES = ["Simple", "Single", "Double", "Bulk", "Bulk Plus"]
ADD_ON_OPTIONS = ["To The Hole"]

PREFERRED_TIMES = ["Doesn't Matter", "Morning", "Afternoon"]

# --- Load secrets ---
gmaps_api_key = st.secrets["api"]["google_maps_api_key"]

email_info = st.secrets["email"]
sender_email = email_info["sender_email"]
sender_password = email_info["sender_password"]
smtp_server = email_info["smtp_server"]
smtp_port = int(email_info["smtp_port"])
notify_email = email_info["notify_email"]

# Load service account json
gcp_json_str = st.secrets["gcp"]["service_account_json"]
credentials_info = json.loads(gcp_json_str)
credentials = service_account.Credentials.from_service_account_info(
    credentials_info,
    scopes=["https://www.googleapis.com/auth/calendar"]
)

calendar_service = build("calendar", "v3", credentials=credentials)

# Google Maps client
gmaps = googlemaps.Client(key=gmaps_api_key)

# --- Helper Functions ---

def get_roundtrip_miles(origin, destination):
    try:
        directions_result = gmaps.directions(origin, destination)
        if not directions_result:
            return None
        distance_meters = directions_result[0]['legs'][0]['distance']['value']
        distance_miles = distance_meters / 1609.344
        return round(distance_miles * 2, 2)
    except Exception as e:
        st.error(f"Google Maps API error: {e}")
        return None

def calculate_delivery_fee(origin, destination, delivery_type, add_on_option):
    # If Simple, fixed fees for Frankfort or Lexington, else no calculation
    if delivery_type == "Simple":
        if "Frankfort" in origin:
            return 8.00
        elif "Lexington" in origin:
            return 30.00
        else:
            return None

    miles = get_roundtrip_miles(origin, destination)
    if miles is None:
        return None

    # Set multipliers and minimums per delivery type
    if delivery_type == "Single":
        multiplier = 2.00
        minimum = 45 if "Frankfort" in origin else 50
    elif delivery_type == "Double":
        multiplier = 2.95
        minimum = 60 if "Frankfort" in origin else 70
    elif delivery_type == "Bulk":
        multiplier = 2.65
        minimum = 55 if "Frankfort" in origin else 65
    elif delivery_type == "Bulk Plus":
        multiplier = 3.15
        minimum = 65 if "Frankfort" in origin else 80
    else:
        return None

    fee = round(miles * multiplier, 2)
    if fee < minimum:
        fee = minimum

    # Add add-on charge if "To The Hole" selected (let's assume $15)
    if add_on_option == "To The Hole":
        fee += 15.00

    return fee

def create_google_calendar_event(summary, description, start_datetime, end_datetime):
    event = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_datetime.isoformat(),
            'timeZone': 'America/New_York',
        },
        'end': {
            'dateTime': end_datetime.isoformat(),
            'timeZone': 'America/New_York',
        }
    }
    created_event = calendar_service.events().insert(calendarId='deliveries@wilsonnurseriesky.com', body=event).execute()
    return created_event.get('htmlLink')

def generate_pdf(customer_name, customer_phone, customer_notes, quote, delivery_date, delivery_time):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    textobject = c.beginText(40, 750)
    textobject.setFont("Helvetica", 12)
    textobject.textLine(f"Delivery Confirmation")
    textobject.textLine(f"Customer: {customer_name}")
    textobject.textLine(f"Phone: {customer_phone}")
    textobject.textLine(f"Notes: {customer_notes}")
    textobject.textLine(f"Quote: ${quote:.2f}")
    textobject.textLine(f"Scheduled Delivery Date: {delivery_date}")
    textobject.textLine(f"Preferred Time: {delivery_time}")
    c.drawText(textobject)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

def send_email_with_pdf(sender_email, sender_password, to_email, subject, body, pdf_buffer, pdf_filename):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = to_email
    msg.set_content(body)

    pdf_data = pdf_buffer.read()
    msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=pdf_filename)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True, "Email sent successfully!"
    except Exception as e:
        return False, f"Failed to send email: {e}"

# --- Session state defaults ---
if "step" not in st.session_state:
    st.session_state.step = 1
if "quote" not in st.session_state:
    st.session_state.quote = None

def reset_app():
    st.session_state.step = 1
    st.session_state.quote = None
    for key in ["customer_name", "customer_phone", "customer_notes", "preferred_date", "preferred_time", "sold_from", "delivery_type", "add_on_option", "customer_address"]:
        if key in st.session_state:
            del st.session_state[key]

# --- App UI ---

st.title("Delivery Scheduler")

if st.session_state.step == 1:
    st.header("Step 1: Quick Quote")

    customer_address = st.text_input("Customer Address", key="customer_address")

    sold_from = st.radio("Sold From", ["Frankfort", "Lexington"], key="sold_from", index=0)

    delivery_type = st.radio("Select Delivery Type", DELIVERY_TYPES, key="delivery_type", index=1)

    add_on_option = st.selectbox("Add-on Option (Optional)", ["None"] + ADD_ON_OPTIONS, key="add_on_option")

    if st.button("Calculate Quote"):
        if not customer_address:
            st.error("Please enter a customer address")
        else:
            origin_addr = FRANKFORT_ADDR if sold_from == "Frankfort" else LEXINGTON_ADDR
            add_on = add_on_option if add_on_option != "None" else None
            fee = calculate_delivery_fee(origin_addr, customer_address, delivery_type, add_on)
            if fee is None:
                st.error("Could not calculate delivery fee for the given address/type.")
            else:
                st.session_state.quote = fee
                st.success(f"Delivery Quote: ${fee:.2f}")
                st.session_state.step = 2
                # Save values in session state for later steps
                st.session_state.customer_address = customer_address
                st.session_state.sold_from = sold_from
                st.session_state.delivery_type = delivery_type
                st.session_state.add_on_option = add_on_option

if st.session_state.step >= 2:
    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name", key="customer_name")
    customer_phone = st.text_input("Customer Phone", key="customer_phone")
    customer_notes = st.text_area("Please list plants, materials, gate codes, or other notes", key="customer_notes")

    st.header("Step 3: Scheduling")

    # Block weekends & label weekdays for calendar
    def disabled_days(date_to_check):
        # Block weekends
        if date_to_check.weekday() in [5,6]:
            return True
        return False

    # Add weekday labels and colors
    # (We'll just color the label in UI, date picker itself can't label days)
    weekday_labels = {
        0: ("Monday", "#545A35", "Frankfort Area"),
        1: ("Tuesday", "#545A35", "Frankfort Area"),
        2: ("Wednesday", "#9B6554", "Lexington Area"),
        3: ("Thursday", "#545A35", "Frankfort Area"),
        4: ("Friday", "#9B6554", "Lexington Area"),
    }

    st.write("Preferred Delivery Date:")
    preferred_date = st.date_input(
        "",
        min_value=date.today(),
        key="preferred_date"
    )

    # Display weekday label & color for selected date
    wd = preferred_date.weekday()
    if wd in weekday_labels:
        label, color, area = weekday_labels[wd]
        st.markdown(f"<span style='color:{color}; font-weight:bold;'>Day: {label} ({area})</span>", unsafe_allow_html=True)

    preferred_time = st.radio("Preferred Delivery Time", PREFERRED_TIMES, index=0, key="preferred_time")

    quote = st.session_state.quote

    if st.button("Send Confirmation Email and Schedule Delivery"):

        # Build delivery datetime (assuming time slot)
        if preferred_time == "Morning":
            start_dt = datetime.combine(preferred_date, time(hour=9))
        elif preferred_time == "Afternoon":
            start_dt = datetime.combine(preferred_date, time(hour=14))
        else:  # Doesn't Matter defaults to Morning slot
            start_dt = datetime.combine(preferred_date, time(hour=9))
        end_dt = start_dt + timedelta(hours=1)

        # Event details
        event_summary = f"Delivery for {customer_name}"
        event_desc = f"Phone: {customer_phone}\nNotes: {customer_notes}\nAddress: {st.session_state.customer_address}\nDelivery Type: {st.session_state.delivery_type}\nQuote: ${quote:.2f}"

        try:
            event_link = create_google_calendar_event(event_summary, event_desc, start_dt, end_dt)
            st.success(f"Delivery scheduled! [View Event]({event_link})")
        except Exception as e:
            st.error(f"Failed to create calendar event: {e}")
            event_link = None

        # Generate PDF
        pdf_buffer = generate_pdf(customer_name, customer_phone, customer_notes, quote, preferred_date.strftime("%A %m/%d/%Y"), preferred_time)

        # Send email and handle errors
        success, message = send_email_with_pdf(
            sender_email=sender_email,
            sender_password=sender_password,
            to_email=notify_email,
            subject=f"Delivery Scheduled for {customer_name}",
            body=event_desc,
            pdf_buffer=pdf_buffer,
            pdf_filename="Delivery_Confirmation.pdf"
        )
        if success:
            st.success(message)
            pdf_bytes = pdf_buffer.getvalue()
            b64 = base64.b64encode(pdf_bytes).decode()
            href = f'<a href="data:application/octet-stream;base64,{b64}" download="Delivery_Confirmation.pdf">Download PDF Receipt</a>'
            st.markdown(href, unsafe_allow_html=True)

            if st.button("Print PDF Receipt"):
                st.markdown(
                    f"""
                    <script>
                    function printPdf() {{
                        const link = document.createElement('a');
                        link.href = "data:application/pdf;base64,{b64}";
                        link.download = "Delivery_Confirmation.pdf";
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                        window.print();
                    }}
                    </script>
                    <button onclick="printPdf()">Print PDF Receipt</button>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.error(message)

        # Show button to schedule another delivery, resets state
        if st.button("Schedule Another Delivery"):
            reset_app()
            st.experimental_rerun()
