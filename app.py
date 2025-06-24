import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import date
from google.oauth2 import service_account
from googleapiclient.discovery import build
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os

# --------------------------
# GOOGLE CALENDAR SETUP
# --------------------------
def create_google_calendar_event(summary, location, description, start_date, time_pref):
    credentials_info = json.loads(st.secrets["gcp"]["service_account_json"])
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )

    service = build("calendar", "v3", credentials=credentials)

    time_mapping = {
        "Morning": "T09:00:00",
        "Afternoon": "T13:00:00",
        "Doesn't Matter": "T10:00:00"
    }
    start_time = start_date + time_mapping.get(time_pref, "T10:00:00")
    end_time = start_date + time_mapping.get(time_pref, "T10:00:00")

    event = {
        'summary': summary,
        'location': location,
        'description': description,
        'start': {
            'dateTime': start_time + '-04:00',
            'timeZone': 'America/New_York',
        },
        'end': {
            'dateTime': end_time + '-04:00',
            'timeZone': 'America/New_York',
        },
    }

    event_result = service.events().insert(calendarId='deliveries@wilsonnurseriesky.com', body=event).execute()
    return event_result.get('htmlLink')

# --------------------------
# EMAIL SENDER
# --------------------------
def send_email_with_pdf(to_email, subject, body, pdf_file):
    msg = MIMEMultipart()
    msg['From'] = st.secrets["email"]["sender_email"]
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    with open(pdf_file, "rb") as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(pdf_file))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_file)}"'
        msg.attach(part)

    with smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"]) as server:
        server.starttls()
        server.login(st.secrets["email"]["sender_email"], st.secrets["email"]["sender_password"])
        server.sendmail(msg['From'], msg['To'], msg.as_string())

# --------------------------
# PDF CREATOR
# --------------------------
def create_pdf(filename, customer_name, phone, notes, quote, date, time):
    c = canvas.Canvas(filename, pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(100, 750, f"Delivery Scheduled for {customer_name}")
    c.drawString(100, 730, f"Phone: {phone}")
    c.drawString(100, 710, f"Quote: ${quote:.2f}")
    c.drawString(100, 690, f"Preferred Delivery Date: {date} at {time}")
    c.drawString(100, 670, "Notes:")
    c.drawString(100, 650, notes)
    c.save()

# --------------------------
# MAIN UI
# --------------------------

st.set_page_config(page_title="Wilson Delivery Scheduler", layout="centered")

st.markdown("""
    <style>
        body {background-color: #FBF8F6; color: #5e5e5e;}
        .stButton>button {background-color: #545A35; color: white; font-weight: bold;}
        .accent {color: #9B6554; font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

st.title("Wilson Plant Co. Delivery Scheduler")

# Step 1
st.header("Step 1: Delivery Quote")
customer_address = st.text_input("Customer Address")
delivery_origin = st.selectbox("Delivery Origin", ["Frankfort", "Lexington"])
delivery_type = st.radio("Select Delivery Type", ["Simple", "Single", "Double", "Bulk", "Bulk Plus"], index=1)
add_on = st.checkbox("Add-On: To The Hole")

quote_calculated = False
if st.button("Calculate Quote"):
    # Placeholder for actual mileage + logic
    quote = 56.75  # Placeholder value
    st.success(f"Estimated Delivery Quote: ${quote:.2f}")
    quote_calculated = True

if quote_calculated:
    st.header("Step 2: Customer Info")
    customer_name = st.text_input("Customer Name")
    phone = st.text_input("Phone Number")
    notes = st.text_area("Please list plants, materials, gate codes, or other notes")

    st.header("Step 3: Scheduling")

    # Custom calendar embed
    calendar_code = """
    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css\">
    <script src=\"https://cdn.jsdelivr.net/npm/flatpickr\"></script>
    <div>
        <input type=\"text\" id=\"datePicker\" placeholder=\"Select a date\" style=\"padding:8px; font-size:16px;\" />
    </div>
    <script>
        const input = document.getElementById(\"datePicker\");
        flatpickr(input, {
            inline: true,
            disable: [
                function(date) {
                    return (date.getDay() === 0 || date.getDay() === 6);
                }
            ],
            onChange: function(selectedDates, dateStr, instance) {
                const streamlitEvent = new CustomEvent(\"dateSelected\", { detail: dateStr });
                window.dispatchEvent(streamlitEvent);
            }
        });

        window.addEventListener(\"DOMContentLoaded\", () => {
            const streamlitInput = window.streamlitInput = {
                send: function(value) {
                    window.parent.postMessage({ type: \"streamlit:setComponentValue\", value }, \"*\");
                }
            };

            window.addEventListener(\"dateSelected\", function(e) {
                streamlitInput.send(e.detail);
            });
        });
    </script>
    """

    selected_date = components.html(calendar_code, height=330)

    time_pref = st.radio("Preferred Delivery Time", ["Doesn't Matter", "Morning", "Afternoon"], index=0)

    if st.button("Send Confirmation Email & Schedule"):
        summary = f"Delivery for {customer_name}"
        description = notes
        location = customer_address
        pdf_file = "confirmation.pdf"

        create_pdf(pdf_file, customer_name, phone, notes, quote, selected_date, time_pref)
        send_email_with_pdf(
            st.secrets["email"]["notify_email"],
            "Delivery Confirmation",
            f"Delivery scheduled for {customer_name} at {selected_date} ({time_pref})",
            pdf_file
        )

        create_google_calendar_event(
            summary=summary,
            location=location,
            description=description,
            start_date=selected_date,
            time_pref=time_pref
        )

        st.success("Delivery Scheduled!")
        if st.button("Schedule Another Delivery"):
            st.experimental_rerun()
