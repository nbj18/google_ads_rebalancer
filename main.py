import sys
import io
import json
import math
from datetime import date, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
        if isinstance(obj, (date, datetime)):
            return str(obj)
        return super().default(obj)


def save_results_json(results: dict):
    payload = {'run_date': str(date.today()), 'sellers': results}
    with open('latest_results.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, cls=_SafeEncoder, indent=2)
    print("  latest_results.json saved")

from data_fetcher import get_session_token, fetch_all
from engine import run_all_sellers
from sheets_manager import read_action_history, write_action_history
from report_writer import write_report


def main():
    today = date.today()
    print(f"\n{'='*60}")
    print(f"  Google Ads Rebalancing Engine — {today}")
    print(f"{'='*60}\n")

    # ── 1. Authenticate with Metabase ──────────────────────────────────
    print("Authenticating with Metabase...")
    token = get_session_token()
    print("  ✓ Session token obtained\n")

    # ── 2. Fetch data ──────────────────────────────────────────────────
    print("Fetching data from Metabase...")
    campaign_df, be_df, targets_df, week_spend_df = fetch_all(token)

    # ── 3. Load action history ─────────────────────────────────────────
    print("\nLoading action history from Google Sheets...")
    history = read_action_history()
    print(f"  {len(history)} historical campaign records loaded")

    # ── 4. Run rebalancing engine ──────────────────────────────────────
    print("\nRunning rebalancing engine...")
    results = run_all_sellers(campaign_df, be_df, targets_df, week_spend_df, history)
    print(f"  Analysed {len(results)} sellers")

    # ── 5. Console summary ─────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("  SUMMARY")
    print("─" * 60)
    for seller_id, data in results.items():
        plan    = data['weekly_plan']
        n_scale  = sum(1 for c in data['campaigns'] if 'scale_up' in c['action_type'])
        n_reduce = sum(1 for c in data['campaigns'] if c['action_type'] in ('scale_down', 'pause', 'watch_reduce'))
        n_alerts = len(data['alerts'])
        print(
            f"  {seller_id[:12]}...  "
            f"Gap: ₹{plan['remaining_gap']:>8,.0f}  "
            f"Pace: ₹{plan['required_daily_pace']:>6,.0f}/day  "
            f"Cmpgns: {len(data['campaigns'])}  "
            f"↑{n_scale} ↓{n_reduce}  "
            f"Alerts: {n_alerts}"
        )
    print("─" * 60)

    # ── 6. Save JSON for web app ───────────────────────────────────────
    print("\nSaving results...")
    save_results_json(results)

    # ── 7. Write to Google Sheets ──────────────────────────────────────
    print("\nWriting to Google Sheets...")
    write_report(results)
    write_action_history(results)

    print(f"\n✓ Done — {today}\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        raise
