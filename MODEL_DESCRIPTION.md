# Model Description

## Network Routing Liquidity Engine

This document describes the model as implemented in the source code. It covers
the research objective, notation, stochastic topology process, liquidity
multipliers, risk definition, early-warning indicator, policy strategies,
comparison logic, reported metrics, and execution sequence.

The repository README intentionally provides a non-technical overview. Formal
notation and equations are maintained here so that the public landing page
remains concise while the model specification remains explicit and auditable.

## 1. Objective and interpretation

The engine operationalizes the network-based view of systemic liquidity risk
developed in the thesis *Network behavior and liquidity crises*. It separates:

- **balance-sheet capacity**, the liquidity institutions can supply; and
- **routing capacity**, the ability of the network to move that liquidity
  through direct and indirect intermediation links.

The engine isolates the routing component. It is a controlled policy laboratory,
not a crisis-forecasting model. It evaluates how network topology, imperfect
warning information, intervention timing, buffer release, and central-bank
liquidity injections affect simulated routing-capacity shortfalls.

## 2. Notation

| Symbol | Meaning |
|---|---|
| $s$ | Scenario index. |
| $t$ | Trading-day index. |
| $N$ | Number of admissible network nodes or financial counterparties. |
| $I$ | Investment-base liquidity. |
| $b$ | Normal liquidity buffer, expressed as a percentage. |
| $\gamma_{s,t}$ | Positive tail exponent governing the degree distribution. |
| $x_{s,t}$ | Log tail exponent, $x_{s,t}=\log(\gamma_{s,t})$. |
| $\mu_\gamma$ | Requested stationary arithmetic mean of $\gamma$. |
| $\sigma_\gamma$ | Requested stationary standard deviation of $\gamma$. |
| $\mu_x$ | Stationary mean of log-$\gamma$. |
| $\sigma_x$ | Stationary standard deviation of log-$\gamma$. |
| $\phi$ | Daily AR(1) persistence coefficient. |
| $h$ | Mean-reversion half-life in trading days. |
| $LM_{s,t}$ | Direct routing multiplier. |
| $ILM_{s,t}$ | Indirect routing multiplier. |
| $L^{D}_{s,t}$ | Direct routing capacity. |
| $L^{I}_{s,t}$ | Indirect routing capacity. |
| $\tau$ | Liquidity-risk threshold. |
| $u_{s,t}$ | Indicator that policy support is active. |

## 3. Configuration

### 3.1 Simulation settings

| Setting | Code field | Default | Interpretation |
|---|---|---:|---|
| Network size | `n_nodes` | 24 | Number of admissible nodes or degree values. |
| Monte Carlo scenarios | `scenarios` | 1,000 | Number of independent simulated paths. |
| Trading days | `trading_days` | 200 | Number of daily observations per path. |
| Investment base | `investment` | 100.0 | Reference liquidity amount per scenario-day. |
| Normal buffer | `buffer_normal_pct` | 40.0 | Percentage of the investment base unavailable for normal routing. |
| Risk quantile | `liquidity_risk_q` | 5.0 | Lower-tail percentile used to define the risk threshold. |
| Random seed | `seed` | 42 | Seed controlling reproducible simulation draws. |
| Gamma mean | `mu` | 1.15732 | Requested stationary arithmetic mean of $\gamma$. |
| Gamma standard deviation | `sigma` | 0.53811 | Requested stationary standard deviation of $\gamma$. |
| Memory half-life | `halftime` | 10 | Assumed half-life of a log-$\gamma$ deviation, in trading days. |

### 3.2 EWI settings

| Setting | Code field | Default | Interpretation |
|---|---|---:|---|
| Target recall | `target_recall` | 0.70 | Intended share of evaluable risk events receiving a correct advance signal. |
| Target precision | `target_precision` | 0.25 | Intended share of signal days associated with a true event. |
| Lead time | `lead_time` | 5 | Number of days between a signal and its associated event. |
| Random seed | `seed` | 42 | Seed controlling reproducible signal placement. |

### 3.3 Policy settings

| Setting | Code field | Default | Interpretation |
|---|---|---:|---|
| Buffer release | `buffer_release_pct` | 5.0 | Self-funded liquidity released on an active support day. |
| Central-bank injection | `injection_pct` | 5.0 | External liquidity added on an active support day. |
| Combined support | `combined_support_pct` | 10.0 | Sum of buffer release and injection. |
| Support duration | `support_days` | 10 | Number of days an activation remains active. |
| Start delay | `start_delay` | 5 | Delay between a trigger and the start of support. |

## 4. Stochastic log-gamma process

The user specifies the desired long-run arithmetic mean and standard deviation
of the tail exponent on the original gamma scale. Because $\gamma$ must remain
strictly positive, the engine simulates its logarithm:

$$
x_{s,t}=\log(\gamma_{s,t}).
$$

Assuming a stationary lognormal distribution, the gamma-scale inputs are
converted to log-space parameters as follows:

$$
\sigma_x^2
=
\log\left(1+\frac{\sigma_\gamma^2}{\mu_\gamma^2}\right),
$$

$$
\mu_x
=
\log(\mu_\gamma)-\frac{1}{2}\sigma_x^2.
$$

The daily persistence coefficient follows from the configured half-life:

$$
\phi = 2^{-1/h}
     = \exp\left(-\frac{\log 2}{h}\right),
\qquad h>0.
$$

For a no-memory specification, the implementation sets $\phi=0$. The
innovation standard deviation is scaled to preserve the requested stationary
variance of log-$\gamma$:

$$
\sigma_\eta = \sigma_x\sqrt{1-\phi^2}.
$$

The stationary AR(1) process is:

$$
x_{s,t}
=
\mu_x
+
\phi\left(x_{s,t-1}-\mu_x\right)
+
\sigma_\eta\varepsilon_{s,t},
\qquad
\varepsilon_{s,t}\sim\mathcal{N}(0,1).
$$

The simulated state is transformed back to the original scale:

$$
\gamma_{s,t}=\exp(x_{s,t})>0.
$$

The configured half-life is a structural simulation input. A half-life
estimated from one realized finite path is a diagnostic and will generally not
be identical to the configured value.

## 5. Network topology and routing multipliers

For each admissible degree $k\in\{1,\ldots,N-1\}$, the model assigns a
power-law weight:

$$
w_k(\gamma)=k^{-\gamma}.
$$

The normalized degree probability is:

$$
p_k(\gamma)
=
\frac{k^{-\gamma}}
{\sum_{j=1}^{N-1}j^{-\gamma}}.
$$

The direct routing multiplier is the expected degree:

$$
LM(\gamma)
=
\mathbb{E}[k]
=
\sum_{k=1}^{N-1}k\,p_k(\gamma).
$$

The indirect routing multiplier is:

$$
ILM(\gamma)
=
\frac{\mathbb{E}[k^2]}{\mathbb{E}[k]}-1,
$$

where

$$
\mathbb{E}[k^2]
=
\sum_{k=1}^{N-1}k^2p_k(\gamma).
$$

`make_multiplier_grids` precomputes the direct and indirect multiplier curves.
Daily gamma observations are mapped to these grids by interpolation. Values are
clipped only to the supported interpolation range, and the simulation reports
boundary use so that interpolation effects remain visible.

## 6. Baseline routing capacity and risk events

Baseline liquidity available for routing is:

$$
A = I\left(1-\frac{b}{100}\right).
$$

Direct routing capacity is:

$$
L^{D}_{s,t}=A\,LM_{s,t}.
$$

Indirect routing capacity is:

$$
L^{I}_{s,t}=A\,ILM_{s,t}.
$$

The liquidity-risk threshold is the configured lower percentile of the pooled
baseline direct-capacity distribution:

$$
\tau
=
Q_q\left(\left\{L^{D}_{s,t}\right\}_{s,t}\right),
$$

where $Q_q$ denotes the percentile associated with
`liquidity_risk_q`. A scenario-day is classified as a risk day when:

$$
L^{D}_{s,t}<\tau.
$$

Direct routing capacity defines risk events. Indirect routing capacity is
reported as a network diagnostic and does not determine the event mask.

## 7. Reported risk metrics

Let

$$
R_{s,t}=\mathbf{1}\left\{L^{D}_{s,t}<\tau\right\}.
$$

For $S$ scenarios and $T$ trading days, the risk-day rate is:

$$
100\times\frac{1}{ST}
\sum_{s=1}^{S}\sum_{t=1}^{T}R_{s,t}.
$$

The risk-scenario rate is:

$$
100\times\frac{1}{S}
\sum_{s=1}^{S}
\mathbf{1}\left\{\sum_{t=1}^{T}R_{s,t}>0\right\}.
$$

Total routing-capacity shortfall is:

$$
\sum_{s=1}^{S}\sum_{t=1}^{T}
\max\left(\tau-L^{D}_{s,t},0\right).
$$

Relative shortfall divides total shortfall by total baseline direct routing
capacity. Calculations retain full numerical precision; presentation layers may
round values for readability.

## 8. Early-warning indicator

The EWI is a performance-controlled signal emulator rather than a fitted
forecasting model. It is configured through target recall, target precision,
lead time, and a random seed.

For events that can be evaluated at the configured lead time:

$$
\text{Recall}
=
\frac{\text{correctly signalled evaluable events}}
{\text{all evaluable events}}.
$$

$$
\text{Precision}
=
\frac{\text{true-positive signal days}}
{\text{all signal days}}.
$$

True-positive signals are positioned at the specified lead before selected
events. False-positive signals are placed on eligible non-event dates to
approach the target precision. Integer event and signal counts can cause
realized performance to differ from the targets, particularly for small numbers
of scenarios. The application therefore reports target and realized values
separately.

## 9. Liquidity support

Support has two additive components:

$$
c = r + j,
$$

where $r$ is the buffer-release percentage and $j$ is the central-bank
injection percentage. Let $u_{s,t}$ equal one when support is active and zero
otherwise. Available liquidity under a policy becomes:

$$
A^{P}_{s,t}
=
I\left(1-\frac{b}{100}+u_{s,t}\frac{c}{100}\right).
$$

Policy-adjusted direct routing capacity is:

$$
L^{D,P}_{s,t}=A^{P}_{s,t}LM_{s,t}.
$$

Support is added before network scaling. Consequently, the same network state
scales both baseline liquidity and policy support.

## 10. Policy strategies

The engine compares five strategies.

### 10.1 No intervention

The baseline uses no active support days and provides the reference outcomes.

### 10.2 Reactive countercyclical intervention

A realized risk day triggers support after the configured start delay. Support
then remains active for the configured duration. Because this rule is driven by
realized events, its total support volume may differ from the EWI strategy.

### 10.3 EWI-targeted intervention

An imperfect advance signal triggers support after the configured start delay.
The rule tests whether warning-based timing improves outcomes relative to
untargeted timing.

### 10.4 Randomized timing

The randomized benchmark preserves the EWI strategy's realized number of active
support days and combined support level, but reallocates those active days to
random dates. The reported benchmark outcome is the median across randomized
replications. This isolates the value of timing and targeting from the amount
of support supplied.

### 10.5 Perfect-information oracle

The oracle assigns the EWI strategy's active-day budget ex post to the weakest
baseline direct-capacity observations. It is an infeasible upper benchmark and
must not be interpreted as an implementable policy.

## 11. Policy comparison and `comparison.py`

`src/comparison.py` is a presentation and normalization layer. It does not
simulate network paths, generate EWI signals, or apply policy support. Those
calculations occur earlier in the pipeline.

### 11.1 Inputs

Each deterministic policy is produced by `run_policy`, which returns its main
risk metrics and supplementary policy outputs separately. Before comparison,
these dictionaries are merged so that one strategy object contains both the
outcome measures and the realized support information:

```python
countercyclical_result = {
    **countercyclical_metrics,
    **countercyclical_outputs,
}

ewi_result = {
    **ewi_metrics,
    **ewi_outputs,
}

oracle_result = {
    **oracle_metrics,
    **oracle_outputs,
}
```

The objects passed to `build_policy_comparison` are:

- the baseline metric dictionary;
- the merged countercyclical result;
- the merged EWI-targeted result;
- the randomized-replication DataFrame; and
- the merged oracle result.

```python
comparison = build_policy_comparison(
    baseline=baseline_metrics,
    countercyclical=countercyclical_result,
    ewi=ewi_result,
    randomized=randomized_replications,
    oracle=oracle_result,
)
```

EWI signal diagnostics such as recall and precision must not be passed as the
EWI policy result. The comparison requires policy outcomes, including the
risk-scenario rate, risk-day rate, and total shortfall.

### 11.2 Deterministic strategies

For the baseline, countercyclical, EWI-targeted, and oracle strategies, the
comparison layer creates one normalized row per strategy. It verifies that the
required policy metrics are present and places the outputs in a common column
schema.

### 11.3 Randomized benchmark

The randomized input remains a DataFrame because it contains multiple benchmark
replications. The comparison layer summarizes those replications using their
median outcome. This produces one randomized-benchmark row while preserving the
interpretation of randomized timing as a distribution rather than a single
arbitrary draw.

### 11.4 Output interpretation

The resulting table contains one row for each of the five strategies. Its main
columns report:

- risk-scenario rate;
- risk-day rate;
- total routing-capacity shortfall; and
- total support volume.

The application may append relative shortfall as a percentage of total baseline
routing capacity. Lower values are preferable for all risk and shortfall
measures. Support volume is not an outcome to minimize mechanically; it is
reported so that differences in intervention intensity remain explicit.

The comparison figure visualizes the strategy rows using the same table as its
source. Exports should therefore be built from that table to keep displayed and
downloaded results consistent.

## 12. Execution sequence

The application follows this order:

1. `simulate_base_paths` generates log-$\gamma$, $\gamma$, routing multipliers,
   baseline capacity, the threshold, and the event mask.
2. `evaluate_liquidity` calculates baseline risk and shortfall metrics.
3. `create_ewi` creates the warning mask and signal diagnostics.
4. Policy-mask functions create EWI, reactive countercyclical, and oracle
   activation schedules.
5. `run_policy` evaluates each deterministic intervention.
6. `run_random_benchmarks` evaluates randomized timing across replications.
7. Deterministic metric and output dictionaries are merged.
8. `build_policy_comparison` creates the normalized five-strategy table.
9. Plotting and export helpers use the comparison table to generate figures and
   downloadable results.

## 13. Module map

| Module | Responsibility |
|---|---|
| `src/topology.py` | Degree distribution, moments, and multiplier grids. |
| `src/simulation.py` | Log-$\gamma$ process, routing paths, threshold, and event mask. |
| `src/metrics.py` | Risk rates and shortfall measures. |
| `src/ewi.py` | Performance-controlled EWI emulator and diagnostics. |
| `src/policy.py` | Activation masks, policy application, support channels, randomized benchmark, and oracle. |
| `src/comparison.py` | Result validation, five-strategy normalization, comparison figure, and export helpers. |
| `src/plotting.py` | Network-state and routing-capacity figures. |
| `src/definitions.py` | Application glossary. |
| `app.py` | Streamlit interface, cached pipeline, diagnostics, figures, and downloads. |
| `examples/test_s1_default.py` | Integrated S = 1 execution check and auditable CSV export. |

## 14. Scope and limitations

The engine is a reduced-form policy laboratory for network-routing effects. It
does not reconstruct an observed institution-level counterparty graph or model
strategic behavior, balance-sheet adjustment, market prices, margins,
collateral calls, or crisis probabilities. The EWI is a controlled emulator,
the half-life is a scenario assumption, and the oracle is an infeasible upper
benchmark. Results should be interpreted comparatively and conditional on the
selected assumptions.
