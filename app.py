import streamlit as st
import googlemaps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io
import re
import math
from pdfrw import PdfObject
from pdfrw import PdfName
from pdfrw import PdfReader
from pdfrw import PdfWriter
from pdfrw import PageMerge
import fitz
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload 
import datetime
import json



# Allow access to Google Sheet Dashboard
def _get_service_account_info_from_secrets():
    """
    Reads service account JSON stored in st.secrets["gcp"]["service_account_json"].
    Handles either a dict or a JSON string (escaped newlines etc).
    """
    sa = st.secrets.get("gcp", {}).get("service_account_json")
    if not sa:
        raise KeyError("Service account JSON not found: check st.secrets['gcp']['service_account_json']")
    if isinstance(sa, str):
        return json.loads(sa)
    return sa

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_gspread_client():
    sa_info = _get_service_account_info_from_secrets()
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return gspread.authorize(creds)

SHEET_ID = "1kEOIdxYqPKx6R47sNdaY8lWR8PmLc6bz_PyHtYH1M7Q"



# Allow Access to Google Drive for PDF Upload
def get_drive_service():
    """
    Returns a Google Drive service using the same service account as Sheets.
    """
    sa_info = _get_service_account_info_from_secrets()
    creds = Credentials.from_service_account_info(sa_info, scopes=["https://www.googleapis.com/auth/drive"])
    service = build("drive", "v3", credentials=creds)
    return service



# STEP 0: Initialize session state and configuration
def initialize_app():
    """Initialize the Streamlit app with session state variables"""
    if 'phase' not in st.session_state:
        st.session_state.phase = 1
    if 'step' not in st.session_state:
        st.session_state.step = 'A'
    if 'plant_count' not in st.session_state:
        st.session_state.plant_count = 1
    if 'plants' not in st.session_state:
        st.session_state.plants = {}

def clear_all_data():
    """Clear all session state data to restart the app"""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    initialize_app()



# STEP 1: Input validation and character cleaning functions
def clean_text_input(text_input):
    """Remove problematic characters from text input"""
    try:
        if text_input is None:
            return ""
        # Remove problematic characters: quotes, exclamations, etc.
        cleaned = re.sub(r'["\'\!\@\#\$\%\^\&\*\(\)]', '', str(text_input))
        return cleaned.strip()
    except Exception as e:
        st.error(f"Error cleaning text input: {e}")
        return ""

def validate_numeric_input(value, field_name):
    """Validate and convert numeric inputs"""
    try:
        if value is None or value == "":
            return 0
        return float(value)
    except ValueError:
        st.error(f"Invalid numeric value for {field_name}")
        return 0



# STEP 2: Plant size and mulch lookup tables
def get_mulch_soil_tablet_quantities(plant_size, mulch_type, quantity):
    """Calculate mulch, soil conditioner, and tablet quantities based on plant size and type"""
    try:
        # Lookup table for plant sizes
        size_data = {
            "1.25": {"mulch": (2, 2, 1), "soil": 0.5, "tablets": 4},
            "1.5": {"mulch": (2, 2, 1), "soil": 0.5, "tablets": 4},
            "1.75": {"mulch": (3, 3, 2), "soil": 1, "tablets": 5},
            "2": {"mulch": (3, 3, 3), "soil": 2, "tablets": 6},
            "5-6": {"mulch": (3, 3, 2), "soil": 1, "tablets": 5},
            "6-7": {"mulch": (3, 3, 3), "soil": 2, "tablets": 6},
            "Slender Upright": {"mulch": (2, 2, 1), "soil": 0.5, "tablets": 4},
            "1G": {"mulch": (0.5, 0.5, 0.25), "soil": 0.25, "tablets": 2},
            "2G": {"mulch": (0.5, 0.5, 0.25), "soil": 0.25, "tablets": 2},
            "3G": {"mulch": (0.5, 0.5, 0.25), "soil": 0.5, "tablets": 3},
            "5G": {"mulch": (1, 1, 0.5), "soil": 0.5, "tablets": 4},
            "7G": {"mulch": (1, 1, 1), "soil": 1, "tablets": 5},
            "10G": {"mulch": (2, 2, 2), "soil": 1, "tablets": 6},
            "15G": {"mulch": (2, 2, 2), "soil": 2, "tablets": 8},
            "30G": {"mulch": (3, 3, 3), "soil": 3, "tablets": 12}
        }
        
        # Mulch categories
        category_a = ["Soil Conditioner Only", "Hardwood", "Eastern Red Cedar", "Pine Bark", "Pine Bark Mini Nuggets", "Pine Bark Nuggets"]
        category_b = ["Grade A Cedar", "Redwood"]
        category_c = ["Pine Straw"]
        
        if plant_size not in size_data:
            st.error(f"Unknown plant size: {plant_size}")
            return 0, 0, 0
            
        base_data = size_data[plant_size]
        
        # Determine mulch column based on category
        if mulch_type in category_a:
            mulch_base = base_data["mulch"][0]
        elif mulch_type in category_b:
            mulch_base = base_data["mulch"][1]
        elif mulch_type in category_c:
            mulch_base = base_data["mulch"][2]
        else:
            st.error(f"Unknown mulch type: {mulch_type}")
            return 0, 0, 0
            
        # Calculate totals for this plant
        mulch_quantity = mulch_base * quantity
        soil_quantity = base_data["soil"] * quantity
        tablet_quantity = base_data["tablets"] * quantity
        
        return mulch_quantity, soil_quantity, tablet_quantity
        
    except Exception as e:
        st.error(f"Error calculating quantities: {e}")
        return 0, 0, 0



# STEP 3: Google Maps API integration for distance calculation
def calculate_driving_distance(origin, destination):
    """Calculate driving distance using Google Maps API"""
    try:
        # Get API key from Streamlit secrets
        api_key = st.secrets["api"]["google_maps_api_key"]
        if not api_key:
            st.error("Google Maps API key not found in secrets")
            return 0
            
        gmaps = googlemaps.Client(key=api_key)
        
        # Get distance matrix
        result = gmaps.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            units="imperial"
        )
        
        if result['status'] == 'OK':
            distance_text = result['rows'][0]['elements'][0]['distance']['text']
            # Extract numeric value from distance text (e.g., "15.2 mi" -> 15.2)
            distance_miles = float(re.findall(r'\d+\.?\d*', distance_text)[0])
            return distance_miles
        else:
            st.error("Could not calculate distance")
            return 0
            
    except Exception as e:
        st.error(f"Error calculating distance: {e}")
        return 0



# STEP 4: Pricing calculations
def calculate_pricing(plants_data, installation_data):
    """Calculate all pricing components"""
    try:
        # Plant material totals
        plant_material_total = 0
        plant_material_discount_total = 0
        
        total_mulch_quantity = 0
        total_soil_quantity = 0
        total_tablet_quantity = 0
        
        # Process each plant
        for plant_id, plant in plants_data.items():
            quantity = validate_numeric_input(plant.get('quantity', 0), f"Plant {plant_id} quantity")
            price = validate_numeric_input(plant.get('price', 0), f"Plant {plant_id} price")
            discount_percent = validate_numeric_input(plant.get('discount_percent', 0), f"Plant {plant_id} discount percent")
            discount_dollars = validate_numeric_input(plant.get('discount_dollars', 0), f"Plant {plant_id} discount dollars")
            
            # Calculate plant totals
            plant_total = price * quantity
            plant_material_total += plant_total
            
            # Apply discounts
            discounted_price = price * (1 - discount_percent / 100) - discount_dollars
            plant_material_discount_total += discounted_price * quantity
            
            # Calculate mulch, soil, tablet quantities for this plant
            plant_size = plant.get('size', '')
            mulch_type = installation_data.get('mulch_type', '')
            
            mulch_qty, soil_qty, tablet_qty = get_mulch_soil_tablet_quantities(plant_size, mulch_type, quantity)
            
            total_mulch_quantity += mulch_qty
            total_soil_quantity += soil_qty
            total_tablet_quantity += tablet_qty
        
        # Round quantities to whole numbers
        total_mulch_quantity = math.ceil(total_mulch_quantity)
        total_soil_quantity = math.ceil(total_soil_quantity)
        total_tablet_quantity = math.ceil(total_tablet_quantity)
        



        # CHANGE PRICING HERE - Update these values if pricing changes




        # INSTALL MATERIALS PRICING
        tablet_unit_price = 0.75
        soil_conditioner_unit_price = 9.99
        deer_guard_unit_price = 3.99
        tree_stake_unit_price = 36.00
        
        # MULCH PRICING AND SKU BY TYPE
        mulch_type = installation_data.get('mulch_type', '')
        mulch_sku = "placeholder"

        if mulch_type == "Soil Conditioner Only":
            mulch_unit_price = 9.99
            mulch_sku = "07SOILC02"
        elif mulch_type == "Hardwood":
            mulch_unit_price = 8.99
            mulch_sku = "7HARDRVM"
        elif mulch_type == "Eastern Red Cedar":
            mulch_unit_price = 8.99
            mulch_sku = "RVM CEDAR"
        elif mulch_type == "Pine Bark":
            mulch_unit_price = 8.99
            mulch_sku = "07PINEBM02"
        elif mulch_type == "Pine Bark Mini Nuggets":
            mulch_unit_price = 8.99
            mulch_sku = "07PINEBMN02"
        elif mulch_type == "Pine Bark Nuggets":
            mulch_unit_price = 8.99
            mulch_sku = "07PINEBN02"
        elif mulch_type == "Grade A Cedar":
            mulch_unit_price = 16.99
            mulch_sku = "CEDAR"
        elif mulch_type == "Redwood":
            mulch_unit_price = 16.99
            mulch_sku = "REDWOODM"
        elif mulch_type == "Pine Straw":
            mulch_unit_price = 15.99
            mulch_sku = "07PINESTRAW"
        else:
            mulch_unit_price = 8.99  # Default price
            mulch_sku = "7HARDRVM"



        
        # Calculate installation material costs
        tablet_total_price = total_tablet_quantity * tablet_unit_price
        mulch_total_price = total_mulch_quantity * mulch_unit_price
        soil_conditioner_total_price = total_soil_quantity * soil_conditioner_unit_price
        deer_guard_price = validate_numeric_input(installation_data.get('deer_guards_quantity', 0), 'deer guards') * deer_guard_unit_price
        tree_stakes_price = validate_numeric_input(installation_data.get('tree_stakes_quantity', 0), 'tree stakes') * tree_stake_unit_price
        
        installation_material_total = tablet_total_price + mulch_total_price + soil_conditioner_total_price + deer_guard_price + tree_stakes_price
        
        # Installation cost multiplier
        installation_type = installation_data.get('installation_type', '')
        if installation_type == "Shrubs Only: 97%":
            install_multiplier = 0.97
        elif installation_type == "1-3 trees: 97%":
            install_multiplier = 0.97
        elif installation_type == "4-6 trees: 91%":
            install_multiplier = 0.91
        elif installation_type == "7+ Trees: 85%":
            install_multiplier = 0.85
        else:
            install_multiplier = 0.97  # Default
            
        installation_cost = (installation_material_total + plant_material_total) * install_multiplier
        
        # Calculate delivery cost
        origin_location = installation_data.get('origin_location', 'Frankfort')
        if origin_location == "Frankfort":
            origin_address = "3690 East West Connector, Frankfort KY 40601"
        else:
            origin_address = "2700 Palumbo Drive Lexington KY 40509"
            
        customer_address = f"{installation_data.get('customer_street_address', '')}, {installation_data.get('customer_city', '')}, KY {installation_data.get('customer_zip', '')}"
        
        delivery_mileage = calculate_driving_distance(origin_address, customer_address)
        delivery_cost = 2.25 * 2 * delivery_mileage
        
        # Final calculations
        final_subtotal = plant_material_discount_total + installation_material_total + installation_cost + delivery_cost
        final_tax = final_subtotal * 0.06
        final_total = final_subtotal + final_tax
        
        return {
            'plant_material_total': plant_material_total,
            'plant_material_discount_total': plant_material_discount_total,
            'installation_material_total': installation_material_total,
            'installation_cost': installation_cost,
            'delivery_cost': delivery_cost,
            'delivery_mileage': delivery_mileage,
            'final_subtotal': final_subtotal,
            'final_tax': final_tax,
            'final_total': final_total,
            'total_mulch_quantity': total_mulch_quantity,
            'total_soil_quantity': total_soil_quantity,
            'total_tablet_quantity': total_tablet_quantity,

            #just for pdf
            'tablet_total_quantity': total_tablet_quantity,
            'mulch_total_quantity': total_mulch_quantity,
            'soil_conditioner_total_quantity': total_soil_quantity,

            'tablet_total_price': tablet_total_price,
            'mulch_total_price': mulch_total_price,
            'soil_conditioner_total_price': soil_conditioner_total_price,
            'deer_guard_price': deer_guard_price,
            'tree_stakes_price': tree_stakes_price,
            'mulch_sku': mulch_sku,
            'mulch_type': mulch_type,
        }
        
    except Exception as e:
        st.error(f"Error in pricing calculations: {e}")
        return {}



# STEP 5: PDF generation
def generate_pdf(plants_data, installation_data, customer_data, pricing_data):
    """Generate PDF quote document"""
    try:
        template_path = "install_template.pdf"
        filled_path = "/tmp/filled_temp.pdf"
        output_buffer = io.BytesIO()

        ANNOT_KEY = "/Annots"
        ANNOT_FIELD_KEY = "/T"
        ANNOT_VAL_KEY = "/V"
        SUBTYPE_KEY = "/Subtype"
        WIDGET_SUBTYPE_KEY = "/Widget"

        total_number_of_plants = sum([p.get("quantity", 0) for p in plants_data.values()])
        tablet_total_quantity = pricing_data.get("tablet_total_quantity", 0)
        mulch_total_quantity = pricing_data.get("mulch_total_quantity", 0)
        soil_conditioner_total_quantity = pricing_data.get("soil_conditioner_total_quantity", 0)

        tablet_total_price = pricing_data.get("tablet_total_price", 0)
        mulch_total_price = pricing_data.get("mulch_total_price", 0)
        soil_conditioner_total_price = pricing_data.get("soil_conditioner_total_price", 0)
        deer_guard_price = pricing_data.get("deer_guard_price", 0)
        tree_stakes_price = pricing_data.get("tree_stakes_price", 0)
        mulch_sku = pricing_data.get("mulch_sku", 0)
        mulch_type = installation_data.get('mulch_type', '')

        now = datetime.datetime.now()
        date_sold = f"{now.month}/{now.day}/{now.year}"

        installation_cost = pricing_data.get("installation_cost", 0)

        all_materials_discount_total = (
            pricing_data.get("plant_material_discount_total", 0)
            + pricing_data.get("installation_material_total", 0)
        )

        planting_costs_total = (
            pricing_data.get("installation_cost", 0)
            + pricing_data.get("delivery_cost", 0)
        )

        data = {
            "customer_name": customer_data.get("customer_name", ""),
            "customer_email": customer_data.get("customer_email", ""),
            "customer_phone": customer_data.get("customer_phone", ""),
            "customer_street_address": installation_data.get('customer_street_address', ''),
            "customer_city": installation_data.get('customer_city', ''),
            "customer_zip": installation_data.get('customer_zip', ''),
            "customer_subdivision": customer_data.get("customer_subdivision", ""),
            "customer_cross_street": customer_data.get("customer_cross_street", ""),
            "gate_response": customer_data.get("gate_response", ""),
            "gate_width": customer_data.get("gate_width", ""),
            "dogs_response": customer_data.get("dogs_response", ""),
            "install_location": customer_data.get("install_location", ""),
            "utilities_check": customer_data.get("utilities_check", ""),
            "notes": customer_data.get("notes", ""),
            "employee_initials": customer_data.get("employee_initials", ""),
            "mulch_type": installation_data.get("mulch_type", ""),
            "tree_stakes_quantity": installation_data.get("tree_stakes_quantity", 0),
            "deer_guards_quantity": installation_data.get("deer_guards_quantity", 0),
            "installation_type": installation_data.get("installation_type", ""),
            "origin_location": installation_data.get("origin_location", ""),
            "plant_list": "\n".join(
                [f"{p['quantity']} x {p['plant_material']} ({p['size']}) - ${p['price']:.2f}" for p in plants_data.values()]
            ),
            "total_price": f"${pricing_data.get('final_total', 0):.2f}",
            "subtotal": f"${pricing_data.get('final_subtotal', 0):.2f}",
            "tax": f"${pricing_data.get('final_tax', 0):.2f}",
            "delivery_cost": f"${pricing_data.get('delivery_cost', 0):.2f}",
            "flag_quantity": total_number_of_plants,
            "total_tablet_quantity": tablet_total_quantity,
            "total_mulch_quantity": mulch_total_quantity,
            "mulch_sku": mulch_sku,
            "mulch_type": mulch_type,
            "total_soil_conditioner_quantity": soil_conditioner_total_quantity,
            "tablet_total_price": f"${tablet_total_price:.2f}",
            "mulch_total_price": f"${mulch_total_price:.2f}",
            "soil_conditioner_total_price": f"${soil_conditioner_total_price:.2f}",
            "deer_guard_price": f"${deer_guard_price:.2f}",
            "tree_stakes_price": f"${tree_stakes_price:.2f}",
            "installation_cost": f"${installation_cost:.2f}",
            "all_materials_discount_total": f"${all_materials_discount_total:.2f}",
            "planting_costs_total": f"${planting_costs_total:.2f}",
            "date_sold": date_sold,
        }

        def sanitize_for_pdf(value):
            if not isinstance(value, str):
                value = str(value)
            return (
                value.replace("(", "[")
                     .replace(")", "]")
                     .replace("&", "and")
                     .replace("\n", " / ")
                     .replace("\r", "")
                     .replace(":", "-")
                     .replace("\"", "'")
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
                            key_name = str(key)[1:-1] if not isinstance(key, str) else key.strip("()")
                            if key_name in data:
                                value = sanitize_for_pdf(data[key_name])
                                annotation[PdfName("V")] = PdfObject(f"({value})")

        # Write the filled PDF to a temp file
        PdfWriter(filled_path, trailer=template_pdf).write()

        # Ensure annotations are rendered
        doc = fitz.open(filled_path)
        for page in doc:
            widgets = page.widgets()
            if widgets:
                for widget in widgets:
                    widget.update()  # Forces rendering
                    widget.field_flags |= 1 << 0  # Optional: set ReadOnly
        doc.save(output_buffer, deflate=True)
        output_buffer.seek(0)

        return output_buffer

    except Exception as e:
        st.error(f"Error generating PDF: {e}")
        return None



#STEP 6: Upload PDF to Google Drive
PDF_Folder_ID = "1UinHT5ZXjDrGXwfX-WBwge28nnHLfgq8"

def upload_pdf_to_drive(pdf_buffer, filename):
    """
    Upload a PDF from a BytesIO buffer to a Google Drive folder using service account credentials.
    Returns a shareable link.
    """
    try:
        service = get_drive_service()

        file_metadata = {
            "name": filename,
            "parents": [PDF_Folder_ID]
        }

        media = MediaIoBaseUpload(pdf_buffer, mimetype="application/pdf", resumable=True)

        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()

        file_id = uploaded_file.get("id")

        return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

    except Exception as e:
        st.error(f"Error uploading PDF to Drive: {e}")
        return ""

# MAIN APPLICATION INTERFACE
def main():
    """Main application interface"""
    initialize_app()
    
    st.title("🌿 Landscaping Quote Calculator")
    
    # Phase 1: Plant & Installation Data
    if st.session_state.phase == 1:
        
        # Step A: Plants to be installed
        if st.session_state.step == 'A':
            st.header("Step A: Plants to be Installed")
            
            current_plant = st.session_state.plant_count
            
            st.subheader(f"Plant #{current_plant}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                quantity = st.number_input(f"Quantity:", min_value=1, key=f"plant_{current_plant}_quantity")
                
                size_options = ["1.25", "1.5", "1.75", "2", "5-6", "6-7", "1G", "2G", "3G", "5G", "7G", "10G", "15G", "30G", "Slender Upright"]
                size = st.selectbox(f"Size:", size_options, key=f"plant_{current_plant}_size")
                
                plant_material = st.text_input(f"Plant Material:", key=f"plant_{current_plant}_material")
            
            with col2:
                price = st.number_input(f"Retail Price ($):", min_value=0.0, step=0.01, key=f"plant_{current_plant}_price")
                
                discount_percent = st.number_input(f"Discount (% Off):", min_value=0.0, max_value=100.0, step=0.1, key=f"plant_{current_plant}_discount_percent")
                
                discount_dollars = st.number_input(f"Discount ($ Off):", min_value=0.0, step=0.01, key=f"plant_{current_plant}_discount_dollars")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Add Another Plant"):
                    # Save current plant data
                    st.session_state.plants[current_plant] = {
                        'quantity': quantity,
                        'size': size,
                        'plant_material': clean_text_input(plant_material),
                        'price': price,
                        'discount_percent': discount_percent,
                        'discount_dollars': discount_dollars
                    }
                    st.session_state.plant_count += 1
                    st.rerun()
            
            with col2:
                if st.button("That's All"):
                    # Save current plant data
                    st.session_state.plants[current_plant] = {
                        'quantity': quantity,
                        'size': size,
                        'plant_material': clean_text_input(plant_material),
                        'price': price,
                        'discount_percent': discount_percent,
                        'discount_dollars': discount_dollars
                    }
                    st.session_state.step = 'B'
                    st.rerun()
        
        # Step B: Installation Details
        elif st.session_state.step == 'B':
            st.header("Step B: Installation Details")
            
            col1, col2 = st.columns(2)
            
            with col1:
                origin_location = st.selectbox("Sold From:", ["Frankfort", "Lexington"])
                
                mulch_options = ["Soil Conditioner Only", "Hardwood", "Grade A Cedar", "Eastern Red Cedar", "Redwood", "Pine Bark", "Pine Bark Mini Nuggets", "Pine Bark Nuggets", "Pine Straw"]
                mulch_type = st.selectbox("Mulch Type:", mulch_options)
                
                tree_stakes = st.number_input("Number of Tree Stakes:", min_value=0, step=1)
                
                deer_guards = st.number_input("Number of Deer Guards:", min_value=0, step=1)
                
                install_options = ["Shrubs Only: 97%", "1-3 trees: 97%", "4-6 trees: 91%", "7+ Trees: 85%"]
                installation_type = st.selectbox("Installation Type:", install_options)
            
            with col2:
                st.subheader("Install Address")
                street_address = st.text_input("Street Address:")
                city = st.text_input("City:")
                zip_code = st.text_input("Zip:")
            
            if st.button("Calculate Quote"):
                if street_address and city and zip_code:
                    # Save installation data
                    st.session_state.installation_data = st.session_state.get("installation_data", {})
                    st.session_state.installation_data.update({
                        'origin_location': origin_location,
                        'mulch_type': mulch_type,
                        'tree_stakes_quantity': tree_stakes,
                        'deer_guards_quantity': deer_guards,
                        'installation_type': installation_type,
                        'customer_street_address': clean_text_input(street_address),
                        'customer_city': clean_text_input(city),
                        'customer_zip': zip_code
                    })
                    st.session_state.step = 'C'
                    st.rerun()
                else:
                    st.error("Please fill in all address fields")
        
        # Step C & D: Calculations and Quote Display
        elif st.session_state.step == 'C':
            st.header("Quote Calculation")
            
            with st.spinner("Calculating quote..."):
                pricing_data = calculate_pricing(st.session_state.plants, st.session_state.installation_data)
                st.session_state.pricing_data = pricing_data
            
            if pricing_data:
                st.success("Quote calculated successfully!")
                
                # Display quote details
                st.subheader("Quote Summary")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Plant Materials:** ${pricing_data.get('plant_material_discount_total', 0):.2f}")
                    st.write(f"**Installation Materials:** ${pricing_data.get('installation_material_total', 0):.2f}")
                    st.write(f"**Installation Cost:** ${pricing_data.get('installation_cost', 0):.2f}")
                
                with col2:
                    st.write(f"**Delivery Cost:** ${pricing_data.get('delivery_cost', 0):.2f}")
                    st.write(f"**Subtotal:** ${pricing_data.get('final_subtotal', 0):.2f}")
                    st.write(f"**Tax:** ${pricing_data.get('final_tax', 0):.2f}")
                
                st.markdown(f"### **Total: ${pricing_data.get('final_total', 0):.2f}**")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Move Forward with Quote"):
                        st.session_state.phase = 2
                        st.rerun()
                
                with col2:
                    if st.button("No, Restart"):
                        clear_all_data()
                        st.rerun()
    
    # Phase 2: Customer Data
    elif st.session_state.phase == 2:
        st.header("Customer Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            customer_name = st.text_input("Customer Name:*", key="customer_name")
            customer_email = st.text_input("Email Address:*", key="customer_email")
            customer_phone = st.text_input("Phone Number:*", key="customer_phone")
            customer_subdivision = st.text_input("Subdivision:*", key="customer_subdivision")
            customer_cross_street = st.text_input("Nearest Cross Street:*", key="customer_cross_street")
            
        with col2:
            gate_response = st.radio("Is there a gate?*", ["Yes", "No"], key="gate_response")
            gate_width = st.radio("Is it a minimum of 42\" wide?", ["Yes", "No"], key="gate_width")
            dogs_response = st.radio("Are there dogs?*", ["Yes", "No"], key="dogs_response")
            install_location = st.text_input("Where will this be installed in the yard?*", key="install_location")
            utilities_check = st.radio("Are utilities marked?*", ["Yes", "No"], key="utilities_check")
        
        notes = st.text_area("Notes:", key="notes")
        employee_initials = st.text_input("Employee Initials:", key="employee_initials")
        
        if st.button("Complete"):
            if customer_name and customer_email and customer_phone and customer_subdivision and customer_cross_street:
                # Save customer data
                customer_data = {
                    'customer_name': clean_text_input(customer_name),
                    'customer_email': customer_email,
                    'customer_phone': customer_phone,
                    'customer_subdivision': clean_text_input(customer_subdivision),
                    'customer_cross_street': clean_text_input(customer_cross_street),
                    'gate_response': gate_response,
                    'gate_width': gate_width,
                    'dogs_response': dogs_response,
                    'install_location': clean_text_input(install_location),
                    'utilities_check': utilities_check,
                    'notes': clean_text_input(notes),
                    'employee_initials': clean_text_input(employee_initials)
                }
                
                st.session_state.customer_data = customer_data
                st.session_state.phase = 3
                st.rerun()
            else:
                st.error("Please fill in all required fields marked with *")
    
    # Phase 3: PDF Generation and Completion
    elif st.session_state.phase == 3:
        st.header("Quote Completed!")
        
        st.success("Your quote has been generated successfully!")
        
        # Generate PDF
        pdf_buffer = generate_pdf(
            st.session_state.plants, 
            st.session_state.installation_data, 
            st.session_state.customer_data, 
            st.session_state.pricing_data
        )

        today_str = datetime.datetime.today().strftime("%m%d%Y")
        customer_name_clean = st.session_state.customer_data['customer_name'].replace(" ", "_")
        pdf_filename = f"{customer_name_clean}-{today_str}-Installation.pdf"

        if pdf_buffer:
            st.download_button(
                label="Download PDF",
                data=pdf_buffer,
                file_name=pdf_filename,
                mime="application/pdf"
            )
        
        st.markdown("---")
        col1, col2 = st.columns(2)


        # Clear everything and restart
        with col1:
            if st.button("Create a New Installation"):
                # Clear everything and restart
                clear_all_data()
                st.rerun()


        # Send to Google Sheet Dashboard
        with col2:
            if st.button("Send to Google Sheet Dashboard"):

                # Basic validation
                if not st.session_state.get("customer_data") or not st.session_state.get("installation_data") or not st.session_state.get("pricing_data"):
                    st.error("Missing data — please complete the quote before sending to the dashboard.")

                # Open and edit Google Sheet Dashboard
                else:
                    try:
                        client = get_gspread_client()
                        sheet = client.open_by_key(SHEET_ID).sheet1

                        cust = st.session_state.get("customer_data", {})
                        inst = st.session_state.get("installation_data", {})
                        pricing = st.session_state.get("pricing_data", {})
                        plants_data = st.session_state.get("plants_data", {})

                        customer_name = cust.get("customer_name", "")
                        address = f"{inst.get('customer_street_address','')}, {inst.get('customer_city','')}, KY {inst.get('customer_zip','')}".strip().strip(",")
                        phone = cust.get("customer_phone", "")
                        total_amount = pricing.get("final_total", 0.0)
                        sold_on = datetime.date.today().strftime("%m/%d/%Y")
                        customer_phone = cust.get("customer_phone", "")
                        customer_subdivision = cust.get("customer_subdivision", "")
                        customer_cross_street = cust.get("customer_cross_street", "")
                        install_location = cust.get("install_location", "")
                        notes = cust.get("notes", "")
                        employee_initials = cust.get("employee_initials", "")
                        origin_location = inst.get("origin_location", "")
                        plant_list = "\n".join([f"{p['quantity']} x {p['plant_material']} ({p['size']}) - ${p['price']:.2f}" for p in plants_data.values()])

                        pdf_link = upload_pdf_to_drive(pdf_buffer, pdf_filename)

                        row_data = [
                            customer_name,            # A Customer Name
                            address,                  # B Address
                            phone,                    # C Phone Number
                            f"${total_amount:.2f}",   # D Total Amount
                            "Sold",                   # E Current Status
                            sold_on,                  # F Sold On
                            "",                       # G BUD Called On
                            "",                       # H BUD Clear On
                            "",                       # I Scheduled For
                            "",                       # J Completed
                            pdf_link,                 # K PDF File
                            customer_subdivision,     # L Subdivision (hidden)
                            customer_cross_street,    # M Cross Street (hidden)
                            install_location,         # N Install Location (hidden)
                            employee_initials,        # O Employee Initials (hidden)
                            origin_location,          # P Origin Location (hidden)
                            
                        ]

                        sheet.append_row(row_data, value_input_option='USER_ENTERED')

                        st.success("Install added to Dashboard ✅")

                    except Exception as e:
                        st.error(f"Failed to send to Google Sheet: {e}")

if __name__ == "__main__":
    main()