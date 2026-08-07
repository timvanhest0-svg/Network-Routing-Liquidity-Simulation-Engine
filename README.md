# Network Routing Liquidity Risk Simulation Engine

> A modular Streamlit research application for mean-reverting network topology, network-adjusted routing capacity, performance-controlled early-warning signals, and five-strategy liquidity-support comparison.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-ff4b4b)
![License](https://img.shields.io/badge/license-Apache--2.0-green)
![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)
![Status](https://img.shields.io/badge/status-research--prototype-orange)

## Objective

A financial system is not resilient merely because liquidity exists somewhere in the system. Liquidity must also be capable of reaching the institutions and markets where pressure is concentrated.

The engine is a controlled policy laboratory based on the network view developed in the thesis *Network behavior and liquidity crises*. It separates:

- **Balance-sheet capacity:** how much liquidity institutions can supply.
- **Routing capacity:** how effectively the network can move liquidity through intermediation links.

The engine isolates the routing side. It does not forecast a specific crisis. It evaluates how network topology, warning quality, intervention timing, buffer release, and central-bank support affect simulated liquidity shortfalls.

## Key features

- **Positive mean-reverting tail exponent:** the engine simulates \(x_t=\log(\gamma_t)\) and transforms back with \(\gamma_t=\exp(x_t)\).
- **Intuitive gamma inputs:** users enter the desired arithmetic mean, standard deviation, and memory half-life on the original gamma scale. The engine converts them internally to log-gamma parameters.
- **Network-adjusted routing capacity:** daily gamma values determine direct and indirect liquidity multipliers through a power-law degree distribution.
- **Performance-controlled EWI:** recall, precision, and lead time are explicit scenario inputs. Target and achieved performance are reported separately.
- **Two support channels:** dynamic buffer release and central-bank injection enter as additive liquidity support.
- **Five policy strategies:** no intervention, reactive countercyclical support, EWI-targeted support, randomized equal-volume timing, and a perfect-information equal-volume oracle.
- **Reproducible simulation:** fixed seeds control topology paths, warning placement, and randomized benchmarks.
- **Exportable results:** figures and multi-sheet Excel outputs can be downloaded from the application.

## Main pages

0. **Overview**: model purpose, thesis link, and interpretation.
1. **Network simulation and routing paths**: topology settings, multiplier relationship, and simulated paths.
2. **Risk metrics and EWI design**: baseline risk metrics, EWI controls, target-versus-achieved diagnostics, and signal counts.
3. **Mitigation comparison**: five-strategy policy table and comparison figure.
4. **Definitions**: model glossary.
5. **Downloads**: figures, settings, diagnostics, and result tables.

## Model summary

### 1. Log-gamma topology process

The engine asks users for gamma-scale inputs:

- `mu`: desired stationary arithmetic mean of gamma;
- `sigma`: desired stationary standard deviation of gamma;
- `halftime`: assumed half-life of a topology shock in trading days.

These are converted to log-gamma parameters:

\[
\sigma_x^2=\log\left(1+\frac{\sigma_\gamma^2}{\mu_\gamma^2}\right),
\qquad
\mu_x=\log(\mu_\gamma)-\frac{1}{2}\sigma_x^2.
\]

Log-gamma follows:

\[
x_t=\mu_x+\rho(x_{t-1}-\mu_x)+\sigma_{\eta,x}\varepsilon_t,
\qquad \varepsilon_t\sim N(0,1),
\]

with:

\[
\rho=0.5^{1/\text{halftime}},
\qquad
\sigma_{\eta,x}=\sigma_x\sqrt{1-\rho^2}.
\]

The simulated tail exponent is:

\[
\gamma_t=\exp(x_t)>0.
\]

### 2. Routing capacity

The tail exponent shapes a power-law degree distribution. The engine maps gamma to:

- direct multiplier: \(E[k]\);
- indirect multiplier: \(E[k^2]/E[k]-1\).

Direct routing capacity equals available base liquidity multiplied by the direct multiplier. The indirect multiplier is retained as a network diagnostic.

### 3. Risk events

The liquidity-risk threshold is a lower percentile of baseline direct routing capacity. A risk day is a scenario-day below that threshold. The headline metrics are:

- risk-day rate;
- risk-scenario rate;
- total routing-capacity shortfall;
- routing-capacity shortfall as a percentage of total available routing liquidity.

### 4. EWI emulator

The EWI is not fitted inside the engine. It is a performance-controlled signal emulator defined by:

- target recall;
- target precision;
- lead time;
- random seed.

The app reports target and achieved recall and precision, evaluable event days, signal days, true positives, and false positives.

### 5. Policy strategies

The mitigation comparison contains five outcomes:

1. **Baseline: no intervention**
2. **Reactive countercyclical intervention**
3. **EWI-targeted intervention**
4. **Randomized timing, equal volume**
5. **Perfect-information oracle, equal volume**

Randomized timing and the oracle use the EWI support-day budget. The reactive countercyclical rule is event-driven and can use a different realized volume. The comparison table therefore reports total support volume for every policy.

See [`MODEL_DESCRIPTION.md`](MODEL_DESCRIPTION.md) for full equations, parameter definitions, policy logic, and the module map.

## Installation

```bash
python -m venv .venv
```

Activate the environment:

```bash
# Windows
.venv\Scripts\activate

# macOS or Linux
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Python 3.10 or later is recommended.

## Quick start

From the repository root:

```bash
streamlit run app.py
```

## Tests

Run the complete test suite:

```bash
pytest -q
```

Run the single-scenario smoke test from the repository root:

```bash
python -m examples.test_s1_default
```

The S=1 example checks that the modules execute end-to-end with the smallest supported scenario dimension. It is a software integration test, not a statistically stable policy estimate.

## Comparison-module usage

Merge the deterministic policy metrics and output dictionaries before building the comparison:

```python
countercyclical_result = {**countercyclical_metrics, **countercyclical_outputs}
ewi_result = {**ewi_metrics, **ewi_outputs}
oracle_result = {**oracle_metrics, **oracle_outputs}

comparison = build_policy_comparison(
    baseline=baseline_metrics,
    countercyclical=countercyclical_result,
    ewi=ewi_result,
    randomized=randomized_replications,
    oracle=oracle_result,
)
```

The randomized input remains a DataFrame because the comparison reports medians across benchmark replications.

## Repository contents

| Path | Description |
|---|---|
| `app.py` | Streamlit entry point and cached model pipeline. |
| `src/simulation.py` | Log-gamma topology process and baseline routing paths. |
| `src/topology.py` | Degree distribution, moments, and multiplier grids. |
| `src/metrics.py` | Liquidity-risk metrics and shortfall measures. |
| `src/ewi.py` | Performance-controlled EWI emulator. |
| `src/policy.py` | Support masks, policy application, randomized benchmark, and oracle. |
| `src/comparison.py` | Five-strategy table, chart, and export helpers. |
| `src/plotting.py` | Routing-path figures. |
| `src/definitions.py` | Glossary. |
| `examples/` | S=1 smoke test and supporting documentation. |
| `tests/` | Automated tests. |
| `MODEL_DESCRIPTION.md` | Full model logic and equations. |
| `requirements.txt` | Python dependencies. |
| `CITATION.cff` | Citation metadata. |
| `LICENSE` | Apache-2.0 license. |

## Scope and limitations

The model isolates network-driven routing-capacity effects. It does not estimate an institution-level graph or model strategic behavior, balance-sheet adjustment, prices, margins, collateral calls, or crisis probabilities. The EWI is an emulator, the memory half-life is a scenario assumption, and the oracle is an infeasible upper benchmark. Results should be interpreted comparatively and conditional on the selected assumptions.

## Reproducibility

- All stochastic components use explicit seeds.
- The model configuration is held in dataclasses.
- Dependencies are recorded in `requirements.txt`.
- The S=1 smoke test exercises the full pipeline.
- Figures and tables can be exported from the application.

## Citation

Use the metadata in [`CITATION.cff`](CITATION.cff).

## License

Apache License 2.0. See [`LICENSE`](LICENSE).

## Contributing

Issues and pull requests are welcome. Run the smoke test and `pytest -q` before submitting changes.
