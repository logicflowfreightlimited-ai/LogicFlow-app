from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

print("Starting Google Drive Handshake...")

try:
    # 1. Grab the robot's badge
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)

    print("Badge accepted. Attempting to drop a test file into the Vault...")

    # 2. Create a tiny dummy text file
    DRIVE_FOLDER_ID = "19pHVBp63Y2j8y5BKPujV78rbwBVeYuBk"
    file_metadata = {'name': 'ROBOT_TEST_FILE.txt', 'parents': [DRIVE_FOLDER_ID]}
    
    dummy_content = b"Hello from the Meridian Bot! The vault connection is secure."
    media = MediaIoBaseUpload(io.BytesIO(dummy_content), mimetype='text/plain', resumable=True)
    
    # 3. Fire it into the cloud
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    
    print(f"✅ SUCCESS! File uploaded successfully. Go check your Google Drive!")

except Exception as e:
    print(f"\n❌ ERROR CAUGHT: {e}")