import streamlit as st
import googlemaps
import requests
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io
import re
import math

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
        api_key = st.secrets.get("GOOGLE_MAPS_API_KEY", "")
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
        total_mulch_quantity = round(total_mulch_quantity)
        total_soil_quantity = round(total_soil_quantity)
        total_tablet_quantity = round(total_tablet_quantity)
        
        # CHANGE PRICING HERE - Update these values if pricing changes
        tablet_unit_price = 0.75
        soil_conditioner_unit_price = 9.99
        deer_guard_unit_price = 3.99
        tree_stake_unit_price = 36.00
        
        # Mulch pricing by type
        mulch_type = installation_data.get('mulch_type', '')
        if mulch_type == "Soil Conditioner Only":
            mulch_unit_price = 9.99
        elif mulch_type in ["Hardwood", "Eastern Red Cedar", "Pine Bark", "Pine Bark Mini Nuggets", "Pine Bark Nuggets"]:
            mulch_unit_price = 8.99
        elif mulch_type in ["Grade A Cedar", "Redwood"]:
            mulch_unit_price = 16.99
        elif mulch_type == "Pine Straw":
            mulch_unit_price = 15.99
        else:
            mulch_unit_price = 8.99  # Default
        
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
            'total_tablet_quantity': total_tablet_quantity
        }
        
    except Exception as e:
        st.error(f"Error in pricing calculations: {e}")
        return {}

# STEP 5: PDF generation
def generate_pdf(plants_data, installation_data, customer_data, pricing_data):
    """Generate PDF quote document"""
    try:
        buffer = io.BytesIO()
        doc = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # PDF Header
        doc.setFont("Helvetica-Bold", 16)
        doc.drawString(50, height - 50, "Landscaping Installation Quote")
        
        y_position = height - 100
        doc.setFont("Helvetica", 12)
        
        # Customer Information
        doc.drawString(50, y_position, f"Customer: {customer_data.get('customer_name', '')}")
        y_position -= 20
        doc.drawString(50, y_position, f"Email: {customer_data.get('customer_email', '')}")
        y_position -= 20
        doc.drawString(50, y_position, f"Phone: {customer_data.get('customer_phone', '')}")
        y_position -= 30
        
        # Installation Details
        doc.setFont("Helvetica-Bold", 14)
        doc.drawString(50, y_position, "Installation Details")
        y_position -= 20
        doc.setFont("Helvetica", 10)
        
        for plant_id, plant in plants_data.items():
            doc.drawString(50, y_position, f"{plant.get('quantity', 0)} x {plant.get('plant_material', '')} ({plant.get('size', '')}) - ${plant.get('price', 0):.2f}")
            y_position -= 15
        
        y_position -= 20
        doc.setFont("Helvetica-Bold", 12)
        doc.drawString(50, y_position, f"Total: ${pricing_data.get('final_total', 0):.2f}")
        
        doc.save()
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        st.error(f"Error generating PDF: {e}")
        return None

# STEP 6: Zapier integration
def send_to_zapier(plants_data, installation_data, customer_data, pricing_data):
    """Send data to Zapier webhook"""
    try:
        webhook_url = st.secrets.get("zapier", {}).get("webhook_url", "")
        if not webhook_url:
            st.warning("Zapier webhook URL not found in secrets - skipping database integration")
            return True
            
        payload = {
            "plants": plants_data,
            "installation": installation_data,
            "customer": customer_data,
            "pricing": pricing_data
        }
        
        response = requests.post(webhook_url, json=payload)
        
        if response.status_code == 200:
            st.success("Data sent to database successfully!")
            return True
        else:
            st.error(f"Error sending data to database: {response.status_code}")
            return False
            
    except Exception as e:
        st.error(f"Error with Zapier integration: {e}")
        return False

# STEP 7: Main application interface
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
                    st.session_state.installation_data = {
                        'origin_location': origin_location,
                        'mulch_type': mulch_type,
                        'tree_stakes_quantity': tree_stakes,
                        'deer_guards_quantity': deer_guards,
                        'installation_type': installation_type,
                        'customer_street_address': clean_text_input(street_address),
                        'customer_city': clean_text_input(city),
                        'customer_zip': zip_code
                    }
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
        
        if pdf_buffer:
            st.download_button(
                label="Download PDF",
                data=pdf_buffer,
                file_name="landscaping_quote.pdf",
                mime="application/pdf"
            )
        
        # Send to Zapier
        send_to_zapier(
            st.session_state.plants, 
            st.session_state.installation_data, 
            st.session_state.customer_data, 
            st.session_state.pricing_data
        )
        
        if st.button("Create a New Installation"):
            clear_all_data()
            st.rerun()

if __name__ == "__main__":
    main()
