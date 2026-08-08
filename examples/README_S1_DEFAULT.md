# S = 1 pipeline smoke test

This example is a small **integration smoke test** of the routing-liquidity
engine using one Monte Carlo scenario (`S = 1`). It verifies that the smallest
supported scenario dimension can pass through the main computational pipeline
without runtime, shape, indexing, broadcasting, or missing-field errors.

The test covers the baseline simulation, liquidity-risk evaluation, synthetic
early-warning indicator (EWI), EWI-targeted intervention, reactive
countercyclical intervention, randomized-timing benchmark, equal-volume oracle,
and five-strategy comparison table.

> **Scope:** this is an execution and integration check. It does not validate
> economic calibration, statistical inference, Monte Carlo convergence, or the
> stability of estimated policy effects.

## Repository location

The example script is expected at:

```text
examples/test_s1_default.py
```

Run all commands from the repository root, which must contain both `src/` and
`examples/`.

## Run with pytest

```bash
python -m pytest examples/test_s1_default.py -v
```

A successful run should report:

```text
examples/test_s1_default.py::test_s1_pipeline_smoke PASSED
```

To check discovery without running the pipeline:

```bash
python -m pytest examples/test_s1_default.py --collect-only -v
```

## Create the auditable CSV output

Run the example as a module:

```bash
python -m examples.test_s1_default
```

This writes:

```text
s1_smoke_test_comparison.csv
```

The export is intentionally **self-contained**. Each row represents one policy
strategy and contains both:

1. the strategy's comparison outcomes; and
2. the complete set of simulation, EWI, policy, benchmark, and realized-run
   parameters used to produce those outcomes.

Parameter columns use explicit prefixes:

- `simulation_` for network and simulation settings;
- `ewi_` for configured EWI settings;
- `policy_` for policy settings;
- `benchmark_` for randomized-benchmark settings; and
- `realized_` for run-specific quantities such as the realized risk threshold
  and EWI diagnostics.

The settings are repeated on every strategy row. This deliberate rectangular
format keeps the CSV easy to inspect, filter, compare, and import into standard
analysis software. It also ensures that a copied or filtered result row retains
the complete parameter record required to interpret the result.

The CSV is an **audit and reproducibility artefact**. It allows a reviewer to
verify the configuration associated with a reported outcome. The pytest
assertions, rather than the existence of the CSV or its printed values,
determine whether the smoke test passes.

## Strategies checked

The comparison contains:

1. no intervention;
2. reactive countercyclical intervention;
3. EWI-targeted intervention;
4. randomized-timing intervention at the EWI rule's realized support volume;
5. perfect-information oracle at equal support volume.

The test confirms that every deterministic policy result contains:

```text
risk_scenario_rate
risk_day_rate
total_shortfall
```

It also checks that principal arrays and policy masks preserve:

```text
(1, trading_days)
```

## Reproducibility and interpretation

The simulation and EWI use the configured random seed. The randomized benchmark
uses a separately recorded deterministic seed derived from the simulation seed.
The number of benchmark replications is also included in the CSV.

Exact outcomes are not hard-coded in this README because results may change
when model defaults, policy logic, or output definitions are updated. The CSV
records the settings and realized diagnostics for the actual run, while the
smoke test checks shapes, required fields, finite values where applicable, and
successful construction of the comparison table.

The \examples directory contains a CSV record with settings and realized diagnostic for an actual run: s1_smoke_test_default_comparison.csv.

## Common failures

- `collected 0 items`: ensure the file begins with `test_` and the test function
  is named `test_s1_pipeline_smoke`;
- `ModuleNotFoundError: No module named 'src'`: run the command from the
  repository root;
- `missing result keys`: pass policy outcomes from `run_policy()` to the
  comparison function, not EWI recall and precision diagnostics;
- unexpected array shape: inspect whether a function collapsed the scenario
  dimension when `S = 1`.

For the full model logic, see
[`../MODEL_DESCRIPTION.md`](../MODEL_DESCRIPTION.md).
