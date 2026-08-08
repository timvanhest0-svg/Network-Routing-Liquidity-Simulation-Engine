"""
definitions.py — Single glossary of engine terms, formulas, and implementation notes.

Provides the source of definitions for the Network Routing Liquidity
Engine, covering the network mechanism (tail exponent, liquidity multipliers,
routing capacity), the risk definitions (risk day, risk scenario, threshold), the
imperfect EWI (recall, precision, lead time), and the mitigation policy (buffer
release, central-bank injection, combined support) and its outcome metrics
(shortfall, reductions, efficiency).

ROWS is a list of (Term, Definition, Formula / implementation) tuples. Each 'Formula'
mirrors the actual variable names used in the codebase, so the glossary doubles as a
quick code-reference. glossary_dataframe() returns the rows as a DataFrame; the app
renders it as a searchable table on the Definitions page and includes it in the
Excel/CSV export.
"""
import pandas as pd

ROWS = [
    # ---- Network mechanism -------------------------------------------------
    ('Tail exponent (γ)', 'Concentration parameter of the power-law degree distribution. Lower γ = heavier tail, more hub concentration, higher routing multiplier; higher γ = thinner tail, lower routing capacity. Drawn as a calibrated mean-reverting stochastic path.', 'p(k) proportional to k**(-gamma); drawn per scenario-day'),
    ('Network size (N)', 'Number of intermediary nodes. With γ, fixes the implied degree distribution and hence the routing multipliers.', 'K = N - 1 (support of the degree distribution)'),
    ('Direct liquidity multiplier (LM)', 'Expected degree of the implied distribution; scales base liquidity into direct routing capacity.', 'LM = E[k]'),
    ('Indirect liquidity multiplier (ILM)', 'Expected excess degree; branching/pass-through capacity once liquidity has entered the network. Diagnostic only.', 'ILM = E[k**2] / E[k] - 1'),
    ('Available base liquidity', 'Investment base net of the normal unavailable-liquidity buffer, before the routing multiplier is applied.', 'baseline_available = investment * (1 - buffer_normal_pct/100)'),
    ('Network-adjusted direct routing capacity', 'Available base liquidity multiplied by the direct network-liquidity multiplier based on E[k]. This measure defines liquidity-risk events.', 'direct_liquidity = baseline_available * LM'),
    ('Network-adjusted indirect routing capacity', 'Available base liquidity multiplied by E[k^2] / E[k] - 1. It is shown for comparison only.', 'indirect_liquidity = baseline_available * ILM'),

    # ---- Gamma-process definitions ---------------------------------------------
    (r'$\mu_\gamma$','Long-run mean of the positive tail exponent γ. The simulation models log(γ) as a mean-reverting process and transforms it back to levels.',
    r'$\mu_\gamma = E[\gamma_t]$',),
    (r'$\sigma_\gamma$','Long-run standard deviation of the tail exponent γ. It determines the dispersion of simulated network states.',r'$\sigma_\gamma = \sqrt{\mathrm{Var}(\gamma_t)}$',),
    ('Memory function half-life (days)',
     'Number of trading days required for the expected deviation of log(γ) from its long-run mean to decline by 50%. A higher half-life implies slower mean reversion and greater persistence.',
     r'$h=\ln(0.5)/\ln(\phi)$; equivalently, $\phi=\exp[-\ln(2)/h]$'),
    (r'Mean-reverting log-$\gamma$ process',
     'AR(1) process for log(γ). The logarithmic specification ensures that the simulated tail exponent remains positive.',
     r'$\log(\gamma_{t+1})=\mu_{\log\gamma}+\phi[\log(\gamma_t)-\mu_{\log\gamma}]+\sigma_\varepsilon\varepsilon_{t+1}$'),

    # ---- Risk definitions --------------------------------------------------
    ('Liquidity-risk threshold quantile (q)', 'The percentile (in percentage points, 1-10) defining the risk threshold. Anchor to observed crisis levels.', 'q in percent; passed as q/100 to the quantile'),
    ('Liquidity-risk threshold', 'Routing-capacity level below which a day counts as a liquidity-risk day; the q-th percentile of direct capacity in the run.', 'risk_threshold = quantile(direct_liquidity, q/100)'),
    ('Liquidity-risk day', 'A scenario-day on which network-adjusted direct routing capacity falls below the liquidity-risk threshold.', 'direct_liquidity < risk_threshold'),
    ('Liquidity-risk scenario', 'A simulated path with at least one liquidity-risk day.', 'risk.any(axis=1)'),

    # ---- Early-warning indicator (EWI) ------------------------------------
    ('Fixed EWI lead time', 'Trading days before a liquidity-risk event at which a true EWI signal is placed.', 'signal_day = event_day - lead_time'),
    ('Target recall', 'Intended percentage of evaluable liquidity-risk event days receiving a true signal.', 'target_recall * evaluable_event_days'),
    ('Target precision', 'Intended percentage of signal days that are true positives.', 'true_positive_signals / total_signals'),

    # ---- Mitigation policy -------------------------------------------------
    ('Support active days', 'Scenario-days on which mitigation is active (EWI signal + start delay, for the support duration).', 'support_active_days = active_mask.sum()'),
    ('Buffer release', 'A dynamic reduction of the normal unavailable-liquidity buffer on EWI support days. Self-funded liquidity the fund already holds back is released to raise available base liquidity. Capped at the normal buffer.', 'buffer_release_volume = investment * buffer_release_pct/100 * support_active_days (capped at buffer_normal_pct)'),
    ('Central-bank liquidity injection', 'External liquidity added on EWI support days on top of available base liquidity. With the buffer release it forms the combined liquidity support level; both enter additively and are network-scaled by the direct multiplier.', 'injection_volume = investment * injection_pct/100 * support_active_days; combined_support_pct = buffer_release_pct + injection_pct'),
    ('Combined liquidity support level', 'The sum of the buffer release and the central-bank injection. This is the value that drives the mitigation policy.', 'combined_support_pct = buffer_release_pct + injection_pct'),
    ('**1. Baseline: no intervention.**','No additional support is provided and the normal unavailable liquidity buffer remains in place. This is the reference case for all policy comparisons.', 'baseline_available = investment * (1 - buffer_normal_pct / 100)'),   
    ('**2. Reactive countercyclical intervention.**', 'Support is activated reactively after a realized liquidity-risk day, subject to the configured start delay and support duration. The strategy uses realized stress information rather than an advance-warning signal.', 
     'countercyclical_liquidity = '
            '(baseline_available + '
            'investment * combined_support_pct / 100 '
            '* countercyclical_active_mask) * direct_lm'
    ),
    ('**3. EWI-targeted intervention.**','Support is activated following an imperfect EWI signal, subject to the configured recall, precision, lead time, start delay, and support duration. The reported outcome is the result of the reproducible EWI realization, not a median across replications.',
        (
            'ewi_liquidity = baseline_available + investment * combined_support_pct / 100 '
            '* ewi_active_mask) * direct_lm'
        ),
    ),

    ('**4. Randomized timing with equal support volume.**',
        (
            'The same number of active support days and the same support '
            'intensity as the EWI intervention are assigned to randomly '
            'selected scenario-days. The median outcome across randomized-'
            'timing replications is reported.'
        ),
        (
            'randomized_liquidity_r = (baseline_available + '
            'investment * combined_support_pct / 100 '
            '* randomized_active_mask_r) * direct_lm; '
            'reported outcome = median across replications r'
        ),
    ),

    ('**5. Perfect-information oracle with equal support volume.**',
        (
            'The oracle allocates the same active-day budget and support '
            'intensity as the EWI intervention to the weakest realized '
            'baseline routing-capacity observations. It is an infeasible '
            'ex-post upper benchmark, not a perfect EWI and not a median '
            'across replications.'
        ),
        (
            'oracle_liquidity = '
            '(baseline_available + '
            'investment * combined_support_pct / 100 '
            '* oracle_active_mask) * direct_lm'
        ),
    ),

    # ---- Outcome metrics ---------------------------------------------------
    ('Total routing-capacity shortfall', 'Cumulative amount by which direct routing capacity falls below the threshold, summed over all risk days.', 'sum(max(risk_threshold - direct_liquidity, 0))'),
    ('Total routing liquidity available', 'Sum of baseline direct routing capacity over all scenario-days; the 100% baseline for relative figures.', 'total_available = direct_liquidity.sum()'),
    ('Policy support intensity', 'Realized support relative to baseline available capacity over all scenario-days.', 'sum(support) / (baseline_available * scenario_days)'),
    ('Risk-day reduction', 'Percentage reduction in risk days relative to no mitigation.', '(baseline - policy) / baseline * 100'),
    ('Shortfall reduction', 'Percentage reduction in cumulative routing-capacity shortfall relative to no mitigation.', '(baseline_shortfall - policy_shortfall) / baseline_shortfall * 100'),
    ('Mitigation efficiency', 'Shortfall reduction per percentage point of realized support intensity.', 'shortfall_reduction_pct / support_intensity_pct'),
]


def glossary_dataframe():
    return pd.DataFrame(ROWS, columns=['Term', 'Definition', 'Formula / implementation'])