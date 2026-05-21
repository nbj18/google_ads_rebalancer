import os
import requests
import pandas as pd
from dotenv import load_dotenv
from config import SELLER_IDS

load_dotenv()

METABASE_URL     = os.getenv('METABASE_URL', 'https://metabase.kaip.in').rstrip('/')
METABASE_USER    = os.getenv('METABASE_USERNAME')
METABASE_PASS    = os.getenv('METABASE_PASSWORD')

DB_NUSHOP = 6  # nushop dataset in Metabase


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def get_session_token() -> str:
    resp = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_USER, "password": METABASE_PASS},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()['id']


# ---------------------------------------------------------------------------
# Core fetch helpers
# ---------------------------------------------------------------------------

def _parse_result(result: dict) -> pd.DataFrame:
    cols = [c['name'] for c in result['data']['cols']]
    rows = result['data']['rows']
    return pd.DataFrame(rows, columns=cols)


def run_card(card_id: int, token: str) -> pd.DataFrame:
    resp = requests.post(
        f"{METABASE_URL}/api/card/{card_id}/query",
        headers={"X-Metabase-Session": token},
        json={"parameters": []},
        timeout=120,
    )
    resp.raise_for_status()
    return _parse_result(resp.json())


def run_query(sql: str, database_id: int, token: str) -> pd.DataFrame:
    resp = requests.post(
        f"{METABASE_URL}/api/dataset",
        headers={"X-Metabase-Session": token},
        json={"database": database_id, "native": {"query": sql}, "type": "native"},
        timeout=120,
    )
    resp.raise_for_status()
    return _parse_result(resp.json())


# ---------------------------------------------------------------------------
# Data fetches
# ---------------------------------------------------------------------------

def _seller_list() -> str:
    return ', '.join(f"'{s}'" for s in SELLER_IDS)


def fetch_all(token: str) -> tuple:
    """Returns (campaign_df, be_df, targets_df, week_spend_df)."""

    print("  [1/4] Campaign performance (card 10212)...")
    campaign_df = run_card(10212, token)
    print(f"        {len(campaign_df)} rows, {campaign_df['seller_id'].nunique()} sellers")

    print("  [2/4] Break-even thresholds (card 10216)...")
    be_df = run_card(10216, token)
    print(f"        {len(be_df)} seller rows")

    print("  [3/4] Weekly targets (card 10217)...")
    targets_df = run_card(10217, token)

    print("  [4/4] Current week spend (ad-hoc query)...")
    week_spend_df = run_query(
        f"""
        SELECT
          seller_id,
          ROUND(SUM(spend), 2) AS current_week_spend
        FROM `nushop.google_marketing_insights_master`
        WHERE seller_id IN ({_seller_list()})
          AND spend_date >= DATE_TRUNC(CURRENT_DATE(), WEEK(MONDAY))
          AND spend_date <  CURRENT_DATE()
          AND breakdown_value IS NULL
        GROUP BY seller_id
        """,
        DB_NUSHOP,
        token,
    )
    print(f"        {len(week_spend_df)} seller rows")

    return campaign_df, be_df, targets_df, week_spend_df
