# S = 1 pipeline smoke test

An integration smoke test of the routing-liquidity engine using a single Monte
Carlo scenario (`S = 1`). It verifies that the smallest supported scenario
dimension passes through the full computational pipeline without runtime,
shape, indexing, broadcasting, or missing-field errors.

> **Scope:** this is an execution and integration check. It does not validate
> economic calibration, statistical inference, Monte Carlo convergence, or the
> stability of estimated policy effects.

## At a glance

| | |
|---|---|
| **Test file** | `examples/test_s1_default.py` |
| **Test function** | `test_s1_pipeline_smoke` |
| **Run time** | A few seconds |
| **Pass criterion** | `1 passed`. The pytest assertions decide; the CSV is not part of the criterion. |
| **Audit output** | `s1_smoke_test_comparison.csv` (5 rows, one per strategy) |
| **Reference output** | `examples/s1_smoke_test_default_comparison.csv` (one committed run with default settings) |
| **Run from** | The repository root, which contains `src/` and `examples/` |

## Quick check

```bash
python -m pytest examples/test_s1_default.py -v      # 1. run the test
python -m examples.test_s1_default                   # 2. write the audit CSV
```

Step 3 compares the fresh CSV with the committed reference (see
[Verify against the reference output](#3-verify-against-the-reference-output)).

## 1. Run the test

```bash
python -m pytest examples/test_s1_default.py -v
```

Expected output (timing varies):

```text
examples/test_s1_default.py::test_s1_pipeline_smoke PASSED
============================== 1 passed in 2.1s ==============================
```

Use `python -m pytest` so that the repository root is on the import path and
`from src... import ...` resolves in every setup.

To check test discovery without running the pipeline:

```bash
python -m pytest examples/test_s1_default.py --collect-only -v
```

## 2. Create the audit CSV

```bash
python -m examples.test_s1_default
```

This prints `S=1 pipeline smoke test passed.`, the output path, and the full
table. It writes `s1_smoke_test_comparison.csv` to the current working
directory and overwrites an existing file.

## 3. Verify against the reference output

A reference copy of the CSV from an actual run with the default settings is
committed as `examples/s1_smoke_test_default_comparison.csv`. Compare your fresh
output with it to confirm that your installation reproduces the same results.

Use a tolerance-based comparison rather than a plain text `diff` or `fc`.
Floating-point values can differ in the last digits across NumPy versions and
platforms even when the results are the same.

```bash
python -c "import pandas as pd, numpy as np; a=pd.read_csv('s1_smoke_test_comparison.csv'); b=pd.read_csv('examples/s1_smoke_test_default_comparison.csv'); n=a.select_dtypes('number').columns; assert list(a.columns)==list(b.columns) and a.drop(columns=n).equals(b.drop(columns=n)); np.testing.assert_allclose(a[n], b[n], rtol=1e-9); print('Reproduced')"
```

The command works in macOS, Linux, and Windows shells and prints `Reproduced`.
It fails with an `AssertionError` if a label, column, or value differs, for
example after a change to a model default.

## 4. Structure of the CSV

The file has one row per policy strategy. Each row holds the strategy outcomes
followed by the complete parameter record of the run.

**Outcome columns**

| Column | Meaning |
|---|---|
| `Policy` | Strategy label |
| `Risk-scenario rate (%)` | Share of scenarios with at least one risk day |
| `Risk-day rate (%)` | Share of scenario-days classified as risk days |
| `Total routing-capacity shortfall` | Summed shortfall below the risk threshold |
| `Total support volume` | Support deployed by the strategy |

**Parameter columns** use explicit prefixes so that their source is clear and
names cannot collide:

| Prefix | Content |
|---|---|
| `simulation_` | Network and simulation settings (nodes, scenarios, trading days, seed, μ, σ, half-life, and others) |
| `ewi_` | Configured EWI targets (recall, precision, lead time, seed) |
| `policy_` | Policy settings (buffer release, injection, support days, start delay, combined support) |
| `benchmark_` | Randomized-benchmark settings (replications, seed) |
| `realized_` | Run-specific results: the realized risk threshold and the realized EWI diagnostics (event and signal counts, realized recall and precision) |

The settings are repeated on every row. This rectangular layout keeps the file
easy to filter and import, and a copied or filtered row still carries the full
record needed to interpret it.

## 5. What the test checks

| Stage | Checks |
|---|---|
| Configuration | `PolicyConfig.validate()` accepts the settings. |
| Baseline simulation | `gamma`, `direct_lm`, `indirect_lm`, `direct_liquidity`, `indirect_liquidity`, `event_day` (and `log_gamma` if present) have shape `(1, trading_days)`. Gamma is finite and strictly positive. The risk threshold is finite. |
| Baseline metrics | `risk_scenario_rate`, `risk_day_rate`, `total_shortfall` are present and finite. |
| EWI | Flags have shape `(1, trading_days)`. The diagnostics contain evaluable event days, true- and false-positive signal days, and target and realized recall and precision. |
| Activation masks | The EWI, countercyclical, and oracle masks have shape `(1, trading_days)`. |
| Policy runs | Liquidity paths for the EWI, countercyclical, and oracle strategies have the expected shape and are finite. Each result contains the three required metrics. |
| Randomized benchmark | Returns a non-empty `pandas.DataFrame` (1,000 replications). |
| Comparison | `build_policy_comparison` returns a `DataFrame` with exactly five rows. |
| Audit table | Parameters are appended to all rows, and `simulation_scenarios` equals 1 on every row. |

The strategies in the comparison are:

1. Baseline: no intervention
2. Reactive countercyclical intervention
3. EWI-targeted intervention
4. Randomized timing at the EWI rule's realized support volume
5. Perfect-information oracle at equal support volume

## 6. Reproducibility

- The simulation and the EWI use the configured seed (default 42).
- The randomized benchmark uses a separate seed, recorded as `benchmark_seed`
  (simulation seed + 42), and 1,000 replications, recorded as
  `benchmark_replications`. The Streamlit app uses its own benchmark seed
  (simulation seed + 1000), so the randomized-timing row of this test is not
  expected to match the application's output.
- Two runs with identical settings, library versions, and platform produce
  identical tables.
- Outcomes are not hard-coded in this README or in the test, because they change
  whenever model defaults, policy logic, or output definitions change. The CSV
  records the settings and realized diagnostics of the actual run.
- The committed reference CSV is a record of one run. Regenerate it whenever
  defaults or logic change, so that it always matches the code:

  ```bash
  python -m examples.test_s1_default
  cp s1_smoke_test_comparison.csv examples/s1_smoke_test_default_comparison.csv
  ```

  (On Windows PowerShell, use `Copy-Item` instead of `cp`.) Then run the check in
  [section 3](#3-verify-against-the-reference-output) and commit both files.

### Interpreting a single scenario

With `S = 1`, realized EWI recall and precision can differ noticeably from their
targets, because they rest on only a handful of events and signals (integer
counts). Risk-scenario rates are either 0 % or 100 %. This is expected and is why
the test makes no statistical claims. Use the full application (default 1,000
scenarios) for substantive results.

## 7. Common failures

| Symptom | Likely cause and fix |
|---|---|
| `collected 0 items` | The file name must start with `test_` and the function must be named `test_s1_pipeline_smoke`. |
| `ModuleNotFoundError: No module named 'src'` | Run from the repository root, using `python -m pytest`. |
| `No module named examples.test_s1_default` | Run from the repository root and use the module form shown in section 2. Check that `examples/__init__.py` exists. |
| `... result is missing keys` | Pass the merged outcome of `run_policy()` (metrics and supplementary output) to the comparison, not the EWI recall and precision diagnostics. |
| Unexpected array shape | Check whether a function collapsed the scenario dimension when `S = 1`. |
| Reference check fails (`AssertionError`) | Defaults, logic, or library versions changed. Regenerate the reference as described in section 6. |

For the full model logic, see [`../MODEL_DESCRIPTION.md`](../MODEL_DESCRIPTION.md).
