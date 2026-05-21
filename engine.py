import math
from datetime import date
from typing import Optional


def _is_null(val) -> bool:
    if val is None:
        return True
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_remaining_days() -> int:
    """Days from today to Sunday inclusive (Thu=4, Fri=3, Sat=2, Sun=1)."""
    today = date.today()
    return 7 - today.weekday()  # Mon weekday=0 → 7 days; Sun weekday=6 → 1 day


def spend_gmv_ratio(spend: float, gmv: float) -> Optional[float]:
    """Spend/GMV as a percentage. Returns None if no spend, inf if spend but no GMV."""
    if spend == 0:
        return None
    if gmv == 0:
        return float('inf')
    return round((spend / gmv) * 100, 2)


def get_thresholds(campaign_type: Optional[str], seller_be: dict) -> tuple:
    """Returns (target_pct, be_pct) for a campaign type, falling back to account BE."""
    account_target = seller_be.get('account_BE_5pct')
    account_be = seller_be.get('account_BE_0pct')

    type_map = {
        'demand_gen':  ('demand_gen_BE_5pct',  'demand_gen_BE_0pct'),
        'pmax_banner': ('pmax_banner_BE_5pct', 'pmax_banner_BE_0pct'),
        'pmax_feed':   ('pmax_feed_BE_5pct',   'pmax_feed_BE_0pct'),
        'shopping':    ('shopping_BE_5pct',    'shopping_BE_0pct'),
        'search':      ('search_BE_5pct',      'search_BE_0pct'),
        'display':     ('display_BE_5pct',     'display_BE_0pct'),
    }

    if campaign_type and campaign_type in type_map:
        t_key, be_key = type_map[campaign_type]
        target = seller_be.get(t_key) or account_target
        be     = seller_be.get(be_key) or account_be
    else:
        target = account_target
        be     = account_be

    return target, be


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def calc_efficiency_score(ratio_3d: Optional[float], target: Optional[float], be: Optional[float]) -> int:
    if ratio_3d is None:
        return 30   # No recent spend — uncertain
    if ratio_3d == float('inf'):
        return 0    # Spent money, zero GMV — structural failure
    if target is None or be is None:
        return 50   # No thresholds — neutral
    if ratio_3d < target:
        return 100  # Better than target
    if ratio_3d < be:
        return 70   # Acceptable
    if ratio_3d < be * 1.1:
        return 40   # Near break-even
    if ratio_3d < be * 2:
        return 20   # Above break-even
    return 5        # Severely above break-even


def calc_spendability_score(yesterday_spend: float, budget: Optional[float]) -> int:
    if _is_null(budget) or not budget or budget == 0:
        return 5
    u = yesterday_spend / budget
    if u > 0.90: return 100
    if u > 0.75: return 70
    if u > 0.50: return 40
    if u > 0.05: return 20
    return 5


def calc_stability(spend_3d: float, gmv_3d: float, spend_7d: float, gmv_7d: float) -> tuple:
    """Returns (score, classification)."""
    if spend_3d == 0 and spend_7d == 0:
        return 10, 'Dead'
    if spend_3d == 0:
        return 20, 'Volatile'

    r3 = spend_gmv_ratio(spend_3d, gmv_3d)
    r7 = spend_gmv_ratio(spend_7d, gmv_7d)

    if r3 == float('inf'):
        return 10, 'Structural Issue'
    if r7 is None or r7 == float('inf'):
        return 30, 'Volatile'

    diff = (r3 - r7) / r7
    if diff < -0.15: return 90, 'Improving'
    if diff <= 0.15: return 80, 'Stable'
    if diff <= 0.30: return 60, 'Moderate'
    if diff <= 0.50: return 40, 'Deteriorating'
    return 30, 'Volatile'


def calc_rebalancing_score(eff: int, spend: int, stab: int) -> float:
    return round(0.5 * eff + 0.3 * spend + 0.2 * stab, 1)


def get_campaign_state(score: float) -> str:
    if score >= 85: return 'Scale Aggressively'
    if score >= 70: return 'Scale Carefully'
    if score >= 50: return 'Hold'
    if score >= 30: return 'Watch'
    return 'Reduce'


def get_efficiency_label(ratio_3d: Optional[float], target: Optional[float], be: Optional[float]) -> str:
    if ratio_3d is None:
        return 'No Recent Data'
    if ratio_3d == float('inf'):
        return 'No GMV'
    if target is None or be is None:
        return 'Unknown'
    if ratio_3d < target:
        return 'Efficient'
    if ratio_3d < be:
        return 'Acceptable'
    if ratio_3d < be * 1.1:
        return 'Near Break-even'
    if ratio_3d < be * 2:
        return 'Above Break-even'
    return 'Severely Above Break-even'


# ---------------------------------------------------------------------------
# Budget recommendation
# ---------------------------------------------------------------------------

def recommend_budget(score: float, current_budget: Optional[float],
                     eff_label: str, history: Optional[dict]) -> tuple:
    """Returns (recommended_budget, action_type)."""
    if _is_null(current_budget) or current_budget == 0:
        return 0, 'no_budget_data'

    # Base action from score
    if score >= 85:
        raw, action = current_budget * 1.25, 'scale_up'
    elif score >= 70:
        raw, action = current_budget * 1.15, 'scale_up_careful'
    elif score >= 50:
        raw, action = current_budget,        'hold'
    elif score >= 30:
        raw, action = current_budget * 0.95, 'watch_reduce'
    else:
        descale_map = {
            'No GMV':                    (0.0,  'pause'),
            'Structural Issue':          (0.0,  'pause'),
            'Dead':                      (0.0,  'pause'),
            'Severely Above Break-even': (0.70, 'scale_down'),
            'Above Break-even':          (0.80, 'scale_down'),
            'Near Break-even':           (0.90, 'scale_down'),
        }
        mult, action = descale_map.get(eff_label, (0.90, 'scale_down'))
        raw = current_budget * mult

    # Cooldown from history
    if history:
        last = history.get('action_type', '')
        if 'scale_up' in last and action in ('scale_down', 'pause', 'watch_reduce'):
            if eff_label not in ('No GMV', 'Severely Above Break-even', 'Structural Issue'):
                raw, action = current_budget, 'hold_cooldown'
        if 'scale_down' in last and 'scale_up' in action:
            if score < 90:
                raw, action = current_budget, 'hold_cooldown'

    return round(raw), action


# ---------------------------------------------------------------------------
# Weekly planning
# ---------------------------------------------------------------------------

def weekly_planning(x: float, z: float, yesterday_daily_spend: float,
                    current_week_spend: float, remaining_days: int) -> dict:
    # Gap = Sunday target vs current daily run rate
    remaining_gap = z - yesterday_daily_spend
    daily_pace    = remaining_gap / remaining_days if remaining_days > 0 else 0

    if x > 5000:
        cap_ratio = 0.6 if z > 2 * x else 0.5
    else:
        cap_ratio = 0.5

    existing_capacity = cap_ratio * (z - x)
    new_structure_req = (z - x) - existing_capacity

    return {
        'last_sunday_spend':     round(x, 2),
        'this_week_target':      round(z, 2),
        'yesterday_daily_spend': round(yesterday_daily_spend, 2),
        'current_week_spend':    round(current_week_spend, 2),
        'remaining_gap':         round(remaining_gap, 2),
        'required_daily_pace':   round(daily_pace, 2),
        'existing_capacity':     round(existing_capacity, 2),
        'new_structure_req':     round(new_structure_req, 2),
        'remaining_days':        remaining_days,
        'direction':             'Scale Up' if z > x else ('Scale Down' if z < x else 'Hold'),
    }


# ---------------------------------------------------------------------------
# Risk alerts
# ---------------------------------------------------------------------------

def generate_alerts(campaigns: list, plan: dict) -> list:
    alerts = []

    for c in campaigns:
        cid = c['campaign_id']

        if c['efficiency_label'] == 'No GMV' and c['spend_7d'] > 0:
            alerts.append({
                'priority': 'CRITICAL', 'campaign_id': cid,
                'message': f"Spent ₹{c['spend_7d']:.0f} in 7D with zero GMV — tracking or structural failure",
            })

        if c['efficiency_label'] == 'Severely Above Break-even':
            alerts.append({
                'priority': 'CRITICAL', 'campaign_id': cid,
                'message': (f"3D Spend/GMV {c['ratio_3d']}% is severely above "
                            f"break-even {c['be_threshold']}%"),
            })

        if (c['budget'] and c['budget'] > 0
                and c['yesterday_spend'] == 0 and c['spend_7d'] > 0):
            alerts.append({
                'priority': 'HIGH', 'campaign_id': cid,
                'message': f"Zero spend on ₹{c['budget']:.0f} budget — investigate pause/delivery issue",
            })

        if c['stability_class'] == 'Deteriorating':
            alerts.append({
                'priority': 'HIGH', 'campaign_id': cid,
                'message': (f"3D Spend/GMV {c['ratio_3d']}% deteriorating vs "
                            f"7D {c['ratio_7d']}%"),
            })

        if c.get('threshold_source') == 'account_fallback':
            alerts.append({
                'priority': 'MEDIUM', 'campaign_id': cid,
                'message': f"No {c['campaign_type']} thresholds found — using account-level fallback",
            })

    # Pace alert
    if plan['remaining_days'] <= 2 and plan['remaining_gap'] > plan['this_week_target'] * 0.25:
        alerts.append({
            'priority': 'HIGH', 'campaign_id': 'ACCOUNT',
            'message': (f"₹{plan['remaining_gap']:.0f} gap remaining with only "
                        f"{plan['remaining_days']} day(s) left — pace at risk"),
        })

    return alerts


# ---------------------------------------------------------------------------
# Capital reallocation
# ---------------------------------------------------------------------------

def capital_reallocation(campaigns: list) -> dict:
    donors, scalers = [], []

    for c in campaigns:
        if not c['budget']:
            continue
        delta = (c['recommended_budget'] or 0) - c['budget']
        if delta < 0:
            donors.append({'campaign_id': c['campaign_id'], 'freed': abs(delta),
                           'action': c['action_type']})
        elif delta > 0:
            scalers.append({'campaign_id': c['campaign_id'], 'added': delta,
                            'score': c['rebalancing_score']})

    total_freed    = round(sum(d['freed'] for d in donors), 2)
    total_deployed = round(sum(s['added'] for s in scalers), 2)

    return {
        'donors':          sorted(donors,  key=lambda x: x['freed'], reverse=True),
        'scale_candidates': sorted(scalers, key=lambda x: x['score'], reverse=True),
        'total_freed':     total_freed,
        'total_deployed':  total_deployed,
        'net_surplus':     round(total_freed - total_deployed, 2),
    }


# ---------------------------------------------------------------------------
# Main seller analysis
# ---------------------------------------------------------------------------

def analyze_seller(seller_id: str, campaigns: list, seller_be: dict,
                   x: float, z: float, current_week_spend: float,
                   history: dict, remaining_days: int) -> dict:

    yesterday_daily_spend = sum(
        float(c.get('yesterday_spend') or 0) for c in campaigns
    )
    plan = weekly_planning(x, z, yesterday_daily_spend, current_week_spend, remaining_days)
    scored = []

    for c in campaigns:
        ctype        = c.get('campaign_type')
        budget       = c.get('budget')
        y_spend      = float(c.get('yesterday_spend') or 0)
        spend_3d     = float(c.get('spend_3d') or 0)
        gmv_3d       = float(c.get('gmv_3d') or 0)
        spend_7d     = float(c.get('spend_7d') or 0)
        gmv_7d       = float(c.get('gmv_7d') or 0)

        target, be   = get_thresholds(ctype, seller_be)

        # Detect whether thresholds came from campaign type or account fallback
        type_map = {
            'demand_gen': 'demand_gen_BE_5pct', 'pmax_banner': 'pmax_banner_BE_5pct',
            'pmax_feed':  'pmax_feed_BE_5pct',  'shopping':    'shopping_BE_5pct',
            'search':     'search_BE_5pct',      'display':     'display_BE_5pct',
        }
        threshold_source = (
            'campaign_type' if (ctype and type_map.get(ctype) and seller_be.get(type_map[ctype]))
            else 'account_fallback'
        )

        r3 = spend_gmv_ratio(spend_3d, gmv_3d)
        r7 = spend_gmv_ratio(spend_7d, gmv_7d)

        eff_s  = calc_efficiency_score(r3, target, be)
        spe_s  = calc_spendability_score(y_spend, budget)
        stab_s, stab_class = calc_stability(spend_3d, gmv_3d, spend_7d, gmv_7d)

        rb_score  = calc_rebalancing_score(eff_s, spe_s, stab_s)
        state     = get_campaign_state(rb_score)
        eff_label = get_efficiency_label(r3, target, be)

        utilization = round((y_spend / budget * 100), 1) if (budget and not _is_null(budget) and budget > 0) else 0.0

        cam_history = history.get((seller_id, str(c.get('campaign_id'))))
        rec_budget, action_type = recommend_budget(rb_score, budget, eff_label, cam_history)

        budget_chg_pct = (
            round(((rec_budget - budget) / budget) * 100, 1)
            if (budget and not _is_null(budget) and budget > 0) else 0
        )

        scored.append({
            'campaign_id':        c.get('campaign_id'),
            'campaign_name':      c.get('campaign_name') or '',
            'campaign_status':    c.get('campaign_status') or '',
            'campaign_type':      ctype or 'unknown',
            'budget':             budget,
            'yesterday_spend':    round(y_spend, 2),
            'spend_3d':           round(spend_3d, 2),
            'gmv_3d':             round(gmv_3d, 2),
            'spend_7d':           round(spend_7d, 2),
            'gmv_7d':             round(gmv_7d, 2),
            'ratio_3d':           r3 if r3 != float('inf') else 'inf',
            'ratio_7d':           r7 if r7 != float('inf') else 'inf',
            'target_threshold':   target,
            'be_threshold':       be,
            'threshold_source':   threshold_source,
            'spend_utilization':  utilization,
            'efficiency_label':   eff_label,
            'stability_class':    stab_class,
            'history':            cam_history,
            'efficiency_score':   eff_s,
            'spendability_score': spe_s,
            'stability_score':    stab_s,
            'rebalancing_score':  rb_score,
            'campaign_state':     state,
            'action_type':        action_type,
            'recommended_budget': rec_budget,
            'budget_change_pct':  budget_chg_pct,
        })

    alerts  = generate_alerts(scored, plan)
    realloc = capital_reallocation(scored)

    # Account-level aggregates
    total_spend_3d = sum(float(c.get('spend_3d') or 0) for c in campaigns)
    total_gmv_3d   = sum(float(c.get('gmv_3d')   or 0) for c in campaigns)
    total_spend_7d = sum(float(c.get('spend_7d') or 0) for c in campaigns)
    total_gmv_7d   = sum(float(c.get('gmv_7d')   or 0) for c in campaigns)
    account_ratio_3d = spend_gmv_ratio(total_spend_3d, total_gmv_3d)
    account_ratio_7d = spend_gmv_ratio(total_spend_7d, total_gmv_7d)
    account_be_target = seller_be.get('account_BE_5pct')
    account_be_0pct   = seller_be.get('account_BE_0pct')

    return {
        'seller_id':        seller_id,
        'seller_name':      '',   # filled in by run_all_sellers
        'weekly_plan':      plan,
        'campaigns':        scored,
        'alerts':           alerts,
        'reallocation':     realloc,
        'account_metrics': {
            'ratio_3d':    account_ratio_3d,
            'ratio_7d':    account_ratio_7d,
            'be_target':   account_be_target,
            'be_0pct':     account_be_0pct,
            'total_spend_3d': round(total_spend_3d, 2),
            'total_gmv_3d':   round(total_gmv_3d, 2),
        },
    }


# ---------------------------------------------------------------------------
# Run all sellers
# ---------------------------------------------------------------------------

def run_all_sellers(campaign_df, be_df, targets_df, week_spend_df, history: dict) -> dict:
    remaining_days = get_remaining_days()
    results = {}

    # Index dataframes
    be_lookup      = be_df.set_index('seller_id').to_dict('index')
    targets_lookup = targets_df.set_index('seller_id').to_dict('index')
    week_lookup    = week_spend_df.set_index('seller_id')['current_week_spend'].to_dict()

    for seller_id, grp in campaign_df.groupby('seller_id'):
        seller_be      = be_lookup.get(seller_id, {})
        targets        = targets_lookup.get(seller_id, {})
        x              = float(targets.get('last_sunday_spend', 0) or 0)
        z              = float(targets.get('this_week_target', 0) or 0)
        cw_spend       = float(week_lookup.get(seller_id, 0) or 0)
        campaigns_list = grp.to_dict('records')

        seller_name = targets.get('seller_name') or ''
        result = analyze_seller(
            seller_id, campaigns_list, seller_be,
            x, z, cw_spend, history, remaining_days
        )
        result['seller_name'] = seller_name
        results[seller_id] = result

    return results
