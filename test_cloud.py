import gspread

print("Starting the handshake...")

# 1. Grab the secret robot badge
gc = gspread.service_account(filename="credentials.json")

# 2. Try to open the new cloud database
print("Badge accepted. Attempting to open the Google Sheet...")
sh = gc.open_by_url("https://docs.google.com/spreadsheets/d/1ipB1DaIdX_BS_0iSWRHMwHcP-wEpfu2pZzFT3nJtlho/edit?gid=0#gid=0")

print("✅ SUCCESS! The Meridian-Bot has successfully entered the Cloud Database!")