import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os
pd.options.mode.string_storage = "python"  # <-- PREVENTS PYARROW LINUX SEGFAULT
import base64
import gspread
import json
import jinja2
import re
import tempfile
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as HumanCredentials
from google.oauth2.service_account import Credentials as BotCredentials
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. GLOBAL SETUP & CSS
# ==========================================
st.set_page_config(page_title="Meridian Command Console", page_icon="📦", layout="wide")

COMPANY_LOGO_PATH = "company_logo.png"

def to_decimal(val):
    """Sanitizes and converts to standard float to prevent PyArrow serialization crashes."""
    try:
        if isinstance(val, (int, float)):
            return round(float(val), 2)
        clean_val = re.sub(r'[^\d.-]', '', str(val))
        return round(float(clean_val), 2)
    except:
        return 0.00

def safe_qty_parse(val):
    """Defensive parsing to prevent crashes."""
    try:
        if isinstance(val, (int, float)): return int(val)
        val_str = str(val).replace(",", "").strip()
        if not val_str or val_str.lower() in ['nan', 'none', 'n/a']: return 0
        return int(float(val_str))
    except:
        return 0

st.markdown("""
<style>
    .stApp {
        background-color: #ffffff;
        background-image: 
            linear-gradient(45deg, #f8f9fa 25%, transparent 25%, transparent 75%, #f8f9fa 75%, #f8f9fa), 
            linear-gradient(45deg, #f8f9fa 25%, transparent 25%, transparent 75%, #f8f9fa 75%, #f8f9fa);
        background-size: 20px 20px;
        background-position: 0 0, 10px 10px;
    }
    [data-testid="stExpander"] {
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.04);
        margin-bottom: 10px;
    }
    [data-testid="stExpander"] summary p {
        font-weight: 600 !important;
        color: #1e293b !important;
        font-size: 1.05rem !important;
    }
    [data-testid="stExpander"] p, 
    [data-testid="stExpander"] h3, 
    [data-testid="stExpander"] h4, 
    [data-testid="stExpander"] h5 {
        color: #1e293b !important;
    }
</style>
""", unsafe_allow_html=True)

for folder in ["uploaded_docs", "logos", "signatures", "watermarks", "templates"]:
    if not os.path.exists(folder): os.makedirs(folder)

# ==========================================
# 2. CONSTANTS & DATA SCHEMA
# ==========================================
SHEET_URL = "https://docs.google.com/spreadsheets/d/1wUBZSnB7cJ2T5_iY5_POpfsNmZn0INGj08EdcLc7TsQ/edit?usp=sharing"
ROOT_FOLDER_ID = "1CITSPAI-BoFeQQLLkmeoX2wkjunTbpGm"

ALL_COUNTRIES = [
    "", "USA", "China", "UK", "Canada", "Brazil", "Mexico", "Panama", "Japan", "Germany", 
    "India", "France", "Italy", "South Korea", "Spain", "Australia", "Taiwan", 
    "Netherlands", "Vietnam", "Malaysia", "Singapore", "South Africa", "UAE", 
    "Saudi Arabia", "Switzerland", "Sweden", "Poland", "Belgium", "Thailand", 
    "Indonesia", "Turkey", "Philippines", "Ireland", "Other"
]

SYSTEM_DOCS = ["Commercial Invoice", "CARICOM Invoice", "Sequential Packing List", "Official Duties Assessment"]
EXTERNAL_DOCS = ["Bill of Lading Scan", "Original Invoice", "Original Packing List", "Tracker Document", "Other Documents", "Miscellaneous Supporting Doc"]
ALL_DOCS = SYSTEM_DOCS + EXTERNAL_DOCS

LOG_COLUMNS = [
    "Row_UID", "Invoice No", "Client Name", "Container #", "Country of Origin", "ETA", 
    "Lodged Status", "Shipment Status", "NALDO", "Total Cartons", "B/L Number", "Freight", "Cargo Notes",
    "Commercial Invoice", "CARICOM Invoice", "Sequential Packing List", "Official Duties Assessment", 
    "Bill of Lading Scan", "Original Invoice", "Original Packing List", "Tracker Document", 
    "Other Documents", "Miscellaneous Supporting Doc"
]

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def get_gspread_client():
    creds_dict = json.loads(st.secrets["google_api"]["credentials"])
    creds = BotCredentials.from_service_account_info(
        creds_dict, 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]
    )
    return gspread.authorize(creds)

def get_drive_service():
    token_dict = json.loads(st.secrets["google_drive_human"]["token"])
    creds = HumanCredentials.from_authorized_user_info(token_dict)
    return build('drive', 'v3', credentials=creds)

def load_log_data():
    try: 
        ws = get_gspread_client().open_by_url(SHEET_URL).sheet1
        rows = ws.get_all_values()
        
        if not rows or len(rows) < 2:
            return pd.DataFrame(columns=LOG_COLUMNS)
        
        headers = rows[0]
        data = rows[1:]
        
        df = pd.DataFrame(data, columns=headers, dtype=object)
        
        for col in LOG_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception as e: 
        st.error(f"Failed to load data: {e}")
        return pd.DataFrame(columns=LOG_COLUMNS)

def save_log_data(df):
    try:
        ws = get_gspread_client().open_by_url(SHEET_URL).sheet1
        ws.clear()
        
        df = df.copy()
        for col in df.columns:
            df[col] = df[col].astype(str).replace(['nan', 'None'], '')
            
        for col in LOG_COLUMNS:
            if col not in df.columns: df[col] = ""
        df = df[LOG_COLUMNS]
        ws.update([df.columns.values.tolist()] + df.values.tolist())
        return True
    except Exception as e:
        st.error(f"Failed to sync with Google Sheets: {e}")
        return False

def upload_system_pdf_to_drive(html_content, file_name, client_name, invoice_no):
    if not html_content: return "Pending Upload"
    try:
        # PURE PYTHON PDF ENGINE - NO LINUX SEGFAULTS
        from xhtml2pdf import pisa 
        
        drive = get_drive_service()
        safe_client_name = str(client_name).replace("'", "\\'")
        safe_invoice_no = str(invoice_no).replace("'", "\\'")
        
        folders = drive.files().list(q=f"name='{safe_client_name}' and '{ROOT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false", fields="files(id, name)").execute().get('files', [])
        client_folder_id = folders[0]['id'] if folders else drive.files().create(body={"name": client_name, "parents": [ROOT_FOLDER_ID], "mimeType": "application/vnd.google-apps.folder"}).execute()['id']
        
        inv_folders = drive.files().list(q=f"name='{safe_invoice_no}' and '{client_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false", fields="files(id, name)").execute().get('files', [])
        inv_folder_id = inv_folders[0]['id'] if inv_folders else drive.files().create(body={"name": str(invoice_no), "parents": [client_folder_id], "mimeType": "application/vnd.google-apps.folder"}).execute()['id']
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf_path = temp_pdf.name
            
        with open(temp_pdf_path, "w+b") as result_file:
            pisa_status = pisa.CreatePDF(html_content, dest=result_file)
            
        if pisa_status.err:
            st.error(f"PDF generation error for {file_name}")
            if os.path.exists(temp_pdf_path): os.remove(temp_pdf_path)
            return "Upload Failed"
        
        pdf_media = MediaFileUpload(temp_pdf_path, mimetype='application/pdf', resumable=True)
        
        existing_files = drive.files().list(q=f"name='{file_name}' and '{inv_folder_id}' in parents and trashed=false", fields="files(id, webViewLink)").execute().get('files', [])
        
        if existing_files:
            file_id = existing_files[0]['id']
            final_pdf = drive.files().update(fileId=file_id, media_body=pdf_media, fields='id, webViewLink').execute()
        else:
            pdf_metadata = {'name': file_name, 'parents': [inv_folder_id]}
            final_pdf = drive.files().create(body=pdf_metadata, media_body=pdf_media, fields='id, webViewLink').execute()
        
        if os.path.exists(temp_pdf_path): os.remove(temp_pdf_path)
        return final_pdf.get('webViewLink', 'Upload Failed')
    except Exception as e:
        st.error(f"PDF Engine Error for {file_name}: {e}")
        return "Upload Failed"

def upload_physical_file_to_drive(uploaded_file, file_name, client_name, invoice_no):
    if not uploaded_file: return None
    try:
        drive = get_drive_service()
        safe_client_name = str(client_name).replace("'", "\\'")
        safe_invoice_no = str(invoice_no).replace("'", "\\'")
        
        folders = drive.files().list(q=f"name='{safe_client_name}' and '{ROOT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false", fields="files(id, name)").execute().get('files', [])
        client_folder_id = folders[0]['id'] if folders else drive.files().create(body={"name": client_name, "parents": [ROOT_FOLDER_ID], "mimeType": "application/vnd.google-apps.folder"}).execute()['id']
        
        inv_folders = drive.files().list(q=f"name='{safe_invoice_no}' and '{client_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false", fields="files(id, name)").execute().get('files', [])
        inv_folder_id = inv_folders[0]['id'] if inv_folders else drive.files().create(body={"name": str(invoice_no), "parents": [client_folder_id], "mimeType": "application/vnd.google-apps.folder"}).execute()['id']
        
        file_ext = os.path.splitext(uploaded_file.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_path = temp_file.name
            
        media = MediaFileUpload(temp_path, resumable=True)

        existing_files = drive.files().list(q=f"name='{file_name}' and '{inv_folder_id}' in parents and trashed=false", fields="files(id, webViewLink)").execute().get('files', [])
        
        if existing_files:
            file_id = existing_files[0]['id']
            file = drive.files().update(fileId=file_id, media_body=media, fields='id, webViewLink').execute()
        else:
            file_metadata = {'name': file_name, 'parents': [inv_folder_id]}
            file = drive.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        if os.path.exists(temp_path): os.remove(temp_path)
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"Drive Upload Error: {e}")
        return None

def get_eta_status(eta_date, shipment_status):
    if shipment_status == "Delivered":
        return "✅ DELIVERED", "#00b050"
    try:
        days_diff = (eta_date - datetime.now().date()).days
        if days_diff < 0: return "⚠️ OVERDUE", "#FF4500"
        if 0 <= days_diff <= 7: return "🔴 URGENT", "#FF0000"
        if 8 <= days_diff <= 14: return "🟡 APPROACHING", "#FFD700"
        return "🟢 IN TRANSIT", "#008000"
    except: return "TBD", "#808080"

def get_img_b64(path):
    if os.path.exists(path):
        with open(path, "rb") as f: return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
    return None

def get_entity_profile(file_name, entity_name):
    profile = {"Name": entity_name, "Address": "Main Office Hub", "Template": "classic.html"}
    if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
        df = pd.read_csv(file_name)
        match = df[df["Name"] == entity_name]
        if not match.empty:
            for col in df.columns: profile[col] = match.iloc[0][col]
    return profile

def get_supplier_mapping(supplier):
    if os.path.exists("supplier_mappings.csv") and os.path.getsize("supplier_mappings.csv") > 0:
        df = pd.read_csv("supplier_mappings.csv")
        match = df[df["Supplier"] == supplier]
        if not match.empty: return match.iloc[0]["DescCol"], match.iloc[0]["QtyCol"], match.iloc[0]["PriceCol"]
    return "-- Select --", "-- Select --", "-- Select --"

def save_supplier_mapping(supplier, desc, qty, price):
    df = pd.read_csv("supplier_mappings.csv") if os.path.exists("supplier_mappings.csv") else pd.DataFrame(columns=["Supplier", "DescCol", "QtyCol", "PriceCol"])
    df = df[df["Supplier"] != supplier]
    df = pd.concat([df, pd.DataFrame([{"Supplier": supplier, "DescCol": desc, "QtyCol": qty, "PriceCol": price}])], ignore_index=True)
    df.to_csv("supplier_mappings.csv", index=False)

# ==========================================
# 4. DOCUMENT GENERATORS
# ==========================================

def generate_caricom_printout(inv_num, date, client_name, client_address, supplier_name, supplier_address, bl, total_ctns, subtotal, freight, grand_total, payment_terms, additional_notes, signatory_position, compliance_data, logo_path, sig_path, orientation, primary_hex):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath="./templates"))
    template = env.get_template("caricom_template.html")
    return template.render(
        inv_num=inv_num, date=date, client_name=client_name, client_address=client_address,
        supplier_name=supplier_name, supplier_address=supplier_address, bl=bl, total_ctns=total_ctns,
        subtotal=f"{subtotal:,.2f}", freight=f"{freight:,.2f}", grand_total=f"{grand_total:,.2f}", 
        payment_terms=payment_terms, additional_notes=additional_notes, 
        signatory_position=signatory_position, compliance_data=compliance_data, 
        logo_path=logo_path, sig_path=sig_path, orientation=orientation, primary_hex=primary_hex
    )

def generate_html_document(title, inv_no, date, client, c_addr, supplier, s_profile, bl, total_ctns, df, total_val, freight=None, additional_notes="", payment_terms="", signatory_position="", is_packing=False, is_duties=False, duty_data=None):
    logo_path = get_img_b64(f"logos/{s_profile.get('Name', '')}_logo.png")
    sig_path = get_img_b64(f"signatures/{s_profile.get('Name', '')}_sig.png")

    if is_packing:
        table_rows = ""
        for idx, row in df.iterrows():
            qty = safe_qty_parse(row.get("QUANTITY", 0))
            table_rows += f'<tr><td style="padding:10px; border:1px solid #ccc;">{row.get("SPECIFICATION OF COMMODITIES","N/A")}</td><td style="padding:10px; border:1px solid #ccc; text-align:center;">{row.get("CTNS NOS","N/A")}</td><td style="padding:10px; border:1px solid #ccc; text-align:center;">{row.get("TOTAL CTNS",0)}</td><td style="padding:10px; border:1px solid #ccc; text-align:right;">{qty:,}</td></tr>'
        
        img_tag = f'<img src="{logo_path}" height="40">' if logo_path else ''
        sig_tag = f'<img src="{sig_path}" height="80">' if sig_path else ''
        
        rendered_html = f'<html><head><style>@page {{ margin: 20mm; }} body {{ font-family: Arial, sans-serif; color: #333333; }}</style></head><body><table width="100%" style="border: none;"><tr><td style="border: none;">{img_tag}</td><td align="right" style="border: none;"><h2>{title}</h2></td></tr></table><p><b>Exporter:</b> {supplier}<br><b>Consignee:</b> {client}<br>{c_addr}</p><table border="1" width="100%" cellspacing="0" cellpadding="5"><thead><tr bgcolor="#f7f7f7"><th>Description</th><th>Carton Nos</th><th>Total Ctns</th><th>Qty</th></tr></thead><tbody>{table_rows}</tbody></table><br><br><div align="right">{sig_tag}<br><b>{signatory_position}</b></div></body></html>'
    
    elif is_duties:
        duty_data = duty_data or {}
        img_tag = f'<img src="{logo_path}" height="40">' if logo_path else ''
        rendered_html = f'<html><head><style>@page {{ margin: 20mm; }} body {{ font-family: Arial, sans-serif; color: #333333; }}</style></head><body><table width="100%" style="border: none;"><tr><td style="border: none;">{img_tag}</td><td align="right" style="border: none;"><h2>{title}</h2></td></tr></table><p><b>Invoice:</b> {inv_no}</p><p>Converted Base Value: ${duty_data.get("convert_to_ttd",0):,.2f} TTD</p><p>Customs Duty: ${duty_data.get("duty_owed",0):,.2f} TTD</p><p>VAT Owed: ${duty_data.get("vat_owed",0):,.2f} TTD</p><br><table border="1" width="100%" cellspacing="0" cellpadding="10"><tr><td bgcolor="#f9f9f9"><h3>Total Customs Bill Due: ${duty_data.get("grand_total_ttd",0):,.2f} TTD</h3></td></tr></table></body></html>'
    
    else:
        template_env = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath="./templates"))
        chosen_template = s_profile.get("Template", "classic.html")
        if not os.path.exists(f"./templates/{chosen_template}"): chosen_template = "classic.html"
        try: 
            template = template_env.get_template(chosen_template)
        except: 
            template = template_env.from_string("<h1>{{title}}</h1><p><b>Exporter:</b> {{supplier_name}}<br><b>Consignee:</b> {{client_name}}</p><table border='1' width='100%' cellspacing='0' cellpadding='5'><thead><tr bgcolor='#f2f2f2'><th>Description</th><th>Qty</th><th>Total</th></tr></thead><tbody>{% for item in items %}<tr><td>{{item.Description}}</td><td>{{item.Qty}}</td><td>{{item.Total}}</td></tr>{% endfor %}</tbody></table>")

        items = []
        for idx, row in df.iterrows():
            desc = str(row["Description"])[:250]
            parsed_qty = safe_qty_parse(row.get('Qty', 0))
            qty = f"{parsed_qty:,}" if parsed_qty else ""
            try:
                price = f"{float(row.get('UnitPrice', 0)):.2f}" if pd.notna(row.get('UnitPrice')) else ""
            except ValueError:
                price = ""
            try:
                total = f"{float(row.get('Total Foreign (USD)', 0)):.2f}" if pd.notna(row.get('Total Foreign (USD)')) else ""
            except ValueError:
                total = ""
                
            items.append({"Description": desc, "Qty": qty, "UnitPrice": price, "Total": total})
            
        rendered_html = template.render({
            "title": title, "inv_no": inv_no, "date": date, "client_name": client, 
            "client_address": c_addr, "supplier_name": supplier, 
            "supplier_address": s_profile.get("Address", "Main Office Hub"), 
            "bl": bl, "total_ctns": total_ctns, "payment_terms": payment_terms, 
            "additional_notes": additional_notes, "primary_hex": s_profile.get("PrimaryHex", "#0A2240"), 
            "logo_path": logo_path, "sig_path": sig_path, "signatory_position": signatory_position, 
            "subtotal": f"{total_val:,.2f}", "freight": (f"{freight:,.2f}" if freight else None), 
            "grand_total": f"{(total_val + (freight or 0)):,.2f}", "items": items
        })
        rendered_html = re.sub(r'>\$\s*<', '><', rendered_html)

    return rendered_html

def display_html_preview(raw_html):
    preview_html = f'<div style="background-color: white; padding: 40px; margin: 10px auto; border-radius: 5px; box-shadow: 0px 4px 10px rgba(0,0,0,0.1); max-width: 900px; color: #333333;">{raw_html}</div>'
    components.html(preview_html, height=750, scrolling=True)


# ==========================================
# 5. APP VIEWS (THE "PAGES")
# ==========================================

def render_master_log():
    st.title("🗄️ Master Log: Logistics Control Tower")
    df = load_log_data()

    if df.empty:
        st.info("No data found in the Master Log. Create a new shell to begin.")
    else:
        for idx, row in df.iterrows():
            row_uid = str(row.get('Row_UID', ''))
            if not row_uid.strip():
                continue 
                
            inv_no = str(row.get('Invoice No', ''))
            display_inv = inv_no if inv_no.strip() else "[Blank Entry]"
            client_name = str(row.get('Client Name', 'Unknown Client'))
            ship_status = str(row.get("Shipment Status", "Active"))
            total_cartons = str(row.get("Total Cartons", "0"))
            
            raw_eta = row.get("ETA")
            timestamp = pd.to_datetime(raw_eta, errors='coerce')
            current_date = timestamp.date() if not pd.isna(timestamp) else datetime.now().date()
            status_label, _ = get_eta_status(current_date, ship_status)
            
            naldo_val = str(row.get("NALDO", "No")).strip().upper()
            naldo_display = f"🔴 NALDO: YES" if naldo_val == "YES" else f"⚪ NALDO: NO"
            
            header_text = (f"📦 TOTAL CTNS: {total_cartons} | {status_label} | ETA: {current_date} | "
                           f"Client: {client_name} | Origin: {row.get('Country of Origin', 'N/A')} | "
                           f"Lodged: {row.get('Lodged Status', 'N/A')} | {naldo_display} | INV: {display_inv}")

            with st.expander(header_text):
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                with col1: new_cont = st.text_input("Container #", value=str(row.get("Container #", "")), key=f"cont_{idx}")
                with col2: new_orig = st.selectbox("Country of Origin", ALL_COUNTRIES, index=ALL_COUNTRIES.index(row.get("Country of Origin", "")) if row.get("Country of Origin", "") in ALL_COUNTRIES else 0, key=f"orig_{idx}")
                with col3: new_eta = st.date_input("ETA", value=current_date, key=f"eta_{idx}")
                with col4: new_lodg = st.radio("Lodged", ["Yes", "No"], index=0 if row.get("Lodged Status") == "Yes" else 1, horizontal=True, key=f"lodged_{idx}")
                with col5: new_stat = st.selectbox("Shipment Status", ["Active", "Delivered"], index=0 if ship_status != "Delivered" else 1, key=f"stat_{idx}")
                with col6: new_naldo = st.radio("NALDO Code", ["Yes", "No"], index=0 if naldo_val == "YES" else 1, horizontal=True, key=f"naldo_{idx}")
                
                col7, col8 = st.columns(2)
                with col7: new_bl = st.text_input("B/L Number", value=str(row.get("B/L Number", "")), key=f"bl_{idx}")
                with col8: new_freight = st.text_input("Freight (USD)", value=str(row.get("Freight", "")), key=f"fr_{idx}")

                st.write("---")
                st.subheader("Document Vault (10-Slot Matrix)")
                
                grid = st.columns(5)
                upload_cache = {} 

                for i, slot in enumerate(ALL_DOCS):
                    with grid[i % 5]:
                        st.markdown(f"**{slot}**")
                        file_link = str(row.get(slot, ""))
                        
                        if file_link.startswith("http"):
                            clean_link = file_link
                            match = re.search(r'/d/([a-zA-Z0-9_-]+)', file_link)
                            if match:
                                file_id = match.group(1)
                                clean_link = f"https://drive.google.com/uc?export=download&id={file_id}"
                            st.link_button("📄 View Document", url=clean_link, key=f"view_{idx}_{i}", use_container_width=True)
                        else:
                            st.button("Pending Upload", disabled=True, key=f"pend_{idx}_{i}", use_container_width=True)
                        
                        if slot in EXTERNAL_DOCS:
                            uploaded_file = st.file_uploader(f"Upload {slot}", key=f"up_{idx}_{i}", label_visibility="collapsed")
                            if uploaded_file:
                                upload_cache[slot] = uploaded_file
                
                if st.button("💾 Save Shipment Updates", key=f"save_{idx}", type="primary"):
                    with st.spinner("Processing updates..."):
                        df_update = load_log_data()
                        row_index = df_update.index[df_update['Row_UID'].astype(str).str.strip() == row_uid.strip()].tolist()[0]
                        df_update.at[row_index, "Container #"] = new_cont
                        df_update.at[row_index, "Country of Origin"] = new_orig
                        df_update.at[row_index, "ETA"] = str(new_eta)
                        df_update.at[row_index, "Lodged Status"] = new_lodg
                        df_update.at[row_index, "Shipment Status"] = new_stat
                        df_update.at[row_index, "NALDO"] = new_naldo
                        df_update.at[row_index, "B/L Number"] = str(new_bl).strip()
                        df_update.at[row_index, "Freight"] = str(new_freight).strip()
                        
                        for slot_name, up_file in upload_cache.items():
                            doc_filename = f"{inv_no if inv_no.strip() else row_uid}_{slot_name.replace(' ', '_')}.pdf"
                            new_link = upload_physical_file_to_drive(up_file, doc_filename, client_name, inv_no if inv_no.strip() else row_uid)
                            if new_link: df_update.at[row_index, slot_name] = new_link
                            
                        if save_log_data(df_update):
                            st.success("✅ Updates saved!")
                            st.rerun()

def render_admin_tracker():
    st.title("📦 Command Console: Master Tracker")
    
    active_shell_uid = st.session_state.get("active_shell_uid", "")
    if not active_shell_uid or active_shell_uid == "-- Choose Active Workspace --":
        st.warning("⚠️ Access Restriction: Please create or select an Active Workspace Shell from the top menu to enable data intake.")
        return

    df_current = load_log_data()
    
    match_row = df_current[df_current['Row_UID'].astype(str).str.strip() == active_shell_uid.strip()]
    row_data = match_row.iloc[0] if not match_row.empty else {}
    def get_val(key, default=""): return row_data.get(key, default)

    def sync_base_metadata_to_log(df_active, inv_num, c_name, ctns, date, bl_num, freight_val, cargo_notes):
        df_active['Row_UID'] = df_active['Row_UID'].astype(str).str.strip()
        matches = df_active.index[df_active['Row_UID'] == active_shell_uid.strip()].tolist()
        
        if matches:
            idx = matches[0]
            df_active.at[idx, "Client Name"] = str(c_name)
            df_active.at[idx, "Total Cartons"] = str(ctns)
            df_active.at[idx, "ETA"] = str(date)
            df_active.at[idx, "Invoice No"] = str(inv_num).strip()
            df_active.at[idx, "B/L Number"] = str(bl_num).strip()
            df_active.at[idx, "Freight"] = str(freight_val).strip()
            df_active.at[idx, "Cargo Notes"] = str(cargo_notes).strip()
        else:
            new_row = {col: "" for col in LOG_COLUMNS}
            new_row["Row_UID"] = active_shell_uid.strip()
            new_row["Invoice No"] = str(inv_num).strip()
            new_row["Client Name"] = str(c_name)
            new_row["Total Cartons"] = str(ctns)
            new_row["ETA"] = str(date)
            new_row["Shipment Status"] = "Active"
            new_row["B/L Number"] = str(bl_num).strip()
            new_row["Freight"] = str(freight_val).strip()
            new_row["Cargo Notes"] = str(cargo_notes).strip()
            df_active = pd.concat([df_active, pd.DataFrame([new_row])], ignore_index=True)
        return df_active

    client_file = "clients.csv"
    supplier_file = "suppliers.csv"
    client_options = ["Select a Client..."] + sorted(pd.read_csv(client_file)["Name"].dropna().tolist()) if os.path.exists(client_file) and os.path.getsize(client_file) > 0 else ["Select a Client..."]
    supplier_options = ["Select a Supplier..."] + sorted(pd.read_csv(supplier_file)["Name"].dropna().tolist()) if os.path.exists(supplier_file) and os.path.getsize(supplier_file) > 0 else ["Select a Supplier..."]

    st.write("---")
    col1, col2 = st.columns([1, 1.3])

    with col1:
        st.subheader("Data Intake & Matrix Mapping")
        
        client_val = get_val("Client Name", "Select a Client...")
        client_idx = client_options.index(client_val) if client_val in client_options else 0
        client_name = st.selectbox("Client Workspace", client_options, index=client_idx)
        
        supplier_name = st.selectbox("Supplier Profile", supplier_options)
        
        supplier_profile = get_entity_profile("suppliers.csv", supplier_name)
        client_profile = get_entity_profile("clients.csv", client_name)
        
        uploaded_file = st.file_uploader("Drop Raw Vendor Spreadsheet (CSV or Excel)", type=["csv", "xlsx"])
        saved_desc, saved_qty, saved_price = get_supplier_mapping(supplier_name)
        map_description, map_qty, map_price = "-- Select --", "-- Select --", "-- Select --"
        
        if uploaded_file is not None:
            df_raw = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            all_columns = list(df_raw.dropna(how='all').columns)
            cm1, cm2, cm3 = st.columns(3)
            with cm1: map_description = st.selectbox("Description Column", ["-- Select --"] + all_columns, index=all_columns.index(saved_desc)+1 if saved_desc in all_columns else 0)
            with cm2: map_qty = st.selectbox("Quantity Column", ["-- Select --"] + all_columns, index=all_columns.index(saved_qty)+1 if saved_qty in all_columns else 0)
            with cm3: map_price = st.selectbox("Unit Price Column", ["-- Select --"] + all_columns, index=all_columns.index(saved_price)+1 if saved_price in all_columns else 0)
            if map_description != "-- Select --" and (map_description != saved_desc or map_qty != saved_qty or map_price != saved_price):
                if st.button("Save Column Translation Matrix"):
                    save_supplier_mapping(supplier_name, map_description, map_qty, map_price)
                    st.success("Matrix Mapped!")

        st.write("---")
        st.markdown("#### Logistics Manifest Fields")
        cx1, cx2 = st.columns(2)
        with cx1:
            invoice_num = st.text_input("Invoice Number", value=get_val("Invoice No", ""))
            invoice_date = st.text_input("Invoice Date / ETA", value=get_val("ETA", datetime.now().strftime("%Y-%m-%d")))
            bl_number = st.text_input("Bill of Lading (BL#)", value=get_val("B/L Number", ""))
            payment_terms = st.selectbox("Terms", ["NET 90 Days", "NET 45 Days", "NET 30 Days"])
            special_indicator = st.selectbox("Shipment Type", ["Standard", "Express", "Maritime Direct"])
        with cx2:
            freight_cost = st.number_input("Ocean Freight (USD)", value=float(to_decimal(get_val("Freight", 2500.00))))
            carton_val = safe_qty_parse(get_val("Total Cartons", 0))
            container_total_ctns = st.number_input("Total Cartons", value=int(carton_val))
            exchange_rate = st.number_input("Exchange Rate", value=6.77967, format="%.5f")
            signatory_position = st.text_input("Signatory Position", value="Authorized Director")
            
        additional_notes = st.text_area("Cargo Notes", value=get_val("Cargo Notes", "Assorted cargo bulk manifest"))

        st.markdown("#### Tariff Tax Parameters")
        tx1, tx2 = st.columns(2)
        with tx1: duty_percentage = st.number_input("Duty Rate (%)", value=20.0)
        with tx1: vat_percentage = st.number_input("VAT Rate (%)", value=12.5)
        with tx2: ces_fee = st.number_input("CES Fee (TTD)", value=1050.00)
        with tx2: uf_fee = st.number_input("UF Fee (TTD)", value=80.00)

    with col2:
        st.subheader("Targeted Document Generation (Save Independently)")
        
        df_clean = pd.DataFrame(columns=["Description", "Qty", "UnitPrice", "Total Foreign (USD)"])
        subtotal_foreign = 0.00
        freight_dec = to_decimal(freight_cost)
        ex_rate = float(exchange_rate)
        
        duty_dict = {'exchange_rate': ex_rate, 'convert_to_ttd': 0.00, 'duty_owed': 0.00, 'vat_owed': 0.00, 'fixed_fees': float(ces_fee) + float(uf_fee), 'grand_total_ttd': 0.00}
        
        if uploaded_file and map_description != "-- Select --" and map_qty != "-- Select --" and map_price != "-- Select --":
            df_clean = df_raw[[map_description, map_qty, map_price]].dropna().copy()
            df_clean.columns = ["Description", "Qty", "UnitPrice"]
            
            # STRICT TYPE CASTING TO PREVENT PYARROW C++ CRASHES
            df_clean["Description"] = df_clean["Description"].astype(str)
            df_clean["Qty"] = pd.to_numeric(df_clean["Qty"], errors='coerce').fillna(0).astype(int)
            df_clean["UnitPrice"] = df_clean["UnitPrice"].apply(to_decimal)
            
            df_clean["Total Foreign (USD)"] = df_clean.apply(lambda x: round(float(x['Qty']) * x['UnitPrice'], 2), axis=1)
            subtotal_foreign = float(df_clean["Total Foreign (USD)"].sum())
            
            convert_to_ttd = round((subtotal_foreign + freight_dec) * ex_rate, 2)
            duty_owed = round(convert_to_ttd * (float(duty_percentage) / 100.0), 2)
            vat_owed = round((convert_to_ttd + duty_owed) * (float(vat_percentage) / 100.0), 2)
            
            ces_fee_dec = float(ces_fee)
            uf_fee_dec = float(uf_fee)
            grand_total_ttd = round(duty_owed + vat_owed + ces_fee_dec + uf_fee_dec, 2)
            
            duty_dict = {
                'exchange_rate': ex_rate, 
                'convert_to_ttd': convert_to_ttd, 
                'duty_owed': duty_owed, 
                'vat_owed': vat_owed, 
                'fixed_fees': ces_fee_dec + uf_fee_dec, 
                'grand_total_ttd': grand_total_ttd
            }
            
            file_state_hash = f"{uploaded_file.name}_{supplier_name}_{client_name}"
            if "active_file_hash" not in st.session_state or st.session_state["active_file_hash"] != file_state_hash:
                st.session_state["active_file_hash"] = file_state_hash
                
                # STRICTLY TYPE THE EDITOR DATAFRAME TO PREVENT STREAMLIT SEGFAULT
                base_pck_df = df_raw[[map_description, map_qty]].dropna().copy()
                base_pck_df.columns = ["SPECIFICATION OF COMMODITIES", "QUANTITY"]
                base_pck_df["SPECIFICATION OF COMMODITIES"] = base_pck_df["SPECIFICATION OF COMMODITIES"].astype(str)
                base_pck_df["QUANTITY"] = pd.to_numeric(base_pck_df["QUANTITY"], errors='coerce').fillna(0).astype(int)
                base_pck_df["TOTAL CTNS"] = 0
                st.session_state["pck_working_df"] = base_pck_df

        t_inv, t_car, t_pck, t_dut = st.tabs(["📄 Invoice", "🌐 CARICOM", "📋 Packing Manifest", "🇹🇹 Customs Audit"])
        
        with t_inv:
            if st.button("⚙️ Preview Commercial Invoice"): 
                st.session_state["h_inv"] = generate_html_document("COMMERCIAL INVOICE", invoice_num, invoice_date, client_name, client_profile.get("Address",""), supplier_name, supplier_profile, bl_number, container_total_ctns, df_clean, subtotal_foreign, freight_dec, additional_notes, payment_terms, signatory_position)
            if "h_inv" in st.session_state: 
                display_html_preview(st.session_state["h_inv"])
                
                if st.button("💾 Save Commercial Invoice Only", type="primary", use_container_width=True):
                    with st.spinner("Locking Commercial Invoice PDF to Drive Vault..."):
                        inv_link = upload_system_pdf_to_drive(st.session_state["h_inv"], f"{(invoice_num if invoice_num.strip() else active_shell_uid)}_Commercial_Invoice.pdf", client_name, invoice_num if invoice_num.strip() else active_shell_uid)
                        df_update = load_log_data()
                        df_update = sync_base_metadata_to_log(df_update, invoice_num, client_name, container_total_ctns, invoice_date, bl_number, freight_cost, additional_notes)
                        idx = df_update.index[df_update['Row_UID'].astype(str).str.strip() == active_shell_uid.strip()].tolist()[0]
                        df_update.at[idx, "Commercial Invoice"] = inv_link
                        save_log_data(df_update)
                        st.success("✅ Commercial Invoice locked!")
                
        with t_car:
            orientation = st.radio("Document Orientation", ["portrait", "landscape"], index=1)
            
            with st.expander("📝 Customs Compliance Details (CARICOM)", expanded=True):
                cc1, cc2 = st.columns(2)
                cust_order_no = cc1.text_input("Customer's Order No.")
                country_origin = cc2.text_input("Country of Origin", "USA")
                port_loading = cc1.text_input("Port of Loading")
                port_discharge = cc2.text_input("Port of Discharge")
                final_dest = cc1.text_input("Final Destination", "Trinidad & Tobago")
                mode_transport = cc2.selectbox("Mode", ["SHIP", "AIR", "COURIER", "OTHER"])

            comp_data = {
                "cust_order_no": cust_order_no, 
                "country_origin": country_origin,
                "port_loading": port_loading, 
                "port_discharge": port_discharge,
                "final_dest": final_dest, 
                "mode_transport": mode_transport
            }

            logo_path = get_img_b64(f"logos/{supplier_profile.get('Name', '')}_logo.png")
            sig_path = get_img_b64(f"signatures/{supplier_profile.get('Name', '')}_sig.png")

            if st.button("⚙️ Preview CARICOM"): 
                st.session_state["h_car"] = generate_caricom_printout(
                    invoice_num, invoice_date, client_name, client_profile.get("Address",""), 
                    supplier_name, supplier_profile.get("Address",""), bl_number, container_total_ctns, 
                    subtotal_foreign, freight_dec, subtotal_foreign + freight_dec, 
                    payment_terms, additional_notes, signatory_position, comp_data, 
                    logo_path, sig_path, orientation, supplier_profile.get("PrimaryHex", "#000000")
                )
            
            if "h_car" in st.session_state: 
                display_html_preview(st.session_state["h_car"])
                
                if st.button("💾 Save CARICOM Invoice Only", type="primary", use_container_width=True):
                    with st.spinner("Locking CARICOM Invoice..."):
                        html_car_final = generate_caricom_printout(
                            invoice_num, invoice_date, client_name, client_profile.get("Address",""), 
                            supplier_name, supplier_profile.get("Address",""), bl_number, container_total_ctns, 
                            subtotal_foreign, freight_dec, subtotal_foreign + freight_dec, 
                            payment_terms, additional_notes, signatory_position, comp_data, 
                            logo_path, sig_path, orientation, supplier_profile.get("PrimaryHex", "#000000")
                        )
                        link = upload_system_pdf_to_drive(html_car_final, f"{(invoice_num if invoice_num.strip() else active_shell_uid)}_CARICOM.pdf", client_name, invoice_num if invoice_num.strip() else active_shell_uid)
                        
                        df_update = load_log_data()
                        df_update = sync_base_metadata_to_log(df_update, invoice_num, client_name, container_total_ctns, invoice_date, bl_number, freight_cost, additional_notes)
                        idx = df_update.index[df_update['Row_UID'].astype(str).str.strip() == active_shell_uid.strip()].tolist()[0]
                        df_update.at[idx, "CARICOM Invoice"] = link
                        save_log_data(df_update)
                        st.success("✅ CARICOM Locked!")
                
        with t_pck:
            if "pck_working_df" in st.session_state:
                st.markdown("##### Interactive Packing Line Sheet")
                with st.form("packing_matrix_form"):
                    edited_pck_df = st.data_editor(st.session_state["pck_working_df"], disabled=["SPECIFICATION OF COMMODITIES", "QUANTITY"], key="pck_table_editor", width="stretch")
                    submit_packing = st.form_submit_button("⚙️ Generate & Preview Packing List", type="primary")

                if submit_packing:
                    st.session_state["pck_working_df"] = edited_pck_df
                    calculated_rows = []
                    box_cursor = 1
                    for idx, row in edited_pck_df.iterrows():
                        assigned_ctns = int(row.get("TOTAL CTNS", 0))
                        if assigned_ctns > 0:
                            end_box = box_cursor + assigned_ctns - 1
                            range_str = f"{box_cursor}-{end_box}" if box_cursor != end_box else f"{box_cursor}"
                            box_cursor = end_box + 1
                        else: range_str = "0"
                        calculated_rows.append({"SPECIFICATION OF COMMODITIES": row["SPECIFICATION OF COMMODITIES"], "QUANTITY": row["QUANTITY"], "TOTAL CTNS": assigned_ctns, "CTNS NOS": range_str})
                    
                    df_p_compiled = pd.DataFrame(calculated_rows)
                    st.session_state["df_p_compiled"] = df_p_compiled
                    st.session_state["h_pck"] = generate_html_document("PACKING LIST MANIFEST", invoice_num, invoice_date, client_name, client_profile.get("Address",""), supplier_name, supplier_profile, bl_number, container_total_ctns, df_p_compiled, subtotal_foreign, freight_dec, additional_notes, payment_terms, signatory_position, is_packing=True)
            else:
                st.info("Upload and map a vendor spreadsheet to enable interactive packing validation.")
                
            if "h_pck" in st.session_state: 
                display_html_preview(st.session_state["h_pck"])
                
                if st.button("💾 Save Packing Manifest Only", type="primary", use_container_width=True):
                    with st.spinner("Locking Packing Manifest PDF to Drive Vault..."):
                        html_pck_final = generate_html_document("PACKING LIST MANIFEST", invoice_num, invoice_date, client_name, client_profile.get("Address",""), supplier_name, supplier_profile, bl_number, container_total_ctns, st.session_state.get("df_p_compiled", df_clean), subtotal_foreign, freight_dec, additional_notes, payment_terms, signatory_position, is_packing=True)
                        pck_link = upload_system_pdf_to_drive(html_pck_final, f"{(invoice_num if invoice_num.strip() else active_shell_uid)}_Sequential_Packing_List.pdf", client_name, invoice_num if invoice_num.strip() else active_shell_uid)
                        df_update = load_log_data()
                        df_update = sync_base_metadata_to_log(df_update, invoice_num, client_name, container_total_ctns, invoice_date, bl_number, freight_cost, additional_notes)
                        idx = df_update.index[df_update['Row_UID'].astype(str).str.strip() == active_shell_uid.strip()].tolist()[0]
                        df_update.at[idx, "Sequential Packing List"] = pck_link
                        save_log_data(df_update)
                        st.success("✅ Packing Manifest locked!")
                
        with t_dut:
            if st.button("⚙️ Preview Customs Summary"): 
                st.session_state["h_dut"] = generate_html_document("OFFICIAL DUTIES ASSESSMENT", invoice_num, invoice_date, client_name, client_profile.get("Address",""), supplier_name, supplier_profile, bl_number, container_total_ctns, st.session_state.get("df_p_compiled", df_clean), subtotal_foreign, freight_dec, additional_notes, payment_terms, signatory_position, is_duties=True, duty_data=duty_dict)
            if "h_dut" in st.session_state: 
                display_html_preview(st.session_state["h_dut"])
                
                if st.button("💾 Save Customs Summary Only", type="primary", use_container_width=True):
                    with st.spinner("Locking Customs Summary PDF to Drive Vault..."):
                        html_dut_final = generate_html_document("OFFICIAL DUTIES ASSESSMENT", invoice_num, invoice_date, client_name, client_profile.get("Address",""), supplier_name, supplier_profile, bl_number, container_total_ctns, st.session_state.get("df_p_compiled", df_clean), subtotal_foreign, freight_dec, additional_notes, payment_terms, signatory_position, is_duties=True, duty_data=duty_dict)
                        dut_link = upload_system_pdf_to_drive(html_dut_final, f"{(invoice_num if invoice_num.strip() else active_shell_uid)}_Official_Duties.pdf", client_name, invoice_num if invoice_num.strip() else active_shell_uid)
                        df_update = load_log_data()
                        df_update = sync_base_metadata_to_log(df_update, invoice_num, client_name, container_total_ctns, invoice_date, bl_number, freight_cost, additional_notes)
                        idx = df_update.index[df_update['Row_UID'].astype(str).str.strip() == active_shell_uid.strip()].tolist()[0]
                        df_update.at[idx, "Official Duties Assessment"] = dut_link
                        save_log_data(df_update)
                        st.success("✅ Customs Summary locked!")

# ==========================================
# 6. NEW ADMIN RENDERERS
# ==========================================

def render_supplier_admin():
    st.title("⚙️ Supplier Admin")
    st.write("Register new supplier profiles below to sync into the cloud matrix.")
    fields = ['Name', 'Address', 'Palette', 'Typography', 'Header', 'GeoInv', 'Orient', 'PackOrient', 'WMToggle', 'WMOpacity', 'PrimaryHex', 'SecondaryHex', 'FontSize', 'LogoAlign', 'TableStyle', 'Template']
    with st.form("new_supplier_form"):
        data = {f: st.text_input(f) for f in fields}
        if st.form_submit_button("Save New Supplier"):
            if not data['Name']: 
                st.error("Name is required!")
            else:
                df_csv = pd.read_csv("suppliers.csv") if os.path.exists("suppliers.csv") else pd.DataFrame(columns=fields)
                df_csv = pd.concat([df_csv, pd.DataFrame([data])], ignore_index=True)
                df_csv.to_csv("suppliers.csv", index=False)
                
                try:
                    ws = get_gspread_client().open_by_url(SHEET_URL).worksheet("Suppliers")
                    ws.clear()
                    ws.update([df_csv.columns.values.tolist()] + df_csv.fillna("").values.tolist())
                    st.success("✅ Supplier saved locally and synced to Sheets matrix!")
                except Exception as e:
                    st.warning(f"Saved locally, but missing 'Suppliers' tab on Google Sheet to sync: {e}")

def render_client_admin():
    st.title("👥 Client Admin")
    st.write("Register new client profiles below to sync into the cloud matrix.")
    fields = ['Name', 'Address', 'Contact', 'Email', 'Phone', 'Notes']
    with st.form("new_client_form"):
        data = {f: st.text_input(f) for f in fields}
        if st.form_submit_button("Save New Client"):
            if not data['Name']: 
                st.error("Name is required!")
            else:
                df_csv = pd.read_csv("clients.csv") if os.path.exists("clients.csv") else pd.DataFrame(columns=fields)
                df_csv = pd.concat([df_csv, pd.DataFrame([data])], ignore_index=True)
                df_csv.to_csv("clients.csv", index=False)
                
                try:
                    ws = get_gspread_client().open_by_url(SHEET_URL).worksheet("Clients")
                    ws.clear()
                    ws.update([df_csv.columns.values.tolist()] + df_csv.fillna("").values.tolist())
                    st.success("✅ Client saved locally and synced to Sheets matrix!")
                except Exception as e:
                    st.warning(f"Saved locally, but missing 'Clients' tab on Google Sheet to sync: {e}")


# ==========================================
# 7. TOP NAVIGATION & WORKSPACE ROUTER
# ==========================================

if "active_module" not in st.session_state:
    st.session_state["active_module"] = "📋 Master Log"

st.write("<br>", unsafe_allow_html=True)

col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(4)
with col_nav1:
    if st.button("📋 Master Log", use_container_width=True): st.session_state["active_module"] = "📋 Master Log"
with col_nav2:
    if st.button("📦 Master Tracker", use_container_width=True): st.session_state["active_module"] = "📦 Master Tracker"
with col_nav3:
    if st.button("⚙️ Supplier Admin", use_container_width=True): st.session_state["active_module"] = "⚙️ Supplier Admin"
with col_nav4:
    if st.button("👥 Client Admin", use_container_width=True): st.session_state["active_module"] = "👥 Client Admin"

st.write("---")

col_create, col_select = st.columns([1, 2])

with col_create:
    if st.button("➕ Create Empty Shipment Shell", type="primary", use_container_width=True):
        with st.spinner("Initializing Workspace Shell..."):
            df_current = load_log_data()
            new_uid = f"UID-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            blank_row = {col: "" for col in LOG_COLUMNS}
            blank_row["Row_UID"] = new_uid
            blank_row["Invoice No"] = ""
            blank_row["Total Cartons"] = 0
            blank_row["Shipment Status"] = "Active"
            blank_row["NALDO"] = "No"
            blank_row["Lodged Status"] = "No"
            blank_row["B/L Number"] = ""
            blank_row["Freight"] = ""
            blank_row["Cargo Notes"] = ""
            for doc_slot in ALL_DOCS: blank_row[doc_slot] = "Pending Upload"
            
            df_new = pd.concat([df_current, pd.DataFrame([blank_row])], ignore_index=True)
            if save_log_data(df_new):
                st.session_state["active_shell_uid"] = new_uid
                st.toast("Empty Workspace Shell successfully generated!", icon="✅")
                st.rerun()

with col_select:
    df_dropdown = load_log_data()
    dropdown_options = ["-- Choose Active Workspace --"]
    
    if not df_dropdown.empty:
        for _, r in df_dropdown.iterrows():
            r_uid = str(r.get("Row_UID", "")).strip()
            s_id = str(r.get("Invoice No", "")).strip()
            s_ctns = str(r.get("Total Cartons", "")).strip()
            s_client = str(r.get("Client Name", "")).strip()
            
            if not r_uid: 
                continue
            
            display_name = s_id if s_id.strip() else "[Blank Entry]"
            label = f"[{r_uid}] INV: {display_name}"
            if s_client: label += f" | Client: {s_client}"
            if s_ctns and s_ctns != "0" and s_ctns != "": label += f" | Cartons: {s_ctns}"
            dropdown_options.append(label)

    current_target_uid = st.session_state.get("active_shell_uid", "")
    matching_indices = [i for i, opt in enumerate(dropdown_options) if f"[{current_target_uid}]" in opt]
    default_sel_idx = matching_indices[0] if matching_indices and current_target_uid else 0

    selected_option = st.selectbox("Select Target Workspace", dropdown_options, index=default_sel_idx, label_visibility="collapsed")
    
    if selected_option != "-- Choose Active Workspace --":
        match = re.search(r'\[(.*?)\]', selected_option)
        if match:
            st.session_state["active_shell_uid"] = match.group(1)
    else:
        st.session_state["active_shell_uid"] = ""

st.write("---")

# --- CORE APPLICATION EXECUTION ---
if st.session_state["active_module"] == "📋 Master Log":
    render_master_log()
elif st.session_state["active_module"] == "📦 Master Tracker":
    render_admin_tracker()
elif st.session_state["active_module"] == "⚙️ Supplier Admin":
    render_supplier_admin()
elif st.session_state["active_module"] == "👥 Client Admin":
    render_client_admin()