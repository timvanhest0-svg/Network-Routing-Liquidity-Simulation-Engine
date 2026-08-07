# Model Description

## Network Routing Liquidity Risk Simulation Engine

This note documents the model as implemented in the source code. It covers the objective, notation, stochastic network-topology process, liquidity multipliers, early-warning indicator (EWI), five policy timing strategies, reported metrics, and module structure.

## 1. Objective

The engine operationalizes the network-based view of systemic liquidity risk developed in the thesis *Network behavior and liquidity crises*. It distinguishes:

- **Balance-sheet capacity:** the liquidity that institutions can supply.
- **Routing capacity:** the capacity of the network topology to move that liquidity through direct and indirect intermediation links.

The engine isolates the routing side and acts as a controlled policy laboratory. It does not forecast a specific crisis. It evaluates how network topology, imperfect warning information, intervention timing, buffer release, and central-bank injections affect simulated routing-capacity shortfalls.

## 2. Main configuration

### Simulation parameters

| Name | Code field | Default | Meaning |
|---|---|---:|---|
| Network size | `n_nodes` | 24 | Number of intermediary nodes or degree bins. |
| Monte Carlo paths | `scenarios` | 1,000 | Number of simulated paths. |
| Trading days | `trading_days` | 200 | Number of daily steps per path. |
| Investment base | `investment` | 100.0 | Reference liquidity amount per period. |
| Normal buffer | `buffer_normal_pct` | 40.0 | Share of investment withheld from normal routing. |
| Risk quantile | `liquidity_risk_q` | 5 | Lower-tail threshold in percentage points. |
| Seed | `seed` | 42 | Master random seed. |
| Gamma mean | `mu` | 1.15732 | Desired stationary arithmetic mean of gamma. |
| Gamma standard deviation | `sigma` | 0.53811 | Desired stationary standard deviation of gamma. |
| Memory half-life | `halftime` | 10 | Assumed topology-shock half-life in trading days. |

### EWI parameters

| Name | Code field | Default | Meaning |
|---|---|---:|---|
| Target recall | `target_recall` | 0.70 | Intended share of evaluable event days receiving a correct signal. |
| Target precision | `target_precision` | 0.25 | Intended share of signal days that are true positives. |
| Lead time | `lead_time` | 5 | Days between a signal and its predicted event. |
| Seed | `seed` | 42 | Seed for reproducible signal placement. |

### Policy parameters

| Name | Code field | Default | Meaning |
|---|---|---:|---|
| Buffer release | `buffer_release_pct` | 5.0 | Self-funded liquidity released on an active support day. |
| Central-bank injection | `injection_pct` | 5.0 | External liquidity added on an active support day. |
| Combined support | `combined_support_pct` | 10.0 | Sum of buffer release and injection. |
| Support duration | `support_days` | 10 | Number of days each activation remains active. |
| Start delay | `start_delay` | 5 | Delay between trigger and support activation. |

## 3. Stochastic network-topology process

The application asks the user for the arithmetic mean and standard deviation of the tail exponent on the original gamma scale. The engine simulates the logarithm of gamma:

\[
x_t = \log(\gamma_t).
\]

The gamma-scale inputs are converted to stationary lognormal parameters:

\[
\sigma_x^2 = \log\left(1 + \frac{\sigma_\gamma^2}{\mu_\gamma^2}\right),
\]

\[
\mu_x = \log(\mu_\gamma) - \frac{1}{2}\sigma_x^2.
\]

This conversion ensures that, before multiplier-grid clipping, the transformed process has the requested long-run arithmetic mean and standard deviation on the gamma scale.

Log-gamma follows the mean-reverting process:

\[
x_t = \mu_x + \rho(x_{t-1}-\mu_x) + \sigma_{\eta,x}\varepsilon_t,
\qquad \varepsilon_t \sim N(0,1).
\]

The memory coefficient is determined by the assumed half-life `halftime`:

\[
\rho = 0.5^{1/\text{halftime}}.
\]

For the no-memory case, `halftime = 0` and \(\rho=0\). The innovation volatility is:

\[
\sigma_{\eta,x} = \sigma_x\sqrt{1-\rho^2}.
\]

This preserves the same stationary distribution under each memory scenario. The engine transforms the state back to the original scale using:

\[
\gamma_t = \exp(x_t).
\]

The exponential transformation guarantees a strictly positive tail exponent without imposing an artificial mass at zero.

## 4. Network topology and liquidity multipliers

Implemented in `topology.py`, the tail exponent determines a power-law degree distribution over the admissible degree values. The engine derives:

- **Direct liquidity multiplier:** expected degree, \(E[k]\).
- **Indirect liquidity multiplier:** \(E[k^2]/E[k]-1\), retained as a network diagnostic.

`make_multiplier_grids` precomputes the direct and indirect multiplier curves. Daily gamma values are clipped only for interpolation safety and mapped to the multiplier grids by linear interpolation. The simulation reports the share of gamma draws outside the grid so boundary effects remain visible.

## 5. Baseline liquidity and risk events

Available baseline liquidity is:

\[
A = I\left(1-\frac{b}{100}\right),
\]

where \(I\) is the investment base and \(b\) the normal buffer percentage.

Direct and indirect routing capacity are:

\[
L^{D}_{s,t}=A\times LM^{D}_{s,t},
\]

\[
L^{I}_{s,t}=A\times LM^{I}_{s,t}.
\]

The liquidity-risk threshold is the configured lower percentile of the complete baseline direct-capacity distribution. A risk day is a scenario-day for which direct routing capacity falls strictly below that threshold.

## 6. Risk metrics

Implemented in `metrics.py`, the headline metrics are calculated on direct routing capacity:

- **Risk-day rate:** percentage of all scenario-days below the threshold.
- **Risk-scenario rate:** percentage of paths containing at least one risk day.
- **Total routing-capacity shortfall:** cumulative distance below the threshold.
- **Relative shortfall:** total shortfall divided by total baseline routing liquidity available.

Indirect routing capacity is diagnostic and does not define risk events.

## 7. Early-warning indicator

Implemented in `ewi.py`, the EWI is a performance-controlled signal emulator, not a fitted forecasting model. It imposes target recall, target precision, and an exact lead time.

- **Recall:** correctly signalled evaluable event days divided by all evaluable event days.
- **Precision:** true-positive signal days divided by all signal days.
- **True-positive signals:** placed exactly `lead_time` days before selected event days.
- **False-positive signals:** added on eligible dates to approach target precision.

Integer event and signal counts can cause realized recall and precision to differ slightly from their targets, particularly when the number of paths is small. The Streamlit diagnostics report target and achieved values as well as signal counts.

## 8. Liquidity-support policies

Support is delivered through two additive channels:

1. a buffer release; and
2. a central-bank liquidity injection.

On an active day, combined support is added to the available liquidity base before the direct multiplier is applied. The same network state therefore scales baseline liquidity and policy support.

The engine compares five strategies:

1. **Baseline: no intervention.**
2. **Reactive countercyclical intervention.** Support starts after a realized risk day and remains active for the configured duration. Delay of response follows delay days after event day.
3. **EWI-targeted intervention.** Support is triggered by the imperfect advance-warning signal. Delay of response follows delay days after event (imperfect) signal day.
4. **Randomized timing, equal volume.** The EWI strategy's realized support-day budget is assigned to random dates. Reported outcomes are medians across benchmark replications.
5. **Perfect-information oracle, equal volume.** The EWI support-day budget is allocated ex post to the weakest baseline routing-capacity observations. The oracle is an infeasible upper benchmark, not an implementable policy.

Randomized timing and the oracle are equal-volume timing controls. The reactive countercyclical strategy is event-driven and may use a different realized support volume. Total support volume is therefore reported for every strategy.

## 9. Policy comparison

`build_policy_comparison` in `comparison.py` receives one combined result dictionary for each deterministic strategy:

```python
countercyclical_result = {**countercyclical_metrics, **countercyclical_outputs}
ewi_result = {**ewi_metrics, **ewi_outputs}
oracle_result = {**oracle_metrics, **oracle_outputs}
```

The comparison call is:

```python
df = build_policy_comparison(
    baseline=baseline_metrics,
    countercyclical=countercyclical_result,
    ewi=ewi_result,
    randomized=randomized_replications,
    oracle=oracle_result,
)
```

The table and figure report risk-scenario rate, risk-day rate, total routing-capacity shortfall, relative shortfall, and realized support volume. Display tables may round values to two decimal places, while calculations retain full numerical precision.

## 10. Execution order

The Streamlit application follows this sequence:

1. `simulate_base_paths`: simulation engine
2. `evaluate_liquidity` : calculate LMs
3. `create_ewi` create EWI, countercyclical, randomized, and oracle activation masks
4. `run_policy` and `run_random_benchmarks` for each deterministic intervention merge deterministic metrics and outputs
5. `build_policy_comparison`render comparison figures and downloads

## 11. Module map

| Module | Role |
|---|---|
| `topology.py` | Degree distribution, moments, multiplier grids. |
| `simulation.py` | Log-gamma process, routing-capacity paths, threshold, event mask. |
| `metrics.py` | Risk metrics, shortfalls, policy effects. |
| `ewi.py` | Performance-controlled EWI emulator and diagnostics. |
| `policy.py` | Activation masks, policy application, support channels, randomized and oracle benchmarks. |
| `comparison.py` | Five-strategy table, comparison figure, export helpers. |
| `plotting.py` | Individual and ensemble routing-path figures. |
| `definitions.py` | Glossary and definitions. |
| `app.py` | Streamlit interface, cached pipeline, diagnostics, figures, and downloads. |

## 12. Scope and limitations

The engine is a reduced-form policy laboratory for network-routing effects. It does not estimate an institution-level graph, behavioral responses, strategic balance-sheet adjustment, market prices, margins, collateral calls, or a crisis probability model. The EWI is an emulator and the oracle is an infeasible ceiling. Results should be interpreted comparatively and conditional on the selected model assumptions.
