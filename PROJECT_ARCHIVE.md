"Source of Truth":

The Goal: A secure, mobile-optimized logistics portal for Majestic Freight Forwarders.

The Tech Stack: Python, Streamlit, and GitHub.

Key Components:

0_Gatekeeper.py: Contains the login logic and security walls.

3_Master_Log.py: Contains the document vault and the "Nuclear Bypass" logic for Google Drive direct file viewing.

Critical Secrets: Note down that the app relies on st.secrets["google_drive_human"] for authentication and that the root folder ID is 19pHVBp63Y2j8y5BKPujV78rbwBVeYuBk.

Custom Hacks: Explicitly mention: "The app uses a regex bypass in 3_Master_Log.py to convert Google Drive /view links to export=view to bypass mobile login prompts."

2. Document Your "Admin" Workflow
Add a section in that file called "Standard Operating Procedures":

Describe how you corrected invoice discrepancies (e.g., how you coordinate Corrected_Commercial_Invoice.xlsx and Corrected_Packing_List.xlsx).

List the contact information for your key staff, Elton and Smallman, so you remember they are the authorized users for the onboarding process.

3. Archive Your "Correction Ledger"
If you ever make specific changes to the logic, update this PROJECT_ARCHIVE.md file. In six months, all you will need to do is open that file, copy its contents, and paste them into a new chat with me.

This allows you to "re-feed" me the entire history of the project in one single message.

4. Backup the Data Structure
Keep a copy of your current clients.csv and master_log_database.csv (or a link to your Master Google Sheet) in that archive file.

If the structure of your data changes, you will have a record of what it looked like when it was working perfectly.
