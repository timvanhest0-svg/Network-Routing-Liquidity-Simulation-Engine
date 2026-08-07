"""
Network Routing Liquidity Engine — Streamlit application.

A simulation-based framework for liquidity-risk assessment and mitigation on a
preferential-attachment style network. The engine operationalizes the
network-based view of systemic liquidity risk developed in the thesis
"Network behavior and liquidity crises": liquidity risk depends not only on how
much liquidity sits on balance sheets, but on whether the network can still
*route* that liquidity to where it is needed under stress.

A time-varying mean-reverting tail exponent shapes a power-law degree distribution whose
expected degree acts as a direct routing multiplier. Network-adjusted routing
capacity is available base liquidity multiplied by that multiplier, and
liquidity-risk days are defined from the direct capacity. An imperfect
early-warning indicator (EWI) triggers mitigation delivered through two additive
channels: a dynamic buffer release and a central-bank injection.

Pages:
  0. Overview — objective and how to read the engine.
  1. Network simulation and routing paths — realized gamma and multiplier distributions, single- and all-scenario paths.
  2. Risk metrics and EWI settings - design and evaluation.
  3. Mitigation results — random vs. EWI-triggered support at equal volume.
  4. Definitions - Glossary of terms.
  5. Downloads - Figures and results.
"""
from __future__ import annotations
from email.policy import default
import os
import numpy as np, pandas as pd, streamlit as st
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.simulation import SimulationConfig, simulate_base_paths
from src.topology import make_multiplier_grids
from src.ewi import EWIConfig, create_ewi
from src.policy import (
    PolicyConfig,
    forward_active_mask,
    event_delayed_active_mask,
    oracle_active_mask_same_volume,
    run_policy,
    run_random_benchmarks,
    support_split,
)
from src.metrics import evaluate_liquidity
from src.plotting import (routing_paths_figure, all_simulation_paths_figure, multiplier_distribution_figure)
from src.comparison import (build_policy_comparison, policy_comparison_figure,
                            figure_to_png_bytes, png_zip_bytes, tables_to_excel_bytes)
from src.definitions import glossary_dataframe

st.set_page_config(page_title='Network Routing Liquidity Engine', layout='wide')
diag = {}

# Brand logo in the sidebar (place the PNG in assets/). Guarded so the app still
# runs if the asset is missing.
_LOGO = os.path.join(os.path.dirname(__file__), 'assets', 'NetworkSimulationEngineLogo.png')
if os.path.exists(_LOGO):
    st.sidebar.image(_LOGO, use_container_width=True)
title = 'Network Routing Liquidity Engine'; st.title(title)
st.caption('A simulation-based framework for network liquidity-risk assessment and mitigation')

# --- Default session state ---------------------------------------------------
# Support is split into two additive channels (buffer_release + injection); the
# simulation is driven by their sum (PolicyConfig.combined_support_pct).
D = dict(n_nodes=24, scenarios=1000, trading_days=200, seed=42, investment=100.,
         buffer=40., q=5., sigma=.538, mu=1.157, halftime=10, recall=.70, precision=.25,
         lead=5, buffer_release=5., injection=5., duration=10, delay=5, reps=1000)
for k, v in D.items():
    st.session_state.setdefault(k, v)

# --- Navigation --------------------------------------------------------------
PAGE_OVERVIEW    = 'Overview'
PAGE_NETWORK     = 'Network simulation and routing paths'
PAGE_EWI         = 'Risk metrics and EWI settings'
PAGE_POLICY      = 'Mitigation results'
PAGE_DEFINITIONS = 'Model Definitions - Glossary of terms'
PAGE_DOWNLOADS   = 'Downloads - Figures and results'

PAGES = [PAGE_OVERVIEW, PAGE_NETWORK, PAGE_EWI, PAGE_POLICY, PAGE_DEFINITIONS, PAGE_DOWNLOADS]

# Map each page to its display number
_LABELS = {p: f'{i}.\u00a0{p}' for i, p in enumerate(PAGES)}

page = st.sidebar.radio('Navigate engine', PAGES, format_func=lambda p: _LABELS[p])


def net_controls():
    """Sidebar inputs for the network / simulation configuration."""
    s = st.session_state
    s.n_nodes = st.number_input('Network size', 10, 150, int(s.n_nodes), help='Number of intermediary nodes. With γ, fixes the implied degree distribution and the routing multiplier LM = E[k]. Larger N adds potential routing nodes.')
    s.scenarios = st.number_input('Simulation scenarios', 100, 10000, int(s.scenarios), 100, help='Number of independent stochastic paths. More scenarios sharpen the outcome distribution.')
    s.trading_days = st.number_input('Trading days', 20, 1000, int(s.trading_days), 10, help='Number of trading days for each simulation scenario.')
    s.seed = st.number_input('Random seed', 1, 999999, int(s.seed), help='Seed for the random number generator.')
    s.investment = st.number_input('Investment base', 1., 1000., float(s.investment), 100., help='Base investment amount. Total liquidity available to route, before the multiplier is applied. Outcomes are expressed relative to this amount.')
    s.buffer = st.slider('Liquidity buffer (%)', 0., 90., float(s.buffer), 5., help='Percentage of liquidity to keep as a buffer. Each actor keeps this share of its base liquidity unavailable for routing. The buffer is subtracted before the multiplier is applied.')
    s.q = st.slider('Liquidity-risk threshold quantile (%)', 1.0, 25.0,
                    float(min(max(s.q, 1.0), 25.0)), 0.5, format='%.1f', help='Quantile of routing capacity below which a day is flagged as a liquidity-risk day. Anchor to observed crisis levels.')
    with st.expander('Tail exponent (γ) mean-reverting distribution settings'):
        s.mu = st.number_input('Mean of the daily tail exponent γ', 0.1, 5., float(s.mu), 0.1, help='Mean of the daily tail-exponent draw. Higher μ shifts the distribution right, lowering the average multiplier and routing capacity.')
        s.sigma = st.number_input('Volatility of the daily tail exponent γ', .01, 5., float(s.sigma), 0.01, help='Volatility of the tail-exponent draw. Higher σ widens the spread of network states.')
        s.halftime = st.number_input('Memory function, half-life (h) in days', 5, 60, int(s.halftime), 5, help='Memory function half-life (in days) for the daily tail-exponent draw to return to the mean. Higher = more persistence in network states.')
        st.markdown('Note: the engine draws a daily log-γ AR(1) process with half-life (h) from the log transformed distribution. The μ and σ parameters are the γ-distribution parameters themselves; **not** the log-γ distribution parameters.')


# --- Page-specific sidebar controls -----------------------------------------
s = st.session_state
if page == PAGE_EWI:
    st.sidebar.divider()
    st.sidebar.subheader('2. EWI settings')
    s.recall = st.sidebar.slider('Target recall', 0., 1., float(s.recall), .05, key='ewi_target_recall', help='Fraction of true risk days the EWI should catch. Higher = fewer misses, but more false alarms.')
    s.precision = st.sidebar.slider('Target precision', .05, 1., float(s.precision), .05, key='ewi_target_precision', help='Fraction of detected risk days that are true positives. Higher = fewer false alarms, but more misses.')
    s.lead = st.sidebar.slider(
        'Fixed EWI lead time (days)', 1, min(20, int(s.trading_days) - 1),
        min(int(s.lead), int(s.trading_days) - 1), key='ewi_fixed_lead_time', help='Fixed lead time for the EWI.'
    )
elif page == PAGE_POLICY:
    st.sidebar.divider()
    st.sidebar.subheader('3. Policy settings')
    s.delay = st.sidebar.slider('Support-start delay (days)', 1, 20, int(s.delay), key='policy_start_delay', help='Delay before support measures are initiated.')
    s.duration = st.sidebar.slider('Number of support days', 1, 30, int(s.duration), key='policy_support_days', help='Duration of the support period.')
    # Two separate, economically additive support channels.
    s.buffer_release = st.sidebar.slider('Buffer release on support days (%)', 0, int(s.buffer), 5, 5,key='policy_buffer_release', help='Percentage of the buffer to release during the support period.')
    s.injection = st.sidebar.slider('Central-bank injection (%)', 0, 50, 5, 5, key='policy_injection', help='Percentage of liquidity to inject from the central bank.')
    st.sidebar.caption(f'Combined liquidity support level: {s.buffer_release + s.injection:.0f}%')


def configs():
    """Assemble the three config objects from the current session state.

    Buffer release and injection are passed to PolicyConfig as separate
    channels and validated against the normal buffer (release cannot exceed it).
    """
    s = st.session_state
    p = PolicyConfig(s.buffer_release, s.injection, s.duration, s.delay)
    p.validate(float(s.buffer))
    return (SimulationConfig(s.n_nodes, s.scenarios, s.trading_days, s.investment, s.buffer,
                             s.q, s.seed, s.mu, s.sigma, s.halftime),
            EWIConfig(s.recall, s.precision, s.lead, s.seed),
            p)


@st.cache_data(show_spinner=False)
def compute(n, e, p, reps):
    """Run the full pipeline once (cached): simulation, EWI, mitigation, benchmark."""
    sim = simulate_base_paths(n)
    base = evaluate_liquidity(sim['direct_liquidity'], sim['risk_threshold'])
    flags, diag = create_ewi(np.asarray(sim['event_day'], dtype=bool), e)
    # 1. EWI-targeted intervention: starts after an advance-warning flag.
    ewi_active = forward_active_mask(flags, p.support_days, p.start_delay)

    # 2. Reactive countercyclical intervention: starts after a realized risk day.
    counter_active = event_delayed_active_mask(
        np.asarray(sim['event_day'], dtype=bool),
        p.support_days,
        p.start_delay,
    )

    # 3. Perfect-information oracle: same active-day budget as the EWI rule,
    # allocated ex post to the weakest baseline routing-capacity observations.
    oracle_active = oracle_active_mask_same_volume(
        sim['direct_liquidity'],
        sim['risk_threshold'],
        ewi_active,
    )

    _, em, ex, _ = run_policy(
        sim['direct_lm'], sim['risk_threshold'], base, n.investment,
        n.buffer_normal_pct, ewi_active, p.combined_support_pct,
    )
    _, cm, cx, _ = run_policy(
        sim['direct_lm'], sim['risk_threshold'], base, n.investment,
        n.buffer_normal_pct, counter_active, p.combined_support_pct,
    )
    _, om, ox, _ = run_policy(
        sim['direct_lm'], sim['risk_threshold'], base, n.investment,
        n.buffer_normal_pct, oracle_active, p.combined_support_pct,
    )

    # Randomized timing uses the EWI rule's active-day count and support level.
    rnd = run_random_benchmarks(
        sim['direct_lm'], sim['risk_threshold'], base, n.investment,
        n.buffer_normal_pct, ewi_active, p.combined_support_pct,
        reps, n.seed + 1000,
    )
    return sim, base, diag, em, ex, rnd, cm, cx, om, ox


def comparison_table(base, rnd, em, ex, total_available, cm=None, cx=None, om=None, ox=None):
    """Build the five-strategy comparison and attach relative shortfall."""
    countercyclical = {**(cm or {}), **(cx or {})}
    ewi = {**(em or {}), **(ex or {})}
    oracle = {**(om or {}), **(ox or {})}

    df = build_policy_comparison(
        base,
        countercyclical,
        ewi,
        rnd,
        oracle,
    )
    shortfall_abs = pd.to_numeric(
        df['Total routing-capacity shortfall'], errors='coerce'
    )
    df['Routing-capacity shortfall (% of available)'] = (
        shortfall_abs / total_available * 100
        if total_available and total_available > 0
        else np.nan
    )
    return df


def _to_float_scalar(x):
    v = pd.to_numeric(x, errors='coerce')
    return float(v) if not pd.isna(v) else float('nan')


# =============================================================================
# PAGE 0 — Overview
# =============================================================================
if page == PAGE_OVERVIEW:
    st.header('Overview')
    st.markdown(
        'A financial system is not resilient simply because liquidity exists **somewhere** in it. '
        'It is resilient when liquidity can still **reach the parts of the system where pressure is concentrated**. '
        'This engine is a controlled *policy laboratory* built on the network-based view of systemic liquidity risk '
        'developed in the thesis **"Network behavior and liquidity crises."**'
    )
    st.divider()
    st.subheader('How to read the pages')
    st.markdown(
        '0. **Overview** — this page: the engine\'s set-up, objective and how to set the simulation parameters.\n'
        '1. **Network simulation and routing paths** — the tail exponent (γ) and liquidity multiplier distributions that drive routing capacity, shown for single and multiple simulated paths.\n'
        '2. **EWI settings and evaluation** — liquidity risk evaluation settings and targets for how good the early-warning signal is (recall, precision, lead time).\n'
        '3. **Mitigation results** — the headline result: does targeting beat random spending at equal volume?\n'
        '4. **Model Definitions** — every term and formula explained.\n'
        '5. **Downloads** — figures, settings, and full results.'
    )
    st.divider()
    c = st.columns(2)
    with c[0]:
        st.subheader('The core idea')
        st.markdown(
            '- **Balance-sheet capacity** — how much liquidity institutions can supply under funding, '
            'collateral, capital, and risk constraints.\n'
            '- **Routing capacity** — how effectively the network can *move* that liquidity across participants '
            'through direct and indirect intermediation links.\n\n'
            'Liquidity stress becomes **systemic** when these two weaken together: liquidity still exists, '
            'but it no longer reaches where it is needed. The engine isolates the **routing** side.'
        )
    with c[1]:
        st.subheader('The policy question it addresses')
        st.markdown(
            'The simulation does **not** forecast a specific crisis. It asks a sharper, testable question:\n\n'
            '*Can early-warning-triggered interventions measurably reduce simulated liquidity shortfalls?*\n\n'
            'It answers by comparing **targeted (EWI-triggered)** support against **untargeted (random)** support '
            'delivered at the **same total volume**.'
        )
    st.divider()
    st.subheader('Network routing capacity and liquidity risk simulation mechanism')
    st.info(
        'Network-based routing capacity is set jointly by network size **N** and tail exponent **γ**, '
        'which together fix the implied degree distribution and the direct and indirect liquidity multipliers '
        '(LM = E[k] and ILM = E[k²]/E[k] − 1). For a given **N**, a heavier tail (low **γ**) concentrates '
        'connectivity in a few hubs and raises LM; a thinner tail (high **γ**) spreads it out and lowers LM.\n\n'
        'The simulation feeds a real-world–calibrated mean-reverting stochastic path for **γ** through this mapping. Each draw, '
        'combined with N, yields an LM and ILM, and hence a routing-capacity level. When routing capacity falls '
        'below the pre-set risk threshold, the period is flagged as a liquidity-risk day.\n\n'
        'Support enters before it is network-scaled, so the same injection reaches fewer routes when LM is low — '
        'interventions are therefore weakest exactly on the risk days when they are needed most. See the Network '
        'simulation page for the plotted relationship, and the model description for details.'
    )

    st.subheader('Setting the network simulation engine parameters')
    st.markdown(
        'Use the sidebar sliders to configure a run. Parameters fall into three groups: '
        '**network**, **EWI**, and **policy** settings. Set them first, then start the run; '
        'every panel updates from the same configuration.'
    )


    # Shared column configuration so the first column is the same narrow width in every table.
    _col_cfg = {
        'Parameter': st.column_config.TextColumn('Parameter', width=50),
        'What it does': st.column_config.TextColumn('What it does', width='large'),
    }

    # ---- Network settings ----
    with st.expander('**1. Network settings** draw the stochastic topologies and turn them into routing capacity', expanded=True):
        st.markdown('**Core network & run controls**')
        st.dataframe(pd.DataFrame({
            'Parameter': [
                'Network size N', 'Simulation scenarios', 'Trading days',
                'Random seed', 'Investment base',
                'Normal unavailable-liquidity buffer', 'Liquidity-risk threshold quantile',
            ],
            'What it does': [
                'Number of intermediary nodes. With γ, fixes the implied degree distribution and the routing multiplier LM = E[k]. Larger N adds potential routing nodes.',
                'Number of independent stochastic paths. More scenarios sharpen the outcome distribution.',
                'Number of periods per path. Longer horizons give more opportunity for risk days.',
                'Random seed. Fix it to reproduce a run; change it to explore a different path.',
                'Total liquidity available to route, before the multiplier is applied.',
                'Share of the base normally unavailable for routing; subtracted before the multiplier is applied.',
                'Quantile of routing capacity below which a day is flagged as a risk day; anchor to observed crisis levels.',
            ],
        }), hide_index=True, use_container_width=True, column_config=_col_cfg)
        st.markdown('**Tail-exponent (γ) distribution**')
        st.dataframe(pd.DataFrame({
            'Parameter': ['mu (mean)', 'sigma (volatility)', 'Halftime (days)'],
            'What it does': [
                'Mean of the daily tail exponent γ. Higher μ shifts the distribution right, lowering the average multiplier and routing capacity.',
                'Volatility of the tail-exponent draw. Higher σ widens the spread of network states.', 
                'Memory function half-life (in days) for the daily tail-exponent draw to return to the mean. Higher = more persistence in network states.',
            ],
        }), hide_index=True, use_container_width=True, column_config=_col_cfg)
        st.caption(r'Tail exponent distribution default parameters are estimated on the basis of real-world daily γ data during the dash-for-cash period. The simulated model is a mean-reverting stochastic process that draws a daily log-γ from the log transformed distribution (to ensure that simulated γ > 0), which then shapes the network degree distribution and the resulting routing multipliers. The engine uses the realized γ and multiplier distributions to determine routing capacity and liquidity-risk days. Note that the $\mu$ and $\sigma$ parameters are the γ-distribution parameters themselves; **not** the log-γ distribution parameters.')

    # ---- EWI settings ----
    with st.expander('**2. EWI settings** decide how reliably risk days are detected in advance.'):
        st.dataframe(pd.DataFrame({
            'Parameter': ['Target recall', 'Target precision', 'Fixed EWI lead time (days)'],
            'What it does': [
                'Fraction of true risk days the EWI should catch. Higher = fewer misses, but more false alarms.',
                'Fraction of signals that are true positives. Higher = fewer false alarms, but more misses.',
                'How many days ahead the EWI signals. Longer lead gives more time to react, but is harder to achieve.',
            ],
        }), hide_index=True, use_container_width=True, column_config=_col_cfg)
        st.caption('Recall and precision trade off against each other — raising one typically lowers the other.')

    # ---- Policy settings ----
    with st.expander('**3. Policy settings** decide how support responds once the EWI fires.'):
        st.dataframe(pd.DataFrame({
            'Parameter': [
                'Support-start delay (days)', 'Number of support days',
                'Buffer release on support days (%)', 'Central-bank injection (%)',
            ],
            'What it does': [
                'Days between an EWI signal and support activation. Shorter = faster response.',
                'How long support is provided. Longer sustains liquidity but costs more.',
                'Share of the normal buffer released while support is active — adds immediate liquidity.',
                'Share of the investment base injected by the central bank while support is active.',
            ],
        }), hide_index=True, use_container_width=True, column_config=_col_cfg)
        st.caption('Buffer release and liquidity injection are two mechanisms that can be used to provide liquidity during times of stress. Practical implementation (timing, sourcing) differs, but the engine treats them as additive and independent for clarity.')

    st.info('**Tip:** start with a single-scenario smoke test (**S = 1**) to check the setup, '
            'then scale up the scenario count once the parameters look right.', icon='💡')

# =============================================================================
# PAGE 1 — Network simulation and routing paths
# =============================================================================
elif page == PAGE_NETWORK:
    with st.sidebar:
        st.subheader('Network settings'); net_controls()
    n, e, p = configs(); sim = simulate_base_paths(n); st.header('1. Network simulation')
    # Ensure risk_threshold is a plain Python float (some runs return a numpy scalar/array)
    try:
        _risk_threshold = float(np.array(sim['risk_threshold']).ravel()[0])
    except Exception:
        _risk_threshold = float(sim['risk_threshold'])
    st.markdown('This page shows how network-adjusted routing capacity evolves over the trading horizon. Each trading day draws a tail exponent that shapes the degree distribution; its expected degree is the direct routing multiplier that scales available base liquidity into routing capacity.')
    # The driver: realized γ and multiplier distributions.
    st.subheader('1.1 What drives routing capacity: the tail exponent')
    st.pyplot(multiplier_distribution_figure(sim['gamma'], sim['direct_lm'], sim['indirect_lm'], s.q))
    st.caption('Left: the distribution of daily tail exponents actually drawn in this run. Right: the resulting direct routing multipliers. Because the multiplier falls as the tail exponent rises, the right-skewed γ distribution maps into a left-skewed multiplier distribution - the low-multiplier tail is exactly where routing capacity contracts and risk days occur. The liquidity-risk threshold is the 5% worst level of routing capacity in this run; days below it are counted as liquidity-risk days. The direct routing multiplier is the expected degree of the network, which scales available base liquidity into network-adjusted routing capacity. The indirect routing multiplier is a diagnostic only. Target half-life of the mean-reverting γ process is 10 days (= memory function); the realized half-life in this run is indicated by the median realized half-life in days.')
    st.divider()
    # Single displayed scenario.
    st.subheader('1.2 A single scenario')
    scenario = st.slider('Displayed scenario', 1, n.scenarios, 1) - 1
    st.pyplot(routing_paths_figure(sim['direct_liquidity'], sim['indirect_liquidity'], _risk_threshold, scenario, n.investment))
    # Anchor capacity to the investment base for intuition.
    med_mult = float(np.median(sim['direct_liquidity']) / sim['baseline_available']) if sim['baseline_available'] else float('nan')
    thr_mult = float(_risk_threshold / n.investment)
    st.info(f"Network-adjusted direct routing capacity equals available base liquidity multiplied by the direct routing multiplier. It is not bounded at the investment-base reference of {n.investment:,.0f}. In this run the median scenario routes about {med_mult:.1f}x the available base, while the risk threshold sits at roughly {thr_mult:.1f}x the investment base. Direct capacity defines liquidity-risk days; indirect capacity is diagnostic only.")
    st.caption(f"The liquidity-risk threshold is the {n.liquidity_risk_q/100:.1%} worst level of routing capacity in this run ({_risk_threshold:,.2f}); days below it are counted as liquidity-risk days.")
    st.divider()
    # All-scenario routing-capacity paths.
    st.subheader('1.3 Routing-capacity paths across all simulations')
    st.markdown('The chart below overlays the routing-capacity paths of every simulated scenario, giving a view of the full distribution around the liquidity-risk threshold.')
    cap = None if n.scenarios <= 1000 else 1000
    st.pyplot(all_simulation_paths_figure(sim['direct_liquidity'], sim['indirect_liquidity'], _risk_threshold, n.investment, cap))
    if cap is not None:
        st.caption(f'For readability, 1,000 evenly selected paths are shown from {n.scenarios:,} simulations. All simulations remain included in the risk metrics and policy calculations.\n'
               f'The liquidity-risk threshold is the {n.liquidity_risk_q/100:.1%} worst level of routing capacity in this run ({_risk_threshold:,.2f}); days below it are counted as liquidity-risk days.')

# =============================================================================
# PAGE 2 — EWI settings and evaluation
# =============================================================================
elif page == PAGE_EWI:
    n, e, p = configs(); sim, base, diag, em, ex, rnd, cm, cx, om, ox = compute(n, e, p, st.session_state.reps)
    st.header('2. EWI settings and evaluation')
    st.markdown('This page reports the baseline liquidity-risk metrics and the design of the imperfect early-warning indicator (EWI) used to trigger mitigation.')
    st.subheader('2.1 Baseline liquidity-risk evaluation metrics')
    total_available = float(np.sum(sim['direct_liquidity']))
    c = st.columns(3)
    c[0].metric('Baseline risk-scenario rate', f"{base['risk_scenario_rate']:.2f}%",
                help=f'The share of scenarios with at least one risk day. Baseline: no mitigation.')
    c[1].metric('Baseline risk-day rate', f"{base['risk_day_rate']:.2f}%",
                help=f'The share of all scenario-days that are risk days, i.e. liquidity below threshold. Baseline: no mitigation, so equal to set level of routing capacity risk threshold.')
    c[2].metric('Baseline relative shortfall', f"{base['total_shortfall'] / total_available * 100:.2f}%" if total_available > 0 else "N/A",
                help=f'Cumulative shortfall below the risk threshold, as a share of total routing liquidity available. Baseline: no mitigation.')
    st.caption(f"The threshold is the {n.liquidity_risk_q/100:.1%} worst level of routing capacity in this run; days below it are risk days. Metrics are based on network-adjusted direct routing capacity. Indirect capacity is a network diagnostic only.")
    st.divider()
    st.subheader('2.2 EWI settings and realized performance')
    st.warning('The EWI is a performance-controlled signal emulator. It imposes recall, precision and lead time; it does not re-estimate the empirical EWI model.')
    c = st.columns(4)
    c[0].metric('Target recall', f"{diag['target_recall_pct']:.2f}%")
    c[1].metric('Realized recall', f"{diag['realized_recall_pct']:.2f}%")
    c[2].metric('Target precision', f"{diag['target_precision_pct']:.2f}%")
    c[3].metric('Realized precision', f"{diag['realized_precision_pct']:.2f}%")
    st.divider()
   # ---- Figure 2.3: EWI target performance and realized signal quality, two fihures behind the comma----
    st.subheader('2.3 EWI target performance and realized signal quality ')
    target_recall = float(diag['target_recall_pct']) if diag.get('target_recall_pct') is not None else np.nan
    achieved_recall = round(float(diag['realized_recall_pct']), 2) 
    target_precision = float(diag['target_precision_pct']) if diag.get('target_precision_pct') is not None else np.nan
    achieved_precision = round(float(diag["realized_precision_pct"]), 2)
    evaluable_events = int(diag.get('evaluable_event_days', 0))
    true_positive_signals = int(diag.get('true_positive_signal_days', 0))
    false_positive_signals = int(diag.get('false_positive_signal_days', 0))
    missed_events = max(0, evaluable_events - true_positive_signals)
    total_signals = true_positive_signals + false_positive_signals
    # Shared column configuration so the first column is the same narrow width in every table.
    _col_cfg = {
        'Parameter': st.column_config.TextColumn('Parameter', width=50),
        'Value': st.column_config.NumberColumn('Value', width=50, format='%f'),
        'What it does': st.column_config.TextColumn('What it does', width='large'),
    }
    with st.expander('**EWI target performance and realized signal quality**', expanded=True):
        st.dataframe(pd.DataFrame({
            'Parameter': [
                'target recall', 'realized recall', 'target precision', 'realized precision',
                  'evaluable events', 'true positive signals', 'false positive signals', 'missed events', 'total signals'],
            'Value': [
                target_recall, achieved_recall, target_precision, achieved_precision,
                evaluable_events, true_positive_signals, false_positive_signals, missed_events, total_signals],
            'What it does': [
                'Target fraction of true risk days the EWI should catch.',
                'Realized fraction of true risk days the EWI actually caught. Higher = fewer misses, but more false alarms.',
                'Target fraction of detected risk days that are true positives.',
                'Realized fraction of detected risk days that are true positives. Higher = fewer false alarms, but more misses.',
                'Number of risk days that could be evaluated for EWI performance.',
                'Number of risk days correctly flagged by the EWI.',
                'Number of non-risk days incorrectly flagged by the EWI.',
                'Number of risk days that were not flagged by the EWI.',
                'Total number of days flagged by the EWI, both true and false positives.']}), hide_index=True, use_container_width=True, column_config=_col_cfg)

# =============================================================================
# PAGE 3 — Mitigation comparison
# =============================================================================
elif page == PAGE_POLICY:
    n, e, p = configs()
    sim, base, diag, em, ex, rnd, cm, cx, om, ox = compute(n, e, p, st.session_state.reps)
    st.header('3. Mitigation results')
    st.caption('Adjust the policy settings in the sidebar. The comparison uses the EWI settings retained from Tab 2 and updates for the selected support-start delay, number of support days, buffer release and central-bank injection.')
    st.caption(
        "Five strategies are compared: no intervention; randomized timing at "
        "the EWI rule's realized support volume; EWI-targeted support; a reactive "
        "countercyclical rule starting the selected delay after each realized "
        "risk day; and a perfect-information equal-volume oracle."
    )

    # Baseline for all relative figures: total routing liquidity available.
    total_available = float(np.sum(sim['direct_liquidity']))

    # Single source of truth: table + relative shortfall column.
    df = comparison_table(base, rnd, em, ex, total_available, cm, cx, om, ox)

    # ---- Headline relative result, stated in words. ----
    rnd_short  = _to_float_scalar(df.loc[1, 'Total routing-capacity shortfall'])
    ewi_short  = _to_float_scalar(df.loc[2, 'Total routing-capacity shortfall'])
    base_short = _to_float_scalar(df.loc[0, 'Total routing-capacity shortfall'])
    ewi_red = (base_short - ewi_short) / base_short * 100 if base_short > 0 else float('nan')
    rnd_red = (base_short - rnd_short) / base_short * 100 if base_short > 0 else float('nan')
    st.success(f"**At equal spend, EWI-triggered support reduced the routing-capacity shortfall by ~{ewi_red:.0f}% versus ~{rnd_red:.0f}% for randomized-timing support.** Targeting the same volume of liquidity where the network is fragile is what creates the difference.")

    # ---- Top-line liquidity figures — expressed relative to available routing liquidity. ----
    split = support_split(n.investment, p.buffer_release_pct, p.injection_pct, ex['support_active_days'])

    # Everything is scaled against total routing liquidity available (= 100% baseline).
    def _pct(x):
        return (x / total_available * 100) if total_available > 0 else float('nan')

    shortfall_pct = _pct(base['total_shortfall'])
    buffer_pct    = _pct(split['buffer_release_volume'])
    inject_pct    = _pct(split['injection_volume'])
    support_pct   = _pct(split['combined_support_volume'])

    c = st.columns(3)
    c[0].metric('Buffer release as % of available overall routing liquidity', f"{buffer_pct:.2f}%",
                help='Liquidity released via the dynamic buffer, as a share of available routing liquidity in all scenario\'s combined.')
    c[1].metric('Central-bank injection as % of available overall routing liquidity', f"{inject_pct:.2f}%",
                help='Backstop injection, as a share of available routing liquidity in all scenario\'s combined.')
    c[2].metric('Total support as % of available overall routing liquidity', f"{support_pct:.1f}%",
                help='Buffer release + injection combined, as a share of available routing liquidity in all scenario\'s combined.')

    st.caption('All figures are expressed relative to total routing liquidity available (the 100% baseline), '
               'so they are comparable across different investment amounts, scenario counts, and horizons.')

    # ---- Comparison figure and interpretation. ----
    st.pyplot(policy_comparison_figure(df, total_available=total_available))
    st.markdown('**Interpretation.** Panel A reports scenarios with at least one risk day. '
                'Panel B reports the share of all scenario-days that are risk days. '
                'Panel C reports relative routing-capacity shortfall **as a share of total routing liquidity available (%)**. '
                'Lower is better in all panels.')
    with st.expander('Show comparison table'):
        st.dataframe(df, hide_index=True, use_container_width=True)

# =============================================================================
# PAGE 4 — Definitions
# =============================================================================
elif page == PAGE_DEFINITIONS:
    st.header('4. Model definitions'); df = glossary_dataframe(); q = st.text_input('Search definitions')
    if q:
        df = df[df.astype(str).apply(lambda x: x.str.contains(q, case=False, na=False)).any(axis=1)]
    for r in df.to_dict('records'):
        with st.expander(r['Term']):
            st.write(r['Definition']); st.code(r['Formula / implementation'], language=None)

# =============================================================================
# PAGE 5 — Downloads
# =============================================================================
else:
    n, e, p = configs()
    sim, base, diag, em, ex, rnd, cm, cx, om, ox = compute(n, e, p, st.session_state.reps)
    st.header('5. Downloads')

    # Use the same relative-shortfall table as the Mitigation page so the exported
    # figure/table match what is shown on screen.
    total_available = float(np.sum(sim['direct_liquidity']))
    df = comparison_table(base, rnd, em, ex, total_available, cm, cx, om, ox)

    # Ensure risk_threshold is a float (sim may contain an ndarray)
    try:
        threshold = float(np.asarray(sim['risk_threshold']).item())
    except Exception:
        threshold = float(sim['risk_threshold'])

    f1 = routing_paths_figure(sim['direct_liquidity'], sim['indirect_liquidity'], threshold, 0, n.investment)
    f2 = all_simulation_paths_figure(sim['direct_liquidity'], sim['indirect_liquidity'], threshold, n.investment,
                                     None if n.scenarios <= 1000 else 1000)
    f3 = policy_comparison_figure(df, total_available=total_available)
    f4 = multiplier_distribution_figure(sim['gamma'], sim['direct_lm'], sim['indirect_lm'], s.q)
    figs = {'01_selected_scenario.png': f1, '02_all_simulations.png': f2,
            '03_mitigation_comparison.png': f3, '04_network_state_distributions.png': f4}

    settings = pd.DataFrame({
        'Setting': list(n.__dict__) + list(e.__dict__) + list(p.__dict__) + ['combined_support_pct', 'benchmark_replications'],
        'Value': list(n.__dict__.values()) + list(e.__dict__.values()) + list(p.__dict__.values()) + [p.combined_support_pct, st.session_state.reps],
    })
    sheets = {'Settings': settings, 'Baseline': pd.DataFrame([base]), 'EWI diagnostics': pd.DataFrame([diag]),
              'Mitigation comparison': df, 'EWI outcome': pd.DataFrame([{**em, **ex}]),
              'Countercyclical outcome': pd.DataFrame([{**cm, **cx}]),
              'Oracle outcome': pd.DataFrame([{**om, **ox}]),
              'Randomized timing replications': rnd, 'Definitions': glossary_dataframe()}

    a, b = st.columns(2)
    a.download_button('Download all PNG figures', png_zip_bytes(figs), 'network_routing_figures_png.zip', 'application/zip', use_container_width=True)
    a.download_button('Download comparison PNG', figure_to_png_bytes(f3), 'mitigation_comparison.png', 'image/png', use_container_width=True)
    b.download_button('Download Excel results', tables_to_excel_bytes(sheets), 'network_routing_results.xlsx',
                      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
    b.download_button('Download comparison CSV', df.to_csv(index=False).encode(), 'mitigation_comparison.csv', 'text/csv', use_container_width=True)