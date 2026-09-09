import streamlit as st
import pandas as pd
from app import load_log_data, get_eta_status, ALL_DOCS
from datetime import datetime

# ==========================================
# 1. PAGE CONFIGURATION & LANDING STATE
# ==========================================
# By setting this file up with set_page_config and running it directly,
# it acts as the exclusive default landing state for the Operational Floor.
st.set_page_config(
    page_title="Staff Dashboard", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. CSS FOR DEPTH, ALIGNMENT, AND SPACING
# ==========================================
st.markdown("""
<style>
    /* Remove white gap above title and maximize screen usage */
    .block-container { padding-top: 1.5rem; max-width: 98% !important; }
    
    /* Title Pop */
    h1 { font-size: 1.8rem !important; margin-bottom: 1rem !important; font-weight: 800; color: #1e293b; text-align: center; }
    
    /* Table Depth & Container Pop */
    div[data-testid="stDataFrame"] {
        box-shadow: 0 8px 16px rgba(0,0,0,0.08);
        border-radius: 8px;
        border: 1px solid #cbd5e1;
        padding: 4px;
        background-color: white;
    }

    /* Center/Middle align headers and enforce text wrap */
    /* Note: Streamlit natively locks headers when a height is passed to st.dataframe */
    div[data-testid="stDataFrame"] th {
        text-align: center !important;
        vertical-align: middle !important;
        white-space: normal !important; 
        background-color: #f1f5f9 !important;
        color: #0f172a !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        border-bottom: 2px solid #cbd5e1 !important;
    }
    
    /* Center/Middle align cells */
    div[data-testid="stDataFrame"] td {
        text-align: center !important;
        vertical-align: middle !important;
        font-size: 13px !important;
        border-bottom: 1px solid #e2e8f0 !important;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 3. CORE DASHBOARD RENDERER
# ==========================================
def render_staff_dashboard():
    st.title("📊 Operational Floor Dashboard")
    
    df_raw = load_log_data()
    if df_raw.empty:
        st.info("No active shipments to display.")
        return
        
    df = df_raw.copy()

    # --- A. DATA SANITIZATION (Ghost Rows & Delivered Purge) ---
    
    # 1. Eradicate Ghost Rows (Rows with no real Row_UID)
    df['Row_UID'] = df['Row_UID'].astype(str).str.strip()
    df = df[(df['Row_UID'] != '') & (df['Row_UID'] != 'nan') & (df['Row_UID'] != 'None')]
    
    # 2. Purge "Delivered" Shipments from the Operational Floor
    df['Shipment Status'] = df['Shipment Status'].astype(str).str.strip()
    df = df[df['Shipment Status'].str.upper() != 'DELIVERED']

    # Stop if the sweep removed everything
    if df.empty:
        st.info("No active inbound shipments to display.")
        return

    # --- B. Timeline Logic & Status Processing ---
    def get_status_label(row):
        ship_status = str(row.get("Shipment Status", ""))
        raw_eta = row.get("ETA")
        timestamp = pd.to_datetime(raw_eta, errors='coerce')
        current_date = timestamp.date() if not pd.isna(timestamp) else datetime.now().date()
        label, _ = get_eta_status(current_date, ship_status)
        return label

    # Apply Status using raw date
    df["Status"] = df.apply(get_status_label, axis=1)

    # --- C. Strict DD/MM/YYYY ETA Formatting ---
    def format_eta(row):
        raw_eta = row.get("ETA", "")
        if pd.isna(raw_eta) or str(raw_eta).strip() == "": 
            return ""
        try:
            return pd.to_datetime(raw_eta).strftime("%d/%m/%Y")
        except:
            return str(raw_eta)
            
    df["ETA"] = df.apply(format_eta, axis=1)

    # --- D. Visual Transformation (Doc Links to ✅/⬜) ---
    doc_cols = [col for col in ALL_DOCS if col in df.columns]
    
    def get_doc_status(row):
        for col in doc_cols:
            if not str(row[col]).startswith("http"):
                return "⏳ PENDING"
        return "✅ READY"

    df["Doc Status"] = df.apply(get_doc_status, axis=1)
    
    for col in doc_cols:
        df[col] = df[col].apply(lambda x: "✅" if str(x).startswith("http") else "⬜")

    df["NALDO"] = df["NALDO"].apply(lambda x: "✅" if str(x).strip().upper() == "YES" else "⬜")
    
    # --- E. Header Ordering & Display Grid Creation ---
    display_cols = ["Total Cartons", "Status", "NALDO", "ETA", "Container #", "Client Name", "Country of Origin", "Invoice No"] + doc_cols + ["Doc Status"]
    df_display = df[display_cols].copy()
    df_display.columns = ["TOTAL CTNS", "Status", "NALDO", "ETA", "Container #", "Client", "Origin", "Invoice#"] + doc_cols + ["Doc Status"]

    # --- F. The "Active Box" Dynamic Buffer ---
    # Append exactly 2 blank rows to the bottom of the sanitized dataset
    blank_row = pd.DataFrame([{col: "" for col in df_display.columns}])
    df_display = pd.concat([df_display, blank_row, blank_row], ignore_index=True)

    # --- G. Full-Row Conditional Styling & NALDO Override ---
    def style_dashboard(row):
        styles = [''] * len(row)
        
        # 1. Base Timeline Highlighting (Applied horizontally across the entire row)
        s = str(row.get('Status', ''))
        row_color = ''
        if 'OVERDUE' in s: 
            row_color = 'background-color: #ffeaea; color: #900000; font-weight: 600;'
        elif 'URGENT' in s: 
            row_color = 'background-color: #fff4d4; color: #855c00; font-weight: 600;'
        elif 'APPROACHING' in s: 
            row_color = 'background-color: #fffae6; color: #827717;'
            
        if row_color:
            styles = [row_color] * len(row)

        # 2. Priority NALDO Override (Stays purple regardless of row timeline color)
        if 'NALDO' in row.index and row['NALDO'] == '✅':
            naldo_idx = row.index.get_loc('NALDO')
            styles[naldo_idx] = 'background-color: #9b59b6; color: white; font-weight: bold;'
            
        return styles

    # --- H. Column Width Optimization (Tightening Binary Columns) ---
    column_config = {
        "TOTAL CTNS": st.column_config.Column("TOTAL CTNS", pinned=True, width="small"),
        "Status": st.column_config.Column("Status", width="medium"),
        "NALDO": st.column_config.Column("NALDO", width="small"),
        "ETA": st.column_config.Column("ETA", width="small"),
        "Container #": st.column_config.Column("Container #", width="medium"),
        "Client": st.column_config.Column("Client", width="medium"),
        "Origin": st.column_config.Column("Origin", width="medium"),
        "Invoice#": st.column_config.Column("Invoice#", width="medium"),
        "Doc Status": st.column_config.Column("Doc Status", width="small")
    }
    # Dynamically clamp all document checklist columns to small width
    for col in doc_cols:
        column_config[col] = st.column_config.Column(col, width="small")

    # --- I. Render the Locked Data Grid ---
    st.dataframe(
        df_display.style.apply(style_dashboard, axis=1), 
        use_container_width=True, 
        hide_index=True,
        column_config=column_config,
        height=700 # Streamlit natively locks headers when height is provided
    )

# ==========================================
# 4. EXECUTION
# ==========================================
if __name__ == "__main__":
    render_staff_dashboard()
