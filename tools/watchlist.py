import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import os

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
WATCHLIST_SHEET = "watchlist"

def load_watchlist():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)

    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(WATCHLIST_SHEET)
    df = pd.DataFrame(ws.get_all_records())

    df["enabled"] = df["enabled"].astype(bool)
    df["ticker"] = df["ticker"].str.upper()

    return df
