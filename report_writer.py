import gspread
from google.oauth2.service_account import Credentials
from datetime import date
from config import SERVICE_ACCOUNT_FILE, GOOGLE_SHEETS_ID, REPORT_SHEET_NAME

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

ACTION_LABELS = {
    'scale_up':         '⬆ Scale Up (+25%)',
    'scale_up_careful': '↑ Scale Carefully (+15%)',
    'hold':             '→ Hold',
    'hold_cooldown':    '⏸ Hold (Cooldown)',
    'watch_reduce':     '↓ Watch (−5%)',
    'scale_down':       '⬇ Scale Down',
    'pause':            '⏹ Pause',
    'no_budget_data':   '⚠ No Budget Data',
}

STATE_LABELS = {
    'Scale Aggressively': '🟢 Scale Aggressively',
    'Scale Carefully':    '🟡 Scale Carefully',
    'Hold':               '🔵 Hold',
    'Watch':              '🟠 Watch',
    'Reduce':             '🔴 Reduce',
}

PRIORITY_LABELS = {
    'CRITICAL': '🔴 CRITICAL',
    'HIGH':     '🟠 HIGH',
    'MEDIUM':   '🟡 MEDIUM',
}


def _fmt(val, prefix='₹', decimals=0):
    if val is None or val == '':
        return '—'
    if val == float('inf') or val == 'inf':
        return '∞'
    try:
        num = float(val)
        return f"{prefix}{num:,.{decimals}f}" if prefix else f"{num:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _pct(val):
    if val is None:
        return '—'
    try:
        return f"{float(val):.2f}%"
    except (ValueError, TypeError):
        return str(val)


def build_report_rows(results: dict) -> list:
    today = str(date.today())
    rows = []

    rows.append([f'GOOGLE ADS DAILY REBALANCING REPORT — {today}', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''])
    rows.append([])

    for seller_id, data in results.items():
        plan = data['weekly_plan']
        campaigns = data['campaigns']
        alerts = data['alerts']
        realloc = data['reallocation']

        # ── Seller header ──────────────────────────────────────────────
        rows.append([f'━━━ SELLER: {seller_id} ━━━', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''])
        rows.append([])

        # ── Weekly planning summary ────────────────────────────────────
        rows.append(['WEEKLY PLANNING SUMMARY'])
        rows.append([
            'Last Sunday Spend', 'Sunday Target', 'Yesterday Daily Spend',
            'Current Week Spend', 'Remaining Gap (vs Sunday Target)',
            'Required Daily Increase', 'Existing Campaign Capacity',
            'New Structure Req', 'Remaining Days', 'Direction',
        ])
        rows.append([
            _fmt(plan['last_sunday_spend']),
            _fmt(plan['this_week_target']),
            _fmt(plan['yesterday_daily_spend']),
            _fmt(plan['current_week_spend']),
            _fmt(plan['remaining_gap']),
            _fmt(plan['required_daily_pace']),
            _fmt(plan['existing_capacity']),
            _fmt(plan['new_structure_req']),
            plan['remaining_days'],
            plan['direction'],
        ])
        rows.append([])

        # ── Campaign rebalancing table ─────────────────────────────────
        rows.append(['CAMPAIGN ANALYSIS'])
        rows.append([
            'Campaign ID', 'Type',
            'Budget', 'Yesterday Spend', 'Utilization',
            '3D Spend', '3D GMV', '3D Spend/GMV',
            '7D Spend', '7D GMV', '7D Spend/GMV',
            'Target %', 'Break-even %', 'Threshold Source',
            'Efficiency', 'Stability',
            'Eff Score', 'Spend Score', 'Stab Score', 'Rebal Score',
            'State', 'Action', 'Suggested Budget', 'Budget Δ%',
        ])

        for c in sorted(campaigns, key=lambda x: x['rebalancing_score'], reverse=True):
            rows.append([
                c['campaign_id'],
                c['campaign_type'],
                _fmt(c['budget']),
                _fmt(c['yesterday_spend']),
                f"{c['spend_utilization']}%",
                _fmt(c['spend_3d']),
                _fmt(c['gmv_3d']),
                _pct(c['ratio_3d']),
                _fmt(c['spend_7d']),
                _fmt(c['gmv_7d']),
                _pct(c['ratio_7d']),
                _pct(c['target_threshold']),
                _pct(c['be_threshold']),
                c['threshold_source'],
                c['efficiency_label'],
                c['stability_class'],
                c['efficiency_score'],
                c['spendability_score'],
                c['stability_score'],
                c['rebalancing_score'],
                STATE_LABELS.get(c['campaign_state'], c['campaign_state']),
                ACTION_LABELS.get(c['action_type'], c['action_type']),
                _fmt(c['recommended_budget']),
                f"{c['budget_change_pct']:+.1f}%",
            ])

        rows.append([])

        # ── Capital reallocation ───────────────────────────────────────
        rows.append(['CAPITAL REALLOCATION'])
        rows.append(['Role', 'Campaign ID', 'Amount'])
        for d in realloc['donors']:
            rows.append(['Budget Donor', d['campaign_id'], f"−{_fmt(d['freed'])}"])
        for s in realloc['scale_candidates']:
            rows.append(['Scale Candidate', s['campaign_id'], f"+{_fmt(s['added'])}"])
        rows.append(['', 'Total Freed',    _fmt(realloc['total_freed'])])
        rows.append(['', 'Total Deployed', _fmt(realloc['total_deployed'])])
        rows.append(['', 'Net Surplus',    _fmt(realloc['net_surplus'])])
        rows.append([])

        # ── Risk alerts ────────────────────────────────────────────────
        if alerts:
            rows.append(['RISK ALERTS'])
            rows.append(['Priority', 'Campaign ID', 'Message'])
            for a in alerts:
                rows.append([
                    PRIORITY_LABELS.get(a['priority'], a['priority']),
                    a['campaign_id'],
                    a['message'],
                ])
        else:
            rows.append(['RISK ALERTS', 'None'])

        # Separator between sellers
        rows.append([])
        rows.append(['─' * 60])
        rows.append([])

    return rows


def write_report(results: dict):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    ss    = gc.open_by_key(GOOGLE_SHEETS_ID)

    try:
        ws = ss.worksheet(REPORT_SHEET_NAME)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=REPORT_SHEET_NAME, rows=5000, cols=26)

    rows = build_report_rows(results)

    # Pad all rows to equal column width to avoid API errors
    max_cols = max(len(r) for r in rows) if rows else 1
    padded   = [r + [''] * (max_cols - len(r)) for r in rows]

    ws.update(padded, value_input_option='RAW')
    print(f"  Report written to '{REPORT_SHEET_NAME}' tab ({len(rows)} rows)")
