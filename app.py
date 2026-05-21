import json, math, io
from datetime import date, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="ShopDeck · Budget Rebalancer",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1rem; padding-bottom: 1rem; }

  .top-header {
    display: flex; align-items: center; justify-content: space-between;
    background: #0f172a; color: white;
    padding: 14px 24px; border-radius: 10px; margin-bottom: 18px;
  }
  .top-header .brand { font-size: 18px; font-weight: 700; letter-spacing: -.3px; }
  .top-header .brand span { color: #38bdf8; }
  .top-header .meta { font-size: 12px; color: #94a3b8; }

  .badge {
    display: inline-block; padding: 3px 10px;
    border-radius: 20px; font-size: 11px; font-weight: 700;
    letter-spacing: .3px; white-space: nowrap;
  }
  .badge-profit     { background:#dcfce7; color:#15803d; }
  .badge-breakeven  { background:#fef9c3; color:#92400e; }
  .badge-loss       { background:#fee2e2; color:#b91c1c; }
  .badge-underspend { background:#dbeafe; color:#1d4ed8; }
  .badge-ontarget   { background:#dcfce7; color:#15803d; }
  .badge-overspend  { background:#fce7f3; color:#9d174d; }
  .badge-scale      { background:#dcfce7; color:#166534; }
  .badge-hold       { background:#dbeafe; color:#1e40af; }
  .badge-reduce     { background:#fee2e2; color:#991b1b; }
  .badge-watch      { background:#ffedd5; color:#9a3412; }

  .metric-card {
    background: white; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.05);
  }
  .metric-card .label { font-size: 11px; font-weight: 600; color: #64748b;
    text-transform: uppercase; letter-spacing: .5px; margin-bottom: 6px; }
  .metric-card .value { font-size: 22px; font-weight: 700; color: #0f172a; }
  .metric-card .sub   { font-size: 12px; color: #94a3b8; margin-top: 2px; }
  .metric-card .pos   { color: #16a34a; }
  .metric-card .neg   { color: #dc2626; }

  .alert-critical { background:#fef2f2; border-left:4px solid #dc2626;
    padding:10px 14px; border-radius:6px; margin-bottom:8px; }
  .alert-high     { background:#fffbeb; border-left:4px solid #f59e0b;
    padding:10px 14px; border-radius:6px; margin-bottom:8px; }
  .alert-medium   { background:#eff6ff; border-left:4px solid #3b82f6;
    padding:10px 14px; border-radius:6px; margin-bottom:8px; }
  .alert-text     { font-size:13px; color:#1e293b; }
  .alert-name     { font-weight:700; color:#0f172a; }
  .alert-id       { font-size:11px; color:#64748b; font-family:monospace; }

  .section-title {
    font-size:15px; font-weight:700; color:#0f172a;
    margin:20px 0 10px; padding-bottom:6px;
    border-bottom:2px solid #e2e8f0;
  }
  .row-count { font-size:13px; color:#64748b; margin-bottom:8px; }

  .summary-kpi {
    background: white; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 14px 18px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,.05);
  }
  .summary-kpi .sk-label { font-size:11px; font-weight:600; color:#64748b;
    text-transform:uppercase; letter-spacing:.5px; }
  .summary-kpi .sk-value { font-size:26px; font-weight:800; margin:4px 0 2px; }
  .summary-kpi .sk-sub   { font-size:11px; color:#94a3b8; }
  .kpi-green { color:#16a34a; }
  .kpi-red   { color:#dc2626; }
  .kpi-blue  { color:#2563eb; }
  .kpi-amber { color:#d97706; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_float(val):
    if val is None or val == '': return None
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None

def fmt_inr(val):
    v = safe_float(val)
    if v is None: return '—'
    return f"₹{v:,.0f}"

def badge(text, cls):
    return f'<span class="badge {cls}">{text}</span>'

def account_status(metrics):
    r3  = safe_float(metrics.get('ratio_3d'))
    tgt = safe_float(metrics.get('be_target'))
    be  = safe_float(metrics.get('be_0pct'))
    if r3 is None or tgt is None or be is None: return 'Unknown', 'badge-hold'
    if r3 < tgt: return 'Profit',    'badge-profit'
    if r3 < be:  return 'Breakeven', 'badge-breakeven'
    return 'Loss', 'badge-loss'

def gap_status(gap):
    g = safe_float(gap)
    if g is None: return 'Unknown', 'badge-hold'
    if g > 500:   return 'Underspend', 'badge-underspend'
    if g < -500:  return 'Overspend',  'badge-overspend'
    return 'On Target', 'badge-ontarget'

def metric_card(col, label, value, sub='', pos=None):
    sub_cls = 'pos' if pos is True else ('neg' if pos is False else '')
    col.markdown(f"""
    <div class="metric-card">
      <div class="label">{label}</div>
      <div class="value">{value}</div>
      <div class="sub {sub_cls}">{sub}</div>
    </div>""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_results():
    try:
        with open('latest_results.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def campaigns_to_df(campaigns):
    rows = []
    for c in campaigns:
        rows.append({
            'Campaign ID':    str(c['campaign_id']),
            'Name':           c.get('campaign_name', ''),
            'Status':         c.get('campaign_status', ''),
            'Type':           c['campaign_type'],
            'Budget':         safe_float(c['budget']),
            'Rec Budget':     safe_float(c['recommended_budget']),
            'Δ%':             safe_float(c['budget_change_pct']),
            '3D Spend/GMV%':  safe_float(c['ratio_3d']),
            'Target%':        safe_float(c['target_threshold']),
            'Break-even%':    safe_float(c['be_threshold']),
            'Utilization%':   safe_float(c['spend_utilization']),
            'Score':          safe_float(c['rebalancing_score']),
            'State':          c['campaign_state'],
            'Action':         c['action_type'].replace('_',' ').title(),
            'Efficiency':     c['efficiency_label'],
            'Stability':      c['stability_class'],
        })
    return pd.DataFrame(rows)

def build_excel(sellers):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        ov = []
        for sid, sd in sellers.items():
            p = sd['weekly_plan']; cs = sd['campaigns']
            status, _ = account_status(sd.get('account_metrics', {}))
            gap_lbl, _ = gap_status(p['remaining_gap'])
            ov.append({
                'Seller Name': sd.get('seller_name', ''), 'Seller ID': sid,
                'Status': status, 'Gap Status': gap_lbl,
                'Last Sunday': p['last_sunday_spend'], 'Target': p['this_week_target'],
                'Yesterday': p['yesterday_daily_spend'], 'Gap': p['remaining_gap'],
                'Pace/Day': p['required_daily_pace'], 'Direction': p['direction'],
                'Campaigns': len(cs),
                'Scale': sum(1 for c in cs if 'scale_up' in c['action_type']),
                'Reduce': sum(1 for c in cs if c['action_type'] in ('scale_down','pause','watch_reduce')),
                'Alerts': len(sd['alerts']),
            })
        pd.DataFrame(ov).to_excel(w, sheet_name='Overview', index=False)
        for sid, sd in sellers.items():
            tab_name = (sd.get('seller_name') or sid)[:31]
            campaigns_to_df(sd['campaigns']).to_excel(w, sheet_name=tab_name, index=False)
    buf.seek(0)
    return buf.getvalue()

def get_remaining_days():
    today = date.today()
    return 7 - today.weekday()

def get_day_labels(remaining_days):
    today = date.today()
    return [(today + timedelta(days=i)).strftime('%a %d') for i in range(remaining_days)]

def generate_written_summary(sellers, run_date):
    """Build a narrative weekly summary from the rebalancing data."""
    all_camps = [c for s in sellers.values() for c in s['campaigns']]

    # Profitability
    profit_buckets = {'Profit': [], 'Breakeven': [], 'Loss': [], 'Unknown': []}
    for sid, s in sellers.items():
        st_label, _ = account_status(s.get('account_metrics', {}))
        profit_buckets[st_label].append(s.get('seller_name') or sid[:12])

    # Spend alignment + totals
    gap_buckets = {'Underspend': [], 'On Target': [], 'Overspend': []}
    total_yesterday = total_target = total_gap = 0
    for sid, s in sellers.items():
        plan = s['weekly_plan']
        y = safe_float(plan['yesterday_daily_spend']) or 0
        t = safe_float(plan['this_week_target']) or 0
        g = safe_float(plan['remaining_gap']) or 0
        total_yesterday += y
        total_target    += t
        total_gap       += g
        gl, _ = gap_status(g)
        gap_buckets[gl].append(s.get('seller_name') or sid[:12])

    # Actions
    action_map = {}
    for c in all_camps:
        action_map[c['action_type']] = action_map.get(c['action_type'], 0) + 1
    n_scale_up   = sum(v for k, v in action_map.items() if 'scale_up' in k)
    n_hold       = action_map.get('hold', 0) + action_map.get('hold_cooldown', 0)
    n_watch      = action_map.get('watch_reduce', 0)
    n_scale_dn   = action_map.get('scale_down', 0)
    n_pause      = action_map.get('pause', 0)

    # Budget reallocation
    total_freed    = sum(s['reallocation']['total_freed']    for s in sellers.values())
    total_deployed = sum(s['reallocation']['total_deployed'] for s in sellers.values())

    # Alerts
    all_alerts = [a for s in sellers.values() for a in s['alerts']]
    critical_alerts = [a for a in all_alerts if a['priority'] == 'CRITICAL']
    high_alerts     = [a for a in all_alerts if a['priority'] == 'HIGH']

    # Top performers: Profit + underspending (opportunity to scale)
    top_ops = [s.get('seller_name') or sid[:12]
               for sid, s in sellers.items()
               if account_status(s.get('account_metrics',{}))[0] == 'Profit'
               and gap_status(s['weekly_plan']['remaining_gap'])[0] == 'Underspend']

    # Needs attention: Loss + overspending OR Loss + large underspend gap
    attention = []
    for sid, s in sellers.items():
        st_label, _ = account_status(s.get('account_metrics', {}))
        gl, _ = gap_status(s['weekly_plan']['remaining_gap'])
        g = safe_float(s['weekly_plan']['remaining_gap']) or 0
        am = s.get('account_metrics', {})
        r3 = safe_float(am.get('ratio_3d'))
        be = safe_float(am.get('be_0pct'))
        name = s.get('seller_name') or sid[:12]
        if st_label == 'Loss' and gl == 'Overspend':
            attention.append((name, 'overspending while in loss'))
        elif st_label == 'Loss' and r3 and be and r3 > be * 1.5:
            attention.append((name, f'Spend/GMV {r3:.1f}% vs break-even {be:.1f}%'))

    # Remaining days context
    rd = get_remaining_days()
    days_desc = {4: 'Thursday — 4 days to go', 3: 'Friday — 3 days to go',
                 2: 'Saturday — 2 days to go', 1: 'Sunday — final day'}
    today_desc = days_desc.get(rd, f'{rd} days to Sunday')

    # Pace assessment
    pace_ok   = sum(1 for s in sellers.values()
                    if abs(safe_float(s['weekly_plan']['remaining_gap']) or 0) <= 500)
    pace_risk = len(sellers) - pace_ok

    return {
        'run_date':       run_date,
        'today_desc':     today_desc,
        'total_sellers':  len(sellers),
        'total_camps':    len(all_camps),
        'total_yesterday': total_yesterday,
        'total_target':    total_target,
        'total_gap':       total_gap,
        'profit_buckets':  profit_buckets,
        'gap_buckets':     gap_buckets,
        'n_scale_up':      n_scale_up,
        'n_hold':          n_hold,
        'n_watch':         n_watch,
        'n_scale_dn':      n_scale_dn,
        'n_pause':         n_pause,
        'total_freed':     total_freed,
        'total_deployed':  total_deployed,
        'all_alerts':      all_alerts,
        'critical_alerts': critical_alerts,
        'high_alerts':     high_alerts,
        'top_ops':         top_ops,
        'attention':       attention,
        'pace_ok':         pace_ok,
        'pace_risk':       pace_risk,
        'remaining_days':  rd,
    }

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

data = load_results()
if data is None:
    st.error("⚠️ No results found. The daily engine hasn't run yet.")
    st.stop()

run_date   = data.get('run_date', 'Unknown')
sellers    = data.get('sellers', {})
seller_ids = list(sellers.keys())

if 'selected_seller' not in st.session_state:
    st.session_state.selected_seller = None

# ---------------------------------------------------------------------------
# Sidebar — seller selector
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚖️ Budget Rebalancer")
    st.markdown(f"<small style='color:#64748b'>Run: **{run_date}**</small>", unsafe_allow_html=True)
    st.divider()

    st.markdown("**Jump to Seller**")
    seller_display = {sid: (s.get('seller_name') or sid) for sid, s in sellers.items()}
    all_names = ["— All Sellers —"] + list(seller_display.values())

    current_name = "— All Sellers —"
    if st.session_state.selected_seller:
        current_name = seller_display.get(st.session_state.selected_seller, "— All Sellers —")

    chosen_name = st.selectbox(
        "Seller", all_names,
        index=all_names.index(current_name) if current_name in all_names else 0,
        label_visibility="collapsed",
    )

    # Navigate on selection change
    if chosen_name == "— All Sellers —":
        if st.session_state.selected_seller is not None:
            st.session_state.selected_seller = None
            st.rerun()
    else:
        for sid, name in seller_display.items():
            if name == chosen_name and sid != st.session_state.selected_seller:
                st.session_state.selected_seller = sid
                st.rerun()

    st.divider()
    excel_bytes = build_excel(sellers)
    st.download_button(
        "⬇ Export All (Excel)", excel_bytes,
        f"rebalancing_{run_date}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

total_camps = sum(len(s['campaigns']) for s in sellers.values())
st.markdown(f"""
<div class="top-header">
  <div class="brand">⚖️ &nbsp;ShopDeck · <span>Budget Rebalancer</span></div>
  <div class="meta">Last run: {run_date} &nbsp;|&nbsp; {len(sellers)} sellers &nbsp;|&nbsp; {total_camps} campaigns</div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# SELLER DEEP DIVE
# ---------------------------------------------------------------------------

if st.session_state.selected_seller:
    sid   = st.session_state.selected_seller
    sdata = sellers[sid]
    plan  = sdata['weekly_plan']
    camps = sdata['campaigns']
    alerts  = sdata['alerts']
    realloc = sdata['reallocation']
    metrics = sdata.get('account_metrics', {})
    status, status_cls = account_status(metrics)
    gap_lbl, gap_cls   = gap_status(plan['remaining_gap'])

    # Build campaign name lookup for alerts
    camp_name_lookup = {str(c['campaign_id']): c.get('campaign_name') or str(c['campaign_id'])
                        for c in camps}

    if st.button("← Back to All Sellers"):
        st.session_state.selected_seller = None
        st.rerun()

    seller_name = sdata.get('seller_name') or ''
    hc1, hc2 = st.columns([6, 1])
    with hc1:
        title = f"**{seller_name}**  `{sid}`" if seller_name else f"`{sid}`"
        st.markdown(f"### {title}")
    with hc2:
        st.markdown(badge(status, status_cls) + '&nbsp;' + badge(gap_lbl, gap_cls), unsafe_allow_html=True)

    # ── Tabs inside deep dive ────────────────────────────────
    t1, t2, t3 = st.tabs(["Planning & Campaigns", "Charts", "Alerts & Reallocation"])

    # ── Tab 1: Planning & Campaigns ──────────────────────────
    with t1:
        st.markdown('<div class="section-title">Weekly Planning</div>', unsafe_allow_html=True)
        cols = st.columns(5)
        metric_card(cols[0], "Last Sunday Spend", fmt_inr(plan['last_sunday_spend']))
        metric_card(cols[1], "Sunday Target",      fmt_inr(plan['this_week_target']))
        metric_card(cols[2], "Yesterday Spend",    fmt_inr(plan['yesterday_daily_spend']))
        gap_val = safe_float(plan['remaining_gap'])
        metric_card(cols[3], "Gap",
                    f"₹{abs(gap_val):,.0f}" if gap_val else '—',
                    "to grow" if (gap_val and gap_val > 0) else "above target",
                    pos=(gap_val is not None and gap_val <= 0))
        pace_val = safe_float(plan['required_daily_pace'])
        metric_card(cols[4], "Daily Pace Needed",
                    f"₹{abs(pace_val):,.0f}/day" if pace_val else '—',
                    plan['direction'],
                    pos=(pace_val is not None and pace_val <= 0))

        st.markdown('<br>', unsafe_allow_html=True)
        r1, r2, r3, r4 = st.columns(4)
        metric_card(r1, "Budget Freed",    fmt_inr(realloc['total_freed']))
        metric_card(r2, "Budget Deployed", fmt_inr(realloc['total_deployed']))
        metric_card(r3, "Net Surplus",     fmt_inr(realloc['net_surplus']))
        metric_card(r4, "Active Alerts",   str(len(alerts)))

        st.markdown(f'<div class="section-title">Campaign Analysis ({len(camps)} campaigns)</div>', unsafe_allow_html=True)
        df = campaigns_to_df(camps).sort_values('Score', ascending=False)
        st.dataframe(
            df, use_container_width=True, hide_index=True,
            column_config={
                'Budget':        st.column_config.NumberColumn(format='₹%.0f'),
                'Rec Budget':    st.column_config.NumberColumn(format='₹%.0f'),
                'Δ%':            st.column_config.NumberColumn(format='%+.1f%%'),
                '3D Spend/GMV%': st.column_config.NumberColumn(format='%.2f%%'),
                'Target%':       st.column_config.NumberColumn(format='%.2f%%'),
                'Break-even%':   st.column_config.NumberColumn(format='%.2f%%'),
                'Utilization%':  st.column_config.NumberColumn(format='%.1f%%'),
                'Score':         st.column_config.ProgressColumn(min_value=0, max_value=100, format='%.0f'),
            },
        )
        dl1, _ = st.columns([1, 5])
        with dl1:
            st.download_button("⬇ Export CSV", df.to_csv(index=False).encode('utf-8'),
                               f"{(seller_name or sid[:12])}_campaigns.csv", "text/csv")

    # ── Tab 2: Charts ────────────────────────────────────────
    with t2:
        ch1, ch2 = st.columns(2)

        with ch1:
            st.markdown("#### Budget Movement")
            valid = [
                (c.get('campaign_name') or str(c['campaign_id']),
                 safe_float(c['budget']),
                 safe_float(c['recommended_budget']),
                 c['action_type'])
                for c in camps
                if safe_float(c['budget']) and safe_float(c['recommended_budget'])
            ]
            if valid:
                # Sort by delta descending (biggest increases first)
                valid = sorted(valid, key=lambda x: (x[2] or 0) - (x[1] or 0), reverse=True)
                names = [v[0][:38] for v in valid]
                curr  = [v[1] for v in valid]
                rec   = [v[2] for v in valid]
                deltas = [r - c for r, c in zip(rec, curr)]
                bar_colors = ['#22c55e' if d > 0 else ('#ef4444' if d < 0 else '#94a3b8') for d in deltas]
                delta_text = [f"{'+'if d>=0 else ''}₹{d:,.0f}" for d in deltas]

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name='Current Budget', y=names, x=curr, orientation='h',
                    marker_color='#e2e8f0', marker_line_color='#cbd5e1', marker_line_width=1,
                ))
                fig.add_trace(go.Bar(
                    name='Recommended', y=names, x=rec, orientation='h',
                    marker_color=bar_colors, opacity=0.85,
                    text=delta_text, textposition='outside',
                    textfont=dict(size=10, color='#374151'),
                ))
                fig.update_layout(
                    barmode='overlay',
                    height=max(360, len(valid) * 40),
                    xaxis_title='Daily Budget (₹)',
                    paper_bgcolor='white', plot_bgcolor='#f8fafc',
                    legend=dict(orientation='h', y=1.06, x=0, font_size=11),
                    margin=dict(l=0, r=90, t=36, b=0),
                    font=dict(size=11),
                    xaxis=dict(gridcolor='#f1f5f9'),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No budget data available.")

        with ch2:
            st.markdown("#### 3D Spend/GMV Efficiency")
            eff_rows = [
                {
                    'Campaign':   (c.get('campaign_name') or str(c['campaign_id']))[:35],
                    'Spend/GMV%': safe_float(c['ratio_3d']),
                    'Efficiency': c['efficiency_label'],
                    'Target':     safe_float(c['target_threshold']),
                    'Break-even': safe_float(c['be_threshold']),
                }
                for c in camps if safe_float(c['ratio_3d']) is not None
            ]
            if eff_rows:
                df_eff = pd.DataFrame(eff_rows).sort_values('Spend/GMV%', ascending=False)
                color_map = {
                    'Efficient':                  '#22c55e',
                    'Acceptable':                 '#84cc16',
                    'Near Break-even':            '#fb923c',
                    'Above Break-even':           '#ef4444',
                    'Severely Above Break-even':  '#7f1d1d',
                    'No GMV':                     '#374151',
                    'No Recent Data':             '#9ca3af',
                    'Unknown':                    '#9ca3af',
                }
                fig = px.bar(
                    df_eff, x='Campaign', y='Spend/GMV%',
                    color='Efficiency', color_discrete_map=color_map,
                    hover_data=['Target', 'Break-even'],
                    text='Spend/GMV%',
                )
                # Add threshold reference lines
                targets = [r['Target'] for r in eff_rows if r['Target']]
                bes     = [r['Break-even'] for r in eff_rows if r['Break-even']]
                if targets:
                    t_val = sum(targets) / len(targets)
                    fig.add_hline(y=t_val, line_dash='dash', line_color='#16a34a', line_width=1.5,
                                  annotation_text=f"Avg Target {t_val:.1f}%",
                                  annotation_position='top right',
                                  annotation_font=dict(size=10, color='#16a34a'))
                if bes:
                    be_val = sum(bes) / len(bes)
                    fig.add_hline(y=be_val, line_dash='dot', line_color='#dc2626', line_width=1.5,
                                  annotation_text=f"Avg BE {be_val:.1f}%",
                                  annotation_position='bottom right',
                                  annotation_font=dict(size=10, color='#dc2626'))
                fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside', textfont_size=9)
                fig.update_layout(
                    height=max(360, len(eff_rows) * 32),
                    xaxis_tickangle=-40,
                    paper_bgcolor='white', plot_bgcolor='#f8fafc',
                    margin=dict(l=0, r=100, t=36, b=0),
                    font=dict(size=11),
                    legend=dict(orientation='h', y=-0.35, font_size=10),
                    yaxis=dict(gridcolor='#f1f5f9', title='Spend/GMV %'),
                    xaxis=dict(title=''),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No Spend/GMV data available.")

    # ── Tab 3: Alerts & Reallocation ────────────────────────
    with t3:
        if alerts:
            st.markdown(f'<div class="section-title">Risk Alerts ({len(alerts)})</div>', unsafe_allow_html=True)
            for a in alerts:
                cls  = {'CRITICAL': 'alert-critical', 'HIGH': 'alert-high', 'MEDIUM': 'alert-medium'}.get(a['priority'], 'alert-medium')
                icon = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡'}.get(a['priority'], '⚪')
                cid  = str(a['campaign_id'])
                cname = camp_name_lookup.get(cid, cid)
                display = (f'<span class="alert-name">{cname}</span> '
                           f'<span class="alert-id">({cid})</span>'
                           if cname != cid else f'<span class="alert-name">{cid}</span>')
                st.markdown(f"""
                <div class="{cls}">
                  <span class="alert-text">{icon} {display} — {a['message']}</span>
                </div>""", unsafe_allow_html=True)
        else:
            st.success("No risk alerts for this seller.")

        st.markdown('<div class="section-title">Capital Reallocation</div>', unsafe_allow_html=True)
        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("**Budget Donors (freed capital)**")
            if realloc['donors']:
                donor_df = pd.DataFrame([
                    {'Campaign': d['campaign_id'], 'Freed': d['freed'], 'Action': d['action']}
                    for d in realloc['donors']
                ])
                st.dataframe(donor_df, hide_index=True, use_container_width=True,
                             column_config={'Freed': st.column_config.NumberColumn(format='₹%.0f')})
            else:
                st.caption("None")
        with rc2:
            st.markdown("**Scale Candidates (receiving capital)**")
            if realloc['scale_candidates']:
                scale_df = pd.DataFrame([
                    {'Campaign': s['campaign_id'], 'Added': s['added'], 'Score': s['score']}
                    for s in realloc['scale_candidates']
                ])
                st.dataframe(scale_df, hide_index=True, use_container_width=True,
                             column_config={'Added': st.column_config.NumberColumn(format='₹%.0f'),
                                            'Score': st.column_config.ProgressColumn(min_value=0, max_value=100, format='%.0f')})
            else:
                st.caption("None")

# ---------------------------------------------------------------------------
# ALL SELLERS + SUMMARY (tabbed)
# ---------------------------------------------------------------------------

else:
    tab_overview, tab_summary = st.tabs(["All Sellers", "Today's Summary"])

    # ════════════════════════════════════════════════════════
    # TAB 1 — ALL SELLERS OVERVIEW
    # ════════════════════════════════════════════════════════
    with tab_overview:
        f1, f2, f3 = st.columns([2, 2, 2])
        with f1:
            status_filter = st.multiselect("Profitability",
                ["Profit", "Breakeven", "Loss", "Unknown"],
                default=["Profit", "Breakeven", "Loss", "Unknown"])
        with f2:
            gap_filter = st.multiselect("Spend Alignment",
                ["Underspend", "On Target", "Overspend"],
                default=["Underspend", "On Target", "Overspend"])
        with f3:
            direction_filter = st.multiselect("Direction",
                ["Scale Up", "Scale Down", "Hold"],
                default=["Scale Up", "Scale Down", "Hold"])

        overview_rows = []
        for sid, sdata in sellers.items():
            plan    = sdata['weekly_plan']
            camps   = sdata['campaigns']
            metrics = sdata.get('account_metrics', {})

            status, status_cls = account_status(metrics)
            gap_lbl, gap_cls   = gap_status(plan['remaining_gap'])
            direction          = plan['direction']

            if status    not in status_filter:    continue
            if gap_lbl   not in gap_filter:       continue
            if direction not in direction_filter: continue

            n_scale  = sum(1 for c in camps if 'scale_up' in c['action_type'])
            n_reduce = sum(1 for c in camps if c['action_type'] in ('scale_down','pause','watch_reduce'))
            n_alerts = len(sdata['alerts'])
            seller_name = sdata.get('seller_name', '')

            overview_rows.append({
                '_seller_id': sid,
                'Seller':     seller_name or sid[:20],
                'Status':     badge(status, status_cls),
                'Gap Status': badge(gap_lbl, gap_cls),
                'Direction':  direction,
                'Last Sunday': fmt_inr(plan['last_sunday_spend']),
                'Target':      fmt_inr(plan['this_week_target']),
                'Yesterday':   fmt_inr(plan['yesterday_daily_spend']),
                'Gap':    f"₹{safe_float(plan['remaining_gap']):+,.0f}" if safe_float(plan['remaining_gap']) else '—',
                'Pace/Day': f"₹{safe_float(plan['required_daily_pace']):+,.0f}" if safe_float(plan['required_daily_pace']) else '—',
                'Campaigns': len(camps),
                '↑ Scale': n_scale,
                '↓ Reduce': n_reduce,
                '⚠ Alerts': n_alerts,
            })

        st.markdown(f'<div class="row-count">{len(overview_rows)} seller(s) matching filters</div>', unsafe_allow_html=True)

        if not overview_rows:
            st.info("No sellers match the selected filters.")
        else:
            col_order = ['Seller','Status','Gap Status','Direction','Last Sunday','Target','Yesterday','Gap','Pace/Day','Campaigns','↑ Scale','↓ Reduce','⚠ Alerts']
            header_html = ''.join(
                f'<th style="padding:8px 12px;text-align:left;background:#f8fafc;border-bottom:2px solid #e2e8f0;'
                f'font-size:12px;font-weight:700;color:#64748b;white-space:nowrap">{c}</th>'
                for c in col_order
            )
            rows_html = ''
            for row in overview_rows:
                cells = ''
                for col in col_order:
                    val = row.get(col, '—')
                    if col == 'Seller':
                        val = f'<span style="font-weight:600;color:#0f172a">{val}</span>'
                    elif col == '⚠ Alerts' and isinstance(val, int) and val > 0:
                        val = f'<span style="color:#dc2626;font-weight:700">{val}</span>'
                    cells += f'<td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;vertical-align:middle">{val}</td>'
                rows_html += f'<tr>{cells}</tr>'

            st.markdown(f"""
            <div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;background:white">
              <table style="width:100%;border-collapse:collapse">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>""", unsafe_allow_html=True)

        if overview_rows:
            st.markdown('<div class="section-title">Account Overview</div>', unsafe_allow_html=True)
            oc1, oc2 = st.columns(2)
            with oc1:
                st.markdown("**Gap vs Sunday Target (₹)**")
                gap_data = []
                for row in overview_rows:
                    g = safe_float(sellers[row['_seller_id']]['weekly_plan']['remaining_gap'])
                    gap_data.append({
                        'Seller': sellers[row['_seller_id']].get('seller_name') or row['_seller_id'][:14],
                        'Gap': g,
                        'Status': 'Underspend' if (g and g > 500) else ('Overspend' if (g and g < -500) else 'On Target'),
                    })
                fig = px.bar(pd.DataFrame(gap_data), x='Seller', y='Gap', color='Status',
                    color_discrete_map={'Underspend':'#3b82f6','On Target':'#22c55e','Overspend':'#f43f5e'})
                fig.add_hline(y=0, line_color='#0f172a', line_width=1)
                fig.update_layout(height=320, paper_bgcolor='white', plot_bgcolor='#f8fafc',
                    xaxis_tickangle=-35, margin=dict(l=0,r=0,t=10,b=0),
                    font=dict(size=11), yaxis=dict(gridcolor='#f1f5f9'))
                st.plotly_chart(fig, use_container_width=True)

            with oc2:
                st.markdown("**Profitability Distribution**")
                status_counts = {}
                for row in overview_rows:
                    s, _ = account_status(sellers[row['_seller_id']].get('account_metrics', {}))
                    status_counts[s] = status_counts.get(s, 0) + 1
                fig = px.pie(
                    names=list(status_counts.keys()), values=list(status_counts.values()),
                    color=list(status_counts.keys()),
                    color_discrete_map={'Profit':'#22c55e','Breakeven':'#facc15','Loss':'#ef4444','Unknown':'#9ca3af'},
                    hole=0.52,
                )
                fig.update_traces(textinfo='label+percent', textfont_size=12)
                fig.update_layout(height=320, paper_bgcolor='white',
                    margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

    # ════════════════════════════════════════════════════════
    # TAB 2 — TODAY'S SUMMARY
    # ════════════════════════════════════════════════════════
    with tab_summary:

        sm = generate_written_summary(sellers, run_date)

        # ── KPI strip ─────────────────────────────────────────
        n_alerts_all = len(sm['all_alerts'])
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.markdown(f'<div class="summary-kpi"><div class="sk-label">Scale Up</div><div class="sk-value kpi-green">{sm["n_scale_up"]}</div><div class="sk-sub">campaigns</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="summary-kpi"><div class="sk-label">Hold</div><div class="sk-value kpi-blue">{sm["n_hold"]}</div><div class="sk-sub">campaigns</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="summary-kpi"><div class="sk-label">Watch / Reduce</div><div class="sk-value kpi-amber">{sm["n_watch"] + sm["n_scale_dn"]}</div><div class="sk-sub">campaigns</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="summary-kpi"><div class="sk-label">Pause</div><div class="sk-value kpi-red">{sm["n_pause"]}</div><div class="sk-sub">campaigns</div></div>', unsafe_allow_html=True)
        k5.markdown(f'<div class="summary-kpi"><div class="sk-label">Budget Freed</div><div class="sk-value kpi-amber">₹{sm["total_freed"]:,.0f}</div><div class="sk-sub">reallocatable</div></div>', unsafe_allow_html=True)
        k6.markdown(f'<div class="summary-kpi"><div class="sk-label">Risk Alerts</div><div class="sk-value kpi-red">{n_alerts_all}</div><div class="sk-sub">across all sellers</div></div>', unsafe_allow_html=True)

        st.markdown('<br>', unsafe_allow_html=True)

        # ── Written weekly summary ─────────────────────────────
        st.markdown('<div class="section-title">Weekly Written Summary</div>', unsafe_allow_html=True)

        pb  = sm['profit_buckets']
        gb  = sm['gap_buckets']
        rd  = sm['remaining_days']
        att = sm['attention']
        top = sm['top_ops']
        crit = sm['critical_alerts']
        high = sm['high_alerts']

        # Section 1 — Portfolio overview
        gap_dir = "below" if sm['total_gap'] > 0 else "above"
        gap_abs = abs(sm['total_gap'])
        spend_pct = (sm['total_yesterday'] / sm['total_target'] * 100) if sm['total_target'] else 0
        st.markdown(f"""
**📊 Portfolio at a Glance — {run_date}**

Today is **{sm['today_desc']}**. Across all {sm['total_sellers']} sellers and {sm['total_camps']} campaigns, yesterday's combined daily spend was **₹{sm['total_yesterday']:,.0f}**, against a Sunday exit target of **₹{sm['total_target']:,.0f}** — running at **{spend_pct:.0f}%** of target. The portfolio is collectively **₹{gap_abs:,.0f} {gap_dir} target**, with {rd} day{'s' if rd>1 else ''} remaining to close the gap.

Profitability snapshot: **{len(pb['Profit'])} seller{'s' if len(pb['Profit'])!=1 else ''} profitable**, {len(pb['Breakeven'])} at break-even, and **{len(pb['Loss'])} in loss**. On spend alignment: {len(gb['Underspend'])} underspending, {len(gb['On Target'])} on target, {len(gb['Overspend'])} overspending.
""")

        # Section 2 — Actions taken
        net_budget = sm['total_deployed'] - sm['total_freed']
        net_dir    = "increase" if net_budget >= 0 else "decrease"
        st.markdown(f"""
**⚙️ Today's Recommendations**

The engine recommends scaling up **{sm['n_scale_up']} campaign{'s' if sm['n_scale_up']!=1 else ''}**, holding **{sm['n_hold']}**, watching/reducing **{sm['n_watch'] + sm['n_scale_dn']}**, and pausing **{sm['n_pause']}** outright. Capital reallocation frees **₹{sm['total_freed']:,.0f}** from underperforming campaigns and deploys **₹{sm['total_deployed']:,.0f}** into high-scorers — a net budget **{net_dir} of ₹{abs(net_budget):,.0f}** across the portfolio.
""")

        # Section 3 — Opportunities
        if top:
            st.markdown(f"""
**🟢 Scaling Opportunities**

The following sellers are currently **profitable and underspending** — prime candidates to push harder before Sunday:
{chr(10).join(f'- **{n}**' for n in top)}

These accounts have headroom to absorb higher spend without breaching break-even. Applying the recommended budgets here should meaningfully close the gap.
""")

        # Section 4 — Needs attention
        if att:
            st.markdown("**🔴 Sellers Needing Immediate Attention**\n")
            for name, reason in att:
                st.markdown(f"- **{name}** — {reason}")
            st.markdown("\nThese sellers are burning spend without sufficient GMV return. Prioritise reducing their budgets today before the situation worsens into the weekend.")
        else:
            st.markdown("**🟢 No sellers are simultaneously in loss and overspending** — healthy signal for the portfolio.")

        # Section 5 — Risk flags
        if crit or high:
            st.markdown(f"""
**⚠️ Risk Flags**

There are **{len(crit)} CRITICAL** and **{len(high)} HIGH** priority alerts today.
""")
            if crit:
                st.markdown("Critical issues requiring same-day action:")
                for a in crit[:5]:
                    st.markdown(f"- {a['message']} *(Campaign {a['campaign_id']})*")
            if high and len(high) <= 6:
                st.markdown("High-priority items to address:")
                for a in high[:4]:
                    st.markdown(f"- {a['message']} *(Campaign {a['campaign_id']})*")
        else:
            st.markdown("**✅ No critical or high-priority alerts** — portfolio is structurally healthy today.")

        # Section 6 — Weekly outlook
        on_track   = sum(1 for s in sellers.values()
                         if gap_status(s['weekly_plan']['remaining_gap'])[0] in ('On Target', 'Underspend')
                         and account_status(s.get('account_metrics',{}))[0] in ('Profit','Breakeven'))
        at_risk    = sm['total_sellers'] - on_track
        pace_stmt  = (f"**{on_track} seller{'s' if on_track!=1 else ''}** appear on track to meet their Sunday targets at current pace. "
                      f"{'The remaining ' + str(at_risk) + ' require active budget intervention today.' if at_risk else 'All sellers are on track — no emergency interventions needed.'}")

        overspend_names = gb['Overspend']
        os_stmt = (f" Note that **{', '.join(overspend_names[:3])}{'...' if len(overspend_names)>3 else ''}** {'are' if len(overspend_names)>1 else 'is'} already above yesterday's daily run-rate — monitor these for week-end overshoot."
                   if overspend_names else "")

        st.markdown(f"""
**📅 Weekly Outlook**

{pace_stmt}{os_stmt}

With {rd} day{'s' if rd>1 else ''} to Sunday, the focus should be: **execute scale-ups on profitable underspenders today**, reduce budgets on loss-making overspenders immediately, and monitor utilisation closely on Friday to decide whether further adjustments are needed before the weekend.
""")

        st.divider()
        st.markdown('<br>', unsafe_allow_html=True)

        # ── Budget utilisation projection ──────────────────────
        st.markdown('<div class="section-title">Budget Utilisation After Scaling</div>', unsafe_allow_html=True)
        st.caption("Projected daily spend = each campaign's recommended budget × yesterday's utilisation rate")

        util_rows = []
        for sid, s in sellers.items():
            plan  = s['weekly_plan']
            camps = s['campaigns']
            curr_budget_total = sum(safe_float(c['budget']) or 0 for c in camps)
            rec_budget_total  = sum(safe_float(c['recommended_budget']) or 0 for c in camps)

            projected_spend = 0
            for c in camps:
                bud = safe_float(c['budget'])
                rec = safe_float(c['recommended_budget'])
                yspend = safe_float(c['yesterday_spend'])
                if bud and bud > 0 and rec and yspend is not None:
                    util = yspend / bud
                    projected_spend += rec * util

            target = safe_float(plan['this_week_target']) or 0
            proj   = round(projected_spend)
            gap_to_target = proj - target

            util_rows.append({
                'Seller':              s.get('seller_name') or sid[:18],
                'Yesterday Spend':     safe_float(plan['yesterday_daily_spend']) or 0,
                'Current Budget Sum':  round(curr_budget_total),
                'Rec Budget Sum':      round(rec_budget_total),
                'Budget Δ':            round(rec_budget_total - curr_budget_total),
                'Projected Daily':     proj,
                'Sunday Target':       round(target),
                'Proj vs Target':      round(gap_to_target),
            })

        util_df = pd.DataFrame(util_rows).sort_values('Proj vs Target')
        st.dataframe(
            util_df, hide_index=True, use_container_width=True,
            column_config={
                'Yesterday Spend':    st.column_config.NumberColumn(format='₹%.0f'),
                'Current Budget Sum': st.column_config.NumberColumn(format='₹%.0f'),
                'Rec Budget Sum':     st.column_config.NumberColumn(format='₹%.0f'),
                'Budget Δ':           st.column_config.NumberColumn(format='₹%+.0f'),
                'Projected Daily':    st.column_config.NumberColumn(format='₹%.0f'),
                'Sunday Target':      st.column_config.NumberColumn(format='₹%.0f'),
                'Proj vs Target':     st.column_config.NumberColumn(format='₹%+.0f'),
            },
        )

        # Utilisation bar chart
        util_chart_df = pd.DataFrame([
            {'Seller': r['Seller'], 'Type': 'Yesterday Spend', 'Amount': r['Yesterday Spend']},
            {'Seller': r['Seller'], 'Type': 'Projected (Post-Scale)', 'Amount': r['Projected Daily']},
            {'Seller': r['Seller'], 'Type': 'Sunday Target', 'Amount': r['Sunday Target']},
        ] for r in util_rows)
        util_chart_df = util_chart_df.explode('Amount') if isinstance(util_chart_df.iloc[0]['Amount'], list) else pd.concat(
            [pd.DataFrame([{'Seller': r['Seller'], 'Type': 'Yesterday Spend', 'Amount': r['Yesterday Spend']},
                           {'Seller': r['Seller'], 'Type': 'Projected (Post-Scale)', 'Amount': r['Projected Daily']},
                           {'Seller': r['Seller'], 'Type': 'Sunday Target', 'Amount': r['Sunday Target']}])
             for r in util_rows]
        )
        fig = px.bar(util_chart_df, x='Seller', y='Amount', color='Type', barmode='group',
                     color_discrete_map={
                         'Yesterday Spend': '#94a3b8',
                         'Projected (Post-Scale)': '#38bdf8',
                         'Sunday Target': '#22c55e',
                     })
        fig.update_layout(height=340, paper_bgcolor='white', plot_bgcolor='#f8fafc',
                          xaxis_tickangle=-35, margin=dict(l=0,r=0,t=10,b=0),
                          legend=dict(orientation='h', y=1.08, font_size=11),
                          font=dict(size=11), yaxis=dict(gridcolor='#f1f5f9', title='₹ / day'))
        st.plotly_chart(fig, use_container_width=True)

        # ── Weekly scaling plan ────────────────────────────────
        st.markdown('<div class="section-title">Weekly Scaling Plan</div>', unsafe_allow_html=True)
        st.caption("Linear daily ramp from yesterday's spend to Sunday target. Actual application is manual.")

        remaining_days = get_remaining_days()
        day_labels     = get_day_labels(remaining_days)

        plan_rows = []
        for sid, s in sellers.items():
            plan   = s['weekly_plan']
            y_spnd = safe_float(plan['yesterday_daily_spend']) or 0
            target = safe_float(plan['this_week_target']) or 0
            gap    = target - y_spnd

            row = {'Seller': s.get('seller_name') or sid[:18]}
            for i, day in enumerate(day_labels):
                # Linear ramp: add gap/remaining_days each day
                daily_target = y_spnd + (gap / remaining_days) * (i + 1)
                row[day] = round(daily_target)
            row['Sunday Target'] = round(target)
            plan_rows.append(row)

        plan_df = pd.DataFrame(plan_rows)
        day_col_config = {d: st.column_config.NumberColumn(format='₹%.0f') for d in day_labels}
        day_col_config['Sunday Target'] = st.column_config.NumberColumn(format='₹%.0f')
        st.dataframe(plan_df, hide_index=True, use_container_width=True, column_config=day_col_config)

        # Scaling plan chart (line per seller)
        st.markdown("**Spend Trajectory per Seller**")
        traj_rows = []
        for sid, s in sellers.items():
            plan   = s['weekly_plan']
            y_spnd = safe_float(plan['yesterday_daily_spend']) or 0
            target = safe_float(plan['this_week_target']) or 0
            gap    = target - y_spnd
            name   = s.get('seller_name') or sid[:14]
            for i, day in enumerate(day_labels):
                traj_rows.append({
                    'Seller': name,
                    'Day': day,
                    'Spend': round(y_spnd + (gap / remaining_days) * (i + 1)),
                })
        traj_df = pd.DataFrame(traj_rows)
        fig = px.line(traj_df, x='Day', y='Spend', color='Seller', markers=True)
        fig.update_layout(height=360, paper_bgcolor='white', plot_bgcolor='#f8fafc',
                          margin=dict(l=0,r=0,t=10,b=0),
                          legend=dict(orientation='h', y=-0.25, font_size=10),
                          font=dict(size=11),
                          yaxis=dict(gridcolor='#f1f5f9', title='Daily Spend (₹)'),
                          xaxis=dict(title=''))
        st.plotly_chart(fig, use_container_width=True)
