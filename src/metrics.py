"""
metrics.py — Liquidity-risk evaluation and policy-outcome metrics.

Pure, deterministic numerical core of the engine: given a routing-capacity array
and a risk threshold, it computes the baseline risk statistics; given a baseline
and a policy outcome, it computes the reduction/efficiency metrics reported on the
Mitigation-results page.

REPRODUCIBILITY NOTES
---------------------------------
* No randomness, no I/O, no global state — every output is a deterministic function
  of the inputs, so results are exactly reproducible and unit-testable in isolation.
* Division guards: all ratios (reductions, intensity, efficiency) return np.nan when
  the denominator is non-positive, so an empty/zero baseline can never raise or
  silently produce inf. NaNs propagate visibly to the UI rather than corrupting it.
* Units are explicit: rates and reductions are expressed in percent (×100); volumes
  and shortfalls are in the same units as the input liquidity array.
* Key names here are the contract consumed downstream (comparison.py, app.py):
  'total_shortfall', 'total_support_volume', 'support_active_days', etc.
"""
import numpy as np


def evaluate_liquidity(arr, threshold):
    """Baseline liquidity-risk statistics for a (scenarios × days) capacity array.

    A scenario-day is a *risk day* when routing capacity is strictly below the
    threshold; its shortfall is the positive gap to the threshold (0 otherwise).

    REPRODUCIBILITY NOTES
      * arr is coerced to float and never mutated (np.asarray copy-on-cast).
      * risk_day_rate / risk_scenario_rate are shares ×100 (percent).
      * risk.any(1) reduces over the day axis, so a scenario counts once regardless
        of how many risk days it contains.
      * total_shortfall sums only non-negative gaps (np.maximum(0, ...)), so days
        above threshold contribute exactly 0 and cannot offset shortfalls.
    """
    a = np.asarray(arr, float)
    risk = a < threshold                      # strict: capacity exactly at threshold is NOT a risk day
    short = np.maximum(0, threshold - a)       # per-day shortfall, floored at 0
    return {'risk_days': int(risk.sum()), 'risk_day_rate': float(risk.mean() * 100),
            'risk_scenarios': int(risk.any(1).sum()), 'risk_scenario_rate': float(risk.any(1).mean() * 100),
            'total_shortfall': float(short.sum())}


def safe_reduction(base, value):
    """Percentage reduction of value relative to base, guarded against base <= 0.

    REPRODUCIBILITY NOTES: returns np.nan (not inf/ZeroDivisionError) when base <= 0, so a run
    with no baseline risk/shortfall yields a visible NaN rather than a spurious number.
    """
    return (base - value) / base * 100 if base > 0 else np.nan

def policy_extras(base, outcome, support, available):
    """Policy-outcome metrics: reductions, realized support, and efficiency.

    Parameters mirror one policy run: `base` (no-mitigation stats), `outcome`
    (post-policy stats), `support` (realized support array), and `available`
    (per-day available base liquidity).

      * realized_support_intensity = total support / (available × #cells) ×100 — the
        realized spend as a share of total available base liquidity; guarded on
        available > 0.
      * shortfall/risk-day reductions reuse safe_reduction, so both share the same
        denominator guard.
      * support_active_days counts non-zero support cells (np.count_nonzero) — the
        equal-spend control checked against the random benchmark.
      * mitigation_efficiency = shortfall reduction per point of support intensity;
        guarded on intensity > 0.
      * total_support_volume is the summed realized support — the exact key consumed
        by build_policy_comparison() and the random-benchmark median (naming contract).
      * intensity denominator is support.size = (scenarios × trading_days), i.e. TOTAL available base liquidity across ALL scenario-days, not only active days. 
    """
    intensity = support.sum() / (available * support.size) * 100 if available > 0 else np.nan
    sr = safe_reduction(base['total_shortfall'], outcome['total_shortfall'])
    return {'risk_day_reduction_pct': safe_reduction(base['risk_days'], outcome['risk_days']),
            'shortfall_reduction_pct': sr, 'support_active_days': int(np.count_nonzero(support)),
            'total_support_volume': float(support.sum()), 'realized_support_intensity_pct': float(intensity),
            'mitigation_efficiency': sr / intensity if intensity > 0 else np.nan}