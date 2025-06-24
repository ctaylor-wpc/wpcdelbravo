import streamlit as st
import requests
import json
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO

st.set_page_config(page_title="Wilson Plant Co. Delivery Quote", layout="centered")

# Apply custom CSS for colors and fonts
st.markdown("""
    <style>
        body, .stApp {
            background-color: #FBF8F6;
            color: #5e5e5e;
            font-family: sans-serif;
        }
        .stButton>button {
            background-color: #545A35;
            color: white;
            border-radius: 0.5rem;
        }
        .stRadio > div > label {
            color: #5e5e5e !important;
        }
        .css-1v0mbdj p, .stMarkdown p {
            color: #5e5e5e;
        }
        .css-1aumxhk, .stSelectbox label, .stDateInput label {
            color: #5e5e5e;
        }
        .stAlert[data-baseweb="alert"] {
            background-color: #9B6554;
            color: white;
        }
    </style>
""", unsafe_allow_html=True)

# Address options
origin_addresses = {
    "Frankfort": "3690 East West Connector, Frankfort, KY 40601",
    "Lexington": "2700 Palumbo Drive, Lexington, KY 40509"
}

# Delivery Type settings
rate_table = {
    "Single": {"Frankfort": {"min": 45, "rate": 2.00}, "Lexington": {"min": 50, "rate": 2.00}},
    "Double": {"Frankfort": {"min": 60, "rate": 2.95}, "Lexington": {"min": 70, "rate": 2.95}},
    "Bulk": {"Frankfort": {"min": 55, "rate": 2.65}, "Lexington": {"min": 65, "rate": 2.65}},
    "Bulk Plus": {"Frankfort": {"min": 65, "rate": 3.15}, "Lexington": {"min": 80, "rate": 3.15}}
}

# Google Maps API call (legacy Distance Matrix)
def get_distance_miles(origin, destination):
    api_key = st.secrets["api"]["google_maps_api_key"]
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?units=imperial&origins={origin}&destinations={destination}&key={api_key}"
    response = requests.get(url)
    data = response.json()
    try:
        distance_text = data['rows'][0]['elements'][0]['distance']['text']
        return float(distance_text.replace(" mi", ""))
    except Exception:
        return None

def calculate_delivery_fee(origin_name, destination, delivery_type, add_on_option):
    if delivery_type == "Simple":
        if "Frankfort" in destination:
            return 0, 8.00
        elif "Lexington" in destination:
            return 0, 30.00
        else:
            return None, "Cannot calculate Simple delivery for this address."
    else:
        origin = origin_addresses[origin_name]
        miles = get_distance_miles(origin, destination)
        if miles is None:
            return None, "Could not calculate mileage. Check the address."
        round_trip = miles * 2
        rate = rate_table[delivery_type][origin_name]
        fee = max(rate["min"], round_trip * rate["rate"])
        if add_on_option:
            fee += 10.00  # To-The-Hole surcharge
        return round_trip, round(fee, 2)

def generate_pdf(name, phone, notes, quote, date, time):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(100, 750, f"Delivery Confirmation")
    c.drawString(100, 730, f"Customer Name: {name}")
    c.drawString(100, 715, f"Phone: {phone}")
    c.drawString(100, 700, f"Notes: {notes}")
    c.drawString(100, 685, f"Quote: ${quote:.2f}")
    c.drawString(100, 670, f"Preferred Date: {date}")
    c.drawString(100, 655, f"Preferred Time: {time}")
    c.save()
    buffer.seek(0)
    return buffer

def send_email_with_pdf(to, subject, html_body, pdf_file):
    smtp_server = st.secrets["email"]["smtp_server"]
    smtp_port = st.secrets["email"]["smtp_port"]
    sender_email = st.secrets["email"]["sender_email"]
    password = st.secrets["email"]["sender_password"]

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    part = MIMEApplication(pdf_file.read(), _subtype="pdf")
    part.add_header('Content-Disposition', 'attachment', filename="delivery_confirmation.pdf")
    msg.attach(part)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, password)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)

# Initialize session state
if "quote_submitted" not in st.session_state:
    st.session_state.quote_submitted = False

st.title("🌿 Wilson Plant Co. Delivery Quote")
st.header("Step 1: Delivery Info")

customer_address = st.text_input("Customer Address")
origin_name = st.radio("Sold From", ["Frankfort", "Lexington"])
delivery_type = st.radio("Select Delivery Type", ["Simple", "Single", "Double", "Bulk", "Bulk Plus"], index=1)
add_on_option = st.checkbox("Add 'To The Hole' option?")

if st.button("Calculate Quote") or customer_address:
    mileage, quote = calculate_delivery_fee(origin_name, customer_address, delivery_type, add_on_option)
    if mileage is None:
        st.error(quote)
    else:
        st.success(f"Delivery Quote: ${quote:.2f} (Round trip miles: {mileage:.2f})")
        st.session_state.quote_submitted = True

if st.session_state.quote_submitted:
    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name")
    customer_phone = st.text_input("Customer Phone Number")
    customer_notes = st.text_area("Please list plants, materials, gate codes, or other notes")

    st.header("Step 3: Scheduling")
    preferred_date = st.date_input("Preferred Delivery Date", min_value=datetime.date.today())
    time_pref = st.radio("Preferred Delivery Time", ["Doesn't Matter", "Morning", "Afternoon"], index=0)

    if st.button("Send Confirmation Email and Schedule Delivery"):
        formatted_date = preferred_date.strftime("%A %m/%d/%Y") if preferred_date else "No date selected"
        pdf = generate_pdf(customer_name, customer_phone, customer_notes, quote, formatted_date, time_pref)

        html_body = f"""
            <h2>Delivery Scheduled</h2>
            <p><strong>Name:</strong> {customer_name}</p>
            <p><strong>Phone:</strong> {customer_phone}</p>
            <p><strong>Quote:</strong> ${quote:.2f}</p>
            <p><strong>Preferred Date:</strong> {formatted_date}</p>
            <p><strong>Time Preference:</strong> {time_pref}</p>
            <p><strong>Notes:</strong> {customer_notes}</p>
        """

        success, error_message = send_email_with_pdf(st.secrets["email"]["notify_email"], "New Delivery Scheduled", html_body, pdf)
        if success:
            st.success("✅ Delivery Scheduled!")

            # Show PDF for printing right after scheduling
            pdf_bytes = pdf.getvalue()
            st.download_button(
                label="Download & Print Delivery Confirmation PDF",
                data=pdf_bytes,
                file_name="delivery_confirmation.pdf",
                mime="application/pdf",
                on_click=None
            )

            if st.button("Schedule Another Delivery"):
                st.session_state.clear()
                st.experimental_rerun()
        else:
            st.error(f"Failed to send email: {error_message}")
