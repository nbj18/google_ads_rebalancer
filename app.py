import json, math, io
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="ShopDeck · Budget Rebalancer",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1rem; padding-bottom: 1rem; }

  /* ── Top header bar ─────────────────────────────────── */
  .top-header {
    display: flex; align-items: center; justify-content: space-between;
    background: #0f172a; color: white;
    padding: 14px 24px; border-radius: 10px; margin-bottom: 18px;
  }
  .top-header .brand { font-size: 18px; font-weight: 700; letter-spacing: -.3px; }
  .top-header .brand span { color: #38bdf8; }
  .top-header .meta { font-size: 12px; color: #94a3b8; }

  /* ── Filter bar ─────────────────────────────────────── */
  .filter-bar {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 12px 18px;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .filter-label { font-size: 12px; font-weight: 600; color: #64748b; margin-right: 4px; }

  /* ── Status badges ──────────────────────────────────── */
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

  /* ── Metric cards ───────────────────────────────────── */
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

  /* ── Alert boxes ────────────────────────────────────── */
  .alert-critical { background:#fef2f2; border-left:4px solid #dc2626;
    padding:10px 14px; border-radius:6px; margin-bottom:8px; }
  .alert-high     { background:#fffbeb; border-left:4px solid #f59e0b;
    padding:10px 14px; border-radius:6px; margin-bottom:8px; }
  .alert-medium   { background:#eff6ff; border-left:4px solid #3b82f6;
    padding:10px 14px; border-radius:6px; margin-bottom:8px; }
  .alert-text     { font-size:13px; color:#1e293b; }
  .alert-id       { font-weight:700; }

  /* ── Back button ────────────────────────────────────── */
  .back-btn {
    display:inline-flex; align-items:center; gap:6px;
    font-size:13px; color:#0f172a; font-weight:600;
    background:#f1f5f9; border:1px solid #e2e8f0;
    padding:6px 14px; border-radius:8px; cursor:pointer;
    text-decoration:none; margin-bottom:16px;
  }

  /* ── Section title ──────────────────────────────────── */
  .section-title {
    font-size:15px; font-weight:700; color:#0f172a;
    margin:20px 0 10px; padding-bottom:6px;
    border-bottom:2px solid #e2e8f0;
  }

  /* ── Account row card ───────────────────────────────── */
  .row-count { font-size:13px; color:#64748b; margin-bottom:8px; }
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
    r3    = safe_float(metrics.get('ratio_3d'))
    tgt   = safe_float(metrics.get('be_target'))
    be    = safe_float(metrics.get('be_0pct'))
    if r3 is None or tgt is None or be is None: return 'Unknown', 'badge-hold'
    if r3 < tgt:  return 'Profit',    'badge-profit'
    if r3 < be:   return 'Breakeven', 'badge-breakeven'
    return 'Loss', 'badge-loss'

def gap_status(gap):
    g = safe_float(gap)
    if g is None: return 'Unknown', 'badge-hold'
    if g > 500:   return 'Underspend', 'badge-underspend'
    if g < -500:  return 'Overspend',  'badge-overspend'
    return 'On Target', 'badge-ontarget'

def state_badge_cls(state):
    s = state.lower()
    if 'aggressively' in s or 'carefully' in s: return 'badge-scale'
    if 'hold' in s:   return 'badge-hold'
    if 'watch' in s:  return 'badge-watch'
    return 'badge-reduce'

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

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

data = load_results()
if data is None:
    st.error("⚠️ No results found. The daily engine hasn't run yet.")
    st.stop()

run_date = data.get('run_date', 'Unknown')
sellers  = data.get('sellers', {})
seller_ids = list(sellers.keys())

# Session state
if 'selected_seller' not in st.session_state:
    st.session_state.selected_seller = None

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(f"""
<div class="top-header">
  <div class="brand">⚖️ &nbsp;ShopDeck · <span>Budget Rebalancer</span></div>
  <div class="meta">Last run: {run_date} &nbsp;|&nbsp; {len(sellers)} sellers &nbsp;|&nbsp; {sum(len(s['campaigns']) for s in sellers.values())} campaigns</div>
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

    # Back button
    if st.button("← Back to All Sellers"):
        st.session_state.selected_seller = None
        st.rerun()

    # Seller title
    seller_name = sdata.get('seller_name') or ''
    c1, c2 = st.columns([6, 1])
    with c1:
        title = f"**{seller_name}**  `{sid}`" if seller_name else f"`{sid}`"
        st.markdown(f"### {title}")
    with c2:
        st.markdown(badge(status, status_cls) + '&nbsp;' + badge(gap_lbl, gap_cls), unsafe_allow_html=True)

    # Weekly metric cards
    st.markdown('<div class="section-title">Weekly Planning</div>', unsafe_allow_html=True)
    cols = st.columns(5)
    def metric_card(col, label, value, sub='', pos=None):
        sub_cls = 'pos' if pos is True else ('neg' if pos is False else '')
        col.markdown(f"""
        <div class="metric-card">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
          <div class="sub {sub_cls}">{sub}</div>
        </div>""", unsafe_allow_html=True)

    metric_card(cols[0], "Last Sunday Spend",  fmt_inr(plan['last_sunday_spend']))
    metric_card(cols[1], "Sunday Target",       fmt_inr(plan['this_week_target']))
    metric_card(cols[2], "Yesterday Spend",     fmt_inr(plan['yesterday_daily_spend']))
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

    # Capital reallocation strip
    r1, r2, r3, r4 = st.columns(4)
    metric_card(r1, "Budget Freed",    fmt_inr(realloc['total_freed']))
    metric_card(r2, "Budget Deployed", fmt_inr(realloc['total_deployed']))
    metric_card(r3, "Net Surplus",     fmt_inr(realloc['net_surplus']))
    metric_card(r4, "Active Alerts",   str(len(alerts)))

    # Campaign table
    st.markdown(f'<div class="section-title">Campaign Analysis ({len(camps)} campaigns)</div>', unsafe_allow_html=True)
    df = campaigns_to_df(camps).sort_values('Score', ascending=False)

    # Add badge html for State column display
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
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

    dl_col1, dl_col2 = st.columns([1, 5])
    with dl_col1:
        st.download_button(
            "⬇ Export CSV",
            df.to_csv(index=False).encode('utf-8'),
            f"{sid[:20]}_campaigns.csv", "text/csv",
        )

    # Charts
    st.markdown('<div class="section-title">Charts</div>', unsafe_allow_html=True)
    ch1, ch2 = st.columns(2)

    with ch1:
        st.markdown("**Budget Movement**")
        valid = [(str(c['campaign_id']), safe_float(c['budget']), safe_float(c['recommended_budget']))
                 for c in camps if safe_float(c['budget']) and safe_float(c['recommended_budget'])]
        if valid:
            ids, curr, rec = zip(*valid)
            fig = go.Figure()
            fig.add_trace(go.Bar(name='Current', y=list(ids), x=list(curr),
                orientation='h', marker_color='#cbd5e1'))
            fig.add_trace(go.Bar(name='Recommended', y=list(ids), x=list(rec),
                orientation='h',
                marker_color=['#22c55e' if r >= c else '#ef4444' for r, c in zip(rec, curr)]))
            fig.update_layout(barmode='overlay', height=max(280, len(valid)*32),
                xaxis_title='Budget (₹)', paper_bgcolor='white', plot_bgcolor='white',
                legend=dict(orientation='h', y=1.08), margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No budget data available.")

    with ch2:
        st.markdown("**3D Spend/GMV by Campaign**")
        eff_rows = [{'Campaign': str(c['campaign_id']),
                     'Spend/GMV%': safe_float(c['ratio_3d']),
                     'Efficiency': c['efficiency_label']}
                    for c in camps if safe_float(c['ratio_3d']) is not None]
        if eff_rows:
            color_map = {
                'Efficient': '#22c55e', 'Acceptable': '#facc15',
                'Near Break-even': '#fb923c', 'Above Break-even': '#ef4444',
                'Severely Above Break-even': '#7f1d1d',
                'No GMV': '#374151', 'No Recent Data': '#9ca3af', 'Unknown': '#9ca3af',
            }
            fig = px.bar(pd.DataFrame(eff_rows), x='Campaign', y='Spend/GMV%',
                         color='Efficiency', color_discrete_map=color_map)
            fig.update_layout(height=max(280, len(eff_rows)*25), xaxis_tickangle=-45,
                paper_bgcolor='white', plot_bgcolor='white',
                margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No Spend/GMV data available.")

    # Risk alerts
    if alerts:
        st.markdown(f'<div class="section-title">Risk Alerts ({len(alerts)})</div>', unsafe_allow_html=True)
        for a in alerts:
            cls = {'CRITICAL': 'alert-critical', 'HIGH': 'alert-high', 'MEDIUM': 'alert-medium'}.get(a['priority'], 'alert-medium')
            icon = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡'}.get(a['priority'], '⚪')
            st.markdown(f"""
            <div class="{cls}">
              <span class="alert-text">{icon} <span class="alert-id">{a['campaign_id']}</span> — {a['message']}</span>
            </div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# ALL SELLERS OVERVIEW
# ---------------------------------------------------------------------------

else:
    # ── Filter bar ──────────────────────────────────────────
    st.markdown('<div class="section-title" style="margin-top:0">Filters</div>', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])

    with f1:
        status_filter = st.multiselect(
            "Profitability", ["Profit", "Breakeven", "Loss", "Unknown"],
            default=["Profit", "Breakeven", "Loss", "Unknown"],
        )
    with f2:
        gap_filter = st.multiselect(
            "Spend Alignment", ["Underspend", "On Target", "Overspend"],
            default=["Underspend", "On Target", "Overspend"],
        )
    with f3:
        direction_filter = st.multiselect(
            "Direction", ["Scale Up", "Scale Down", "Hold"],
            default=["Scale Up", "Scale Down", "Hold"],
        )
    with f4:
        st.markdown('<br>', unsafe_allow_html=True)
        excel_bytes = build_excel(sellers)
        st.download_button("⬇ Export Excel", excel_bytes,
            f"rebalancing_{run_date}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)

    # ── Build overview rows ─────────────────────────────────
    overview_rows = []
    for sid, sdata in sellers.items():
        plan    = sdata['weekly_plan']
        camps   = sdata['campaigns']
        metrics = sdata.get('account_metrics', {})

        status, status_cls   = account_status(metrics)
        gap_lbl, gap_cls     = gap_status(plan['remaining_gap'])
        direction            = plan['direction']

        if status not in status_filter:       continue
        if gap_lbl not in gap_filter:         continue
        if direction not in direction_filter: continue

        n_scale  = sum(1 for c in camps if 'scale_up' in c['action_type'])
        n_reduce = sum(1 for c in camps if c['action_type'] in ('scale_down','pause','watch_reduce'))
        n_alerts = len(sdata['alerts'])

        seller_name = sdata.get('seller_name', '')
        overview_rows.append({
            '_seller_id':  sid,
            'Seller':      seller_name or sid[:20],
            'Seller ID':   sid,
            'Status':      badge(status, status_cls),
            'Gap Status':  badge(gap_lbl, gap_cls),
            'Direction':   direction,
            'Last Sunday': fmt_inr(plan['last_sunday_spend']),
            'Target':      fmt_inr(plan['this_week_target']),
            'Yesterday':   fmt_inr(plan['yesterday_daily_spend']),
            'Gap':         f"₹{safe_float(plan['remaining_gap']):+,.0f}" if safe_float(plan['remaining_gap']) else '—',
            'Pace/Day':    f"₹{safe_float(plan['required_daily_pace']):+,.0f}" if safe_float(plan['required_daily_pace']) else '—',
            'Campaigns':   len(camps),
            '↑ Scale':     n_scale,
            '↓ Reduce':    n_reduce,
            '⚠ Alerts':    n_alerts,
        })

    st.markdown(f'<div class="row-count">{len(overview_rows)} seller(s) matching filters</div>', unsafe_allow_html=True)

    if not overview_rows:
        st.info("No sellers match the selected filters.")
    else:
        # Render as HTML table for badge support
        col_order = ['Seller','Status','Gap Status','Direction','Last Sunday','Target','Yesterday','Gap','Pace/Day','Campaigns','↑ Scale','↓ Reduce','⚠ Alerts']
        header_html = ''.join(f'<th style="padding:8px 12px;text-align:left;background:#f8fafc;border-bottom:2px solid #e2e8f0;font-size:12px;font-weight:700;color:#64748b;white-space:nowrap">{c}</th>' for c in col_order)

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
            sid_val = row['_seller_id']
            rows_html += f'<tr style="cursor:pointer" onclick="window.parent.postMessage({{type:\'streamlit:setComponentValue\',value:\'{sid_val}\'}},\'*\')">{cells}</tr>'

        st.markdown(f"""
        <div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;background:white">
          <table style="width:100%;border-collapse:collapse">
            <thead><tr>{header_html}</tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>""", unsafe_allow_html=True)

        # Streamlit-native row selection (since HTML onclick won't work cross-origin)
        st.markdown('<div class="section-title">Select Seller for Deep Dive</div>', unsafe_allow_html=True)
        sel_cols = st.columns([3, 1])
        with sel_cols[0]:
            selected = st.selectbox(
                "Select Seller",
                options=[r['_seller_id'] for r in overview_rows],
                format_func=lambda x: x,
                label_visibility="collapsed",
            )
        with sel_cols[1]:
            if st.button("View Details →", use_container_width=True):
                st.session_state.selected_seller = selected
                st.rerun()

    # ── Summary charts ──────────────────────────────────────
    if overview_rows:
        st.markdown('<div class="section-title">Account Overview</div>', unsafe_allow_html=True)
        ch1, ch2 = st.columns(2)

        with ch1:
            st.markdown("**Gap vs Sunday Target (₹)**")
            gap_data = []
            for row in overview_rows:
                sid = row['_seller_id']
                g   = safe_float(sellers[sid]['weekly_plan']['remaining_gap'])
                gap_data.append({'Seller': sid[:18]+'...', 'Gap': g,
                    'Status': 'Underspend' if (g and g > 500) else ('Overspend' if (g and g < -500) else 'On Target')})
            fig = px.bar(pd.DataFrame(gap_data), x='Seller', y='Gap', color='Status',
                color_discrete_map={'Underspend':'#3b82f6','On Target':'#22c55e','Overspend':'#f43f5e'})
            fig.add_hline(y=0, line_color='#0f172a', line_width=1)
            fig.update_layout(height=320, paper_bgcolor='white', plot_bgcolor='white',
                xaxis_tickangle=-40, margin=dict(l=0,r=0,t=10,b=0), showlegend=True)
            st.plotly_chart(fig, use_container_width=True)

        with ch2:
            st.markdown("**Profitability Distribution**")
            status_counts = {}
            for row in overview_rows:
                s, _ = account_status(sellers[row['_seller_id']].get('account_metrics', {}))
                status_counts[s] = status_counts.get(s, 0) + 1
            fig = px.pie(
                names=list(status_counts.keys()),
                values=list(status_counts.values()),
                color=list(status_counts.keys()),
                color_discrete_map={'Profit':'#22c55e','Breakeven':'#facc15','Loss':'#ef4444','Unknown':'#9ca3af'},
                hole=0.5,
            )
            fig.update_layout(height=320, paper_bgcolor='white',
                margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig, use_container_width=True)
