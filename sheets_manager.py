import math
import gspread
from google.oauth2.service_account import Credentials
from datetime import date
import pandas as pd
from config import SERVICE_ACCOUNT_FILE, GOOGLE_SHEETS_ID, HISTORY_SHEET_NAME


def _clean(val):
    """Replace NaN/inf with empty string so gspread can serialise it."""
    if val is None:
        return ''
    try:
        if math.isnan(float(val)) or math.isinf(float(val)):
            return ''
    except (TypeError, ValueError):
        pass
    return val

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

HISTORY_HEADERS = [
    'action_date', 'seller_id', 'campaign_id', 'campaign_type',
    'previous_budget', 'recommended_budget', 'action_type', 'budget_change_pct',
    'rebalancing_score', 'campaign_state',
    'efficiency_score', 'spendability_score', 'stability_score',
    'spend_3d', 'gmv_3d', 'ratio_3d',
    'efficiency_label', 'stability_class',
]


def _get_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_sheet(spreadsheet, name: str, headers: list):
    try:
        ws = spreadsheet.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=10000, cols=len(headers))
        ws.append_row(headers)
    return ws


def read_action_history() -> dict:
    """Returns dict keyed by (seller_id, campaign_id) → latest action row."""
    gc = _get_client()
    ss = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = _get_or_create_sheet(ss, HISTORY_SHEET_NAME, HISTORY_HEADERS)

    records = ws.get_all_records()
    if not records:
        return {}

    df = pd.DataFrame(records)
    df['action_date'] = pd.to_datetime(df['action_date'], errors='coerce')
    df = df.sort_values('action_date', ascending=False)

    # Keep only the most recent row per (seller_id, campaign_id)
    latest = df.drop_duplicates(subset=['seller_id', 'campaign_id'], keep='first')
    history = {}
    for _, row in latest.iterrows():
        key = (str(row['seller_id']), str(row['campaign_id']))
        history[key] = row.to_dict()

    return history


def write_action_history(results: dict):
    """Appends today's recommendations to the history sheet."""
    today = str(date.today())
    gc = _get_client()
    ss = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = _get_or_create_sheet(ss, HISTORY_SHEET_NAME, HISTORY_HEADERS)

    rows = []
    for seller_id, data in results.items():
        for c in data['campaigns']:
            rows.append([
                today,
                seller_id,
                _clean(c['campaign_id']),
                _clean(c['campaign_type']),
                _clean(c['budget']),
                _clean(c['recommended_budget']),
                _clean(c['action_type']),
                _clean(c['budget_change_pct']),
                _clean(c['rebalancing_score']),
                _clean(c['campaign_state']),
                _clean(c['efficiency_score']),
                _clean(c['spendability_score']),
                _clean(c['stability_score']),
                _clean(c['spend_3d']),
                _clean(c['gmv_3d']),
                _clean(c['ratio_3d']) if c['ratio_3d'] != float('inf') else 'inf',
                _clean(c['efficiency_label']),
                _clean(c['stability_class']),
            ])

    if rows:
        ws.append_rows(rows, value_input_option='RAW')
        print(f"  Logged {len(rows)} campaign actions to '{HISTORY_SHEET_NAME}'")
