import streamlit as st
import pandas as pd
import os
import json
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials as BotCredentials

# 1. INITIALIZE PAGE CONFIG AT THE VERY TOP (STRICTLY SET TO WIDE)
st.set_page_config(
    page_title="Meridian Command Console", 
    page_icon="📦", 
    layout="wide",
    initial_sidebar_state="expanded"
)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1wUBZSnB7cJ2T5_iY5_POpfsNmZn0INGj08EdcLc7TsQ/edit?usp=sharing"

# 2. AUDIT LOGGING FUNCTION WITH LOCAL FALLBACK
def log_access(username, role):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        creds_dict = json.loads(st.secrets["google_api"]["credentials"])
        creds = BotCredentials.from_service_account_info(
            creds_dict, 
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_url(SHEET_URL)
        
        try:
            ws = sheet.worksheet("Access_Log")
        except:
            ws = sheet.add_worksheet(title="Access_Log", rows="1000", cols="3")
            ws.append_row(["Timestamp", "Username", "Role"])
        
        ws.append_row([timestamp, username, role])
    except Exception as e:
        log_file = "login_log.csv"
        df_log = pd.read_csv(log_file) if os.path.exists(log_file) else pd.DataFrame(columns=["Timestamp", "Username", "Role"])
        new_row = pd.DataFrame([{"Timestamp": timestamp, "Username": username, "Role": role}])
        df_log = pd.concat([df_log, new_row], ignore_index=True)
        df_log.to_csv(log_file, index=False)

# 3. SESSION STATE INITIALIZATION
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""

# 4. LOGIN UI (HALTS EXECUTION IF NOT AUTHENTICATED)
if not st.session_state["authenticated"]:
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.write("<br><br>", unsafe_allow_html=True)
        with st.form("login_form"):
            st.subheader("🔒 Meridian Command Console")
            st.caption("Please enter your authorized floor credentials.")
            username_input = st.text_input("Username").strip()
            password_input = st.text_input("Password", type="password").strip()
            submit_button = st.form_submit_button("Log In", type="primary", use_container_width=True)
            
            if submit_button:
                users_vault = st.secrets.get("users", {})
                if username_input in users_vault:
                    if str(users_vault[username_input].get("password", "")) == password_input:
                        st.session_state["authenticated"] = True
                        st.session_state["username"] = username_input
                        st.session_state["role"] = users_vault[username_input].get("role", "staff")
                        log_access(username_input, st.session_state["role"])
                        st.rerun()
                    else:
                        st.error("Invalid password provided.")
                else:
                    st.error("Username not recognized in authorized credentials.")
    st.stop()

# 5. AUTHENTICATED TOP BAR (LOGOUT CONTROL)
top_col1, top_col2 = st.columns([8, 1])
with top_col2:
    if st.button(f"🚪 Logout ({st.session_state['username']})", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state["username"] = ""
        st.session_state["role"] = ""
        st.rerun()

# 6. SAFE LAUNCH OF MAIN APPLICATION (ZERO TOUCH TO APP.PY)
# Neutralizes set_page_config to prevent duplicate call crashes when app.py runs
st.set_page_config = lambda *args, **kwargs: None

if os.path.exists("app.py"):
    with open("app.py", encoding="utf-8") as app_file:
        exec(app_file.read(), globals())
else:
    st.error("Fatal Error: app.py was not found in the root directory.")