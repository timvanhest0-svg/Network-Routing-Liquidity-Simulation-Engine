"""S=1 integration and regression tests for the routing-liquidity pipeline.

These tests verify that the smallest supported scenario dimension passes through
the baseline simulation, EWI, policy, randomized benchmark, and five-strategy
comparison pipeline without runtime, shape, indexing, broadcasting, or
missing-field errors.

The regression test also compares the resulting audit table with the committed
reference output using tolerance-based numerical comparisons. This detects
unintended changes in default model output while allowing negligible
platform-dependent floating-point differences.

The tests do not validate economic calibration, statistical inference, Monte
Carlo convergence, or the stability of estimated policy effects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.comparison import build_policy_comparison
from src.ewi import EWIConfig, create_ewi
from src.metrics import evaluate_liquidity
from src.policy import (
    PolicyConfig,
    event_delayed_active_mask,
    forward_active_mask,
    oracle_active_mask_same_volume,
    run_policy,
    run_random_benchmarks,
)
from src.simulation import SimulationConfig, simulate_base_paths


BENCHMARK_REPLICATIONS = 1000
BENCHMARK_SEED_OFFSET = 42

EXAMPLES_DIR = Path(__file__).resolve().parent
REFERENCE_CSV = EXAMPLES_DIR / "s1_smoke_test_default_comparison.csv"
OUTPUT_CSV = Path.cwd() / "s1_smoke_test_comparison.csv"

CSV_FLOAT_FORMAT = "%.10g"
REFERENCE_RTOL = 1e-9
REFERENCE_ATOL = 1e-12

REQUIRED_POLICY_KEYS = {
    "risk_scenario_rate",
    "risk_day_rate",
    "total_shortfall",
}

EXPECTED_POLICIES = [
    "Baseline: no intervention",
    "Reactive countercyclical intervention",
    "EWI-targeted intervention",
    "Randomized timing (equal volume)",
    "Perfect-information oracle (equal volume)",
]

EWI_POLICY = "EWI-targeted intervention"
RANDOM_POLICY = "Randomized timing (equal volume)"
ORACLE_POLICY = "Perfect-information oracle (equal volume)"


def _assert_shape(
    name: str,
    values: Any,
    expected_shape: tuple[int, int],
) -> None:
    """Assert that an array-like result has the expected scenario-day shape."""
    actual_shape = np.asarray(values).shape
    assert actual_shape == expected_shape, (
        f"{name} has shape {actual_shape}; expected {expected_shape}"
    )


def _assert_policy_result(name: str, result: dict[str, Any]) -> None:
    """Assert that a deterministic policy result has the required metrics."""
    missing = REQUIRED_POLICY_KEYS.difference(result)
    assert not missing, f"{name} result is missing keys: {sorted(missing)}"

    for key in REQUIRED_POLICY_KEYS:
        assert np.isfinite(result[key]), (
            f"{name} result {key!r} is not finite: {result[key]!r}"
        )


def _assert_equal_support_volume(comparison: pd.DataFrame) -> None:
    """Verify equal-volume treatment of EWI, randomized, and oracle strategies."""
    required_columns = {"Policy", "Total support volume"}
    missing = required_columns.difference(comparison.columns)
    assert not missing, (
        "comparison is missing columns required for the equal-volume check: "
        f"{sorted(missing)}"
    )

    indexed = comparison.set_index("Policy")

    for policy in (EWI_POLICY, RANDOM_POLICY, ORACLE_POLICY):
        assert policy in indexed.index, (
            f"comparison is missing the expected policy row {policy!r}"
        )

    ewi_volume = float(indexed.loc[EWI_POLICY, "Total support volume"])
    random_volume = float(indexed.loc[RANDOM_POLICY, "Total support volume"])
    oracle_volume = float(indexed.loc[ORACLE_POLICY, "Total support volume"])

    assert np.isclose(
        ewi_volume,
        random_volume,
        rtol=0.0,
        atol=1e-12,
    ), (
        "randomized timing does not use the same support volume as the "
        f"EWI strategy: EWI={ewi_volume}, randomized={random_volume}"
    )

    assert np.isclose(
        ewi_volume,
        oracle_volume,
        rtol=0.0,
        atol=1e-12,
    ), (
        "the oracle does not use the same support volume as the "
        f"EWI strategy: EWI={ewi_volume}, oracle={oracle_volume}"
    )


def _public_attributes(config: Any, prefix: str) -> dict[str, Any]:
    """Return public configuration attributes with audit-friendly prefixes.

    CODECHECK: prefixes preserve the source of each parameter and prevent name
    collisions between simulation, EWI, and policy configuration objects.
    """
    return {
        f"{prefix}{name}": value
        for name, value in vars(config).items()
        if not name.startswith("_")
    }


def _build_audit_parameters(
    simulation_config: SimulationConfig,
    ewi_config: EWIConfig,
    policy_config: PolicyConfig,
) -> dict[str, Any]:
    """Collect all parameters required to reproduce the S=1 run."""
    parameters: dict[str, Any] = {}
    parameters.update(
        _public_attributes(simulation_config, "simulation_")
    )
    parameters.update(
        _public_attributes(ewi_config, "ewi_")
    )
    parameters.update(
        _public_attributes(policy_config, "policy_")
    )

    # Derived and execution-specific settings are recorded explicitly because
    # they may not be stored as fields on the configuration objects.
    parameters.update(
        {
            "policy_combined_support_pct": (
                policy_config.combined_support_pct
            ),
            "benchmark_replications": BENCHMARK_REPLICATIONS,
            "benchmark_seed": (
                simulation_config.seed + BENCHMARK_SEED_OFFSET
            ),
        }
    )
    return parameters


def _comparison_with_parameters(
    comparison: pd.DataFrame,
    parameters: dict[str, Any],
) -> pd.DataFrame:
    """Append run parameters to every strategy row in the comparison table.

    Repeating the settings on each row keeps the CSV rectangular, filterable,
    and self-contained. A copied or filtered strategy row therefore retains the
    complete parameter record used to generate it.
    """
    audit_table = comparison.copy()

    for column, value in parameters.items():
        audit_table[column] = value

    return audit_table


def _assert_matches_reference(
    actual: pd.DataFrame,
    reference_path: Path = REFERENCE_CSV,
) -> None:
    """Compare an audit table with the committed reference output.

    Labels, column order, and row order must match exactly. Numeric values are
    compared using tolerances to allow negligible platform- or NumPy-dependent
    floating-point differences.
    """
    assert reference_path.is_file(), (
        "committed reference output was not found at "
        f"{reference_path}"
    )

    expected = pd.read_csv(reference_path)

    assert list(actual.columns) == list(expected.columns), (
        "audit-table columns differ from the committed reference.\n"
        f"Actual columns: {list(actual.columns)}\n"
        f"Expected columns: {list(expected.columns)}"
    )

    assert len(actual) == len(expected), (
        "audit-table row count differs from the committed reference: "
        f"actual={len(actual)}, expected={len(expected)}"
    )

    actual = actual.reset_index(drop=True)
    expected = expected.reset_index(drop=True)

    numeric_columns = expected.select_dtypes(include=[np.number]).columns.tolist()
    text_columns = [
        column
        for column in expected.columns
        if column not in numeric_columns
    ]

    if text_columns:
        pd.testing.assert_frame_equal(
            actual[text_columns],
            expected[text_columns],
            check_dtype=False,
            check_exact=True,
        )

    if numeric_columns:
        actual_numeric = actual[numeric_columns].apply(
            pd.to_numeric,
            errors="raise",
        )
        expected_numeric = expected[numeric_columns].apply(
            pd.to_numeric,
            errors="raise",
        )

        np.testing.assert_allclose(
            actual_numeric.to_numpy(dtype=float),
            expected_numeric.to_numpy(dtype=float),
            rtol=REFERENCE_RTOL,
            atol=REFERENCE_ATOL,
            equal_nan=True,
            err_msg=(
                "S=1 default output differs from the committed reference "
                "beyond the allowed numerical tolerance"
            ),
        )


def _run_s1_pipeline() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run the complete five-strategy pipeline for one scenario."""
    # ------------------------------------------------------------------
    # 1. Explicit configurations
    # ------------------------------------------------------------------
    simulation_config = SimulationConfig(scenarios=1)
    ewi_config = EWIConfig(seed=simulation_config.seed)
    policy_config = PolicyConfig()
    policy_config.validate(simulation_config.buffer_normal_pct)

    parameters = _build_audit_parameters(
        simulation_config,
        ewi_config,
        policy_config,
    )

    # ------------------------------------------------------------------
    # 2. Baseline simulation and validation
    # ------------------------------------------------------------------
    simulation = simulate_base_paths(simulation_config)
    expected_shape = (1, simulation_config.trading_days)

    for key in (
        "gamma",
        "direct_lm",
        "indirect_lm",
        "direct_liquidity",
        "indirect_liquidity",
        "event_day",
    ):
        assert key in simulation, f"simulation output is missing {key!r}"
        _assert_shape(key, simulation[key], expected_shape)

    if "log_gamma" in simulation:
        _assert_shape(
            "log_gamma",
            simulation["log_gamma"],
            expected_shape,
        )

    gamma = np.asarray(simulation["gamma"], dtype=float)
    assert np.all(np.isfinite(gamma)), (
        "gamma contains non-finite values"
    )
    assert np.all(gamma > 0.0), (
        "gamma must remain strictly positive"
    )
    assert np.isfinite(simulation["risk_threshold"]), (
        "risk_threshold must be finite"
    )

    # ------------------------------------------------------------------
    # 3. Baseline liquidity metrics
    # ------------------------------------------------------------------
    baseline_metrics = evaluate_liquidity(
        simulation["direct_liquidity"],
        simulation["risk_threshold"],
    )
    _assert_policy_result("baseline", baseline_metrics)

    # ------------------------------------------------------------------
    # 4. Synthetic early-warning indicator
    # ------------------------------------------------------------------
    event_days = np.asarray(simulation["event_day"], dtype=bool)
    flags, ewi_diagnostics = create_ewi(event_days, ewi_config)
    _assert_shape("EWI flags", flags, expected_shape)

    required_ewi_diagnostics = {
        "evaluable_event_days",
        "true_positive_signal_days",
        "false_positive_signal_days",
        "target_recall_pct",
        "realized_recall_pct",
        "target_precision_pct",
        "realized_precision_pct",
    }
    missing_diagnostics = required_ewi_diagnostics.difference(
        ewi_diagnostics
    )
    assert not missing_diagnostics, (
        "EWI output is missing diagnostics: "
        f"{sorted(missing_diagnostics)}"
    )

    # Record realized EWI diagnostics because finite-sample performance may
    # differ from its configured targets, especially when S=1.
    parameters.update(
        {
            f"realized_ewi_{name}": value
            for name, value in ewi_diagnostics.items()
        }
    )
    parameters["realized_risk_threshold"] = simulation["risk_threshold"]

    # ------------------------------------------------------------------
    # 5. Policy activation masks
    # ------------------------------------------------------------------
    ewi_active = forward_active_mask(
        flags,
        policy_config.support_days,
        policy_config.start_delay,
    )
    countercyclical_active = event_delayed_active_mask(
        event_days,
        policy_config.support_days,
        policy_config.start_delay,
    )
    oracle_active = oracle_active_mask_same_volume(
        simulation["direct_liquidity"],
        simulation["risk_threshold"],
        ewi_active,
    )

    for name, mask in {
        "EWI active mask": ewi_active,
        "countercyclical active mask": countercyclical_active,
        "oracle active mask": oracle_active,
    }.items():
        _assert_shape(name, mask, expected_shape)

    assert int(np.asarray(oracle_active, dtype=bool).sum()) == int(
        np.asarray(ewi_active, dtype=bool).sum()
    ), (
        "oracle active-day count does not equal the EWI active-day count"
    )

    # ------------------------------------------------------------------
    # 6. Deterministic policy outcomes
    # ------------------------------------------------------------------
    ewi_liquidity, ewi_metrics, ewi_extra, _ = run_policy(
        simulation["direct_lm"],
        simulation["risk_threshold"],
        baseline_metrics,
        simulation_config.investment,
        simulation_config.buffer_normal_pct,
        ewi_active,
        policy_config.combined_support_pct,
    )
    counter_liquidity, counter_metrics, counter_extra, _ = run_policy(
        simulation["direct_lm"],
        simulation["risk_threshold"],
        baseline_metrics,
        simulation_config.investment,
        simulation_config.buffer_normal_pct,
        countercyclical_active,
        policy_config.combined_support_pct,
    )
    oracle_liquidity, oracle_metrics, oracle_extra, _ = run_policy(
        simulation["direct_lm"],
        simulation["risk_threshold"],
        baseline_metrics,
        simulation_config.investment,
        simulation_config.buffer_normal_pct,
        oracle_active,
        policy_config.combined_support_pct,
    )

    for name, liquidity in {
        "EWI policy liquidity": ewi_liquidity,
        "countercyclical policy liquidity": counter_liquidity,
        "oracle policy liquidity": oracle_liquidity,
    }.items():
        liquidity_array = np.asarray(liquidity, dtype=float)
        _assert_shape(name, liquidity_array, expected_shape)
        assert np.all(np.isfinite(liquidity_array)), (
            f"{name} contains non-finite values"
        )

    # CODECHECK: run_policy separates common metrics and supplementary output.
    # Merge both dictionaries before passing a strategy to the comparison layer.
    ewi_result = {**ewi_metrics, **ewi_extra}
    countercyclical_result = {
        **counter_metrics,
        **counter_extra,
    }
    oracle_result = {**oracle_metrics, **oracle_extra}

    _assert_policy_result("EWI", ewi_result)
    _assert_policy_result(
        "countercyclical",
        countercyclical_result,
    )
    _assert_policy_result("oracle", oracle_result)

    # ------------------------------------------------------------------
    # 7. Randomized-timing benchmark
    # ------------------------------------------------------------------
    randomized_result = run_random_benchmarks(
        simulation["direct_lm"],
        simulation["risk_threshold"],
        baseline_metrics,
        simulation_config.investment,
        simulation_config.buffer_normal_pct,
        ewi_active,
        policy_config.combined_support_pct,
        BENCHMARK_REPLICATIONS,
        parameters["benchmark_seed"],
    )

    assert isinstance(randomized_result, pd.DataFrame), (
        "randomized benchmark must return a pandas DataFrame"
    )
    assert not randomized_result.empty, (
        "randomized benchmark is empty"
    )
    assert len(randomized_result) == BENCHMARK_REPLICATIONS, (
        "randomized benchmark contains "
        f"{len(randomized_result)} replications; "
        f"expected {BENCHMARK_REPLICATIONS}"
    )

    required_random_columns = {
        "risk_scenario_rate",
        "risk_day_rate",
        "total_shortfall",
        "total_support_volume",
    }
    missing_random_columns = required_random_columns.difference(
        randomized_result.columns
    )
    assert not missing_random_columns, (
        "randomized benchmark is missing columns: "
        f"{sorted(missing_random_columns)}"
    )

    random_numeric = randomized_result[
        sorted(required_random_columns)
    ].to_numpy(dtype=float)
    assert np.all(np.isfinite(random_numeric)), (
        "randomized benchmark contains non-finite outcome values"
    )

    # Every randomized replication should deploy the same support volume as
    # the EWI intervention, not only the same median volume.
    expected_support_volume = float(
        ewi_result["total_support_volume"]
    )
    randomized_support_volumes = randomized_result[
        "total_support_volume"
    ].to_numpy(dtype=float)

    np.testing.assert_allclose(
        randomized_support_volumes,
        expected_support_volume,
        rtol=0.0,
        atol=1e-12,
        err_msg=(
            "one or more randomized benchmark replications do not use "
            "the EWI strategy's support volume"
        ),
    )

    # ------------------------------------------------------------------
    # 8. Five-strategy comparison table
    # ------------------------------------------------------------------
    comparison = build_policy_comparison(
        baseline_metrics,
        countercyclical_result,
        ewi_result,
        randomized_result,
        oracle_result,
    )

    assert isinstance(comparison, pd.DataFrame), (
        "comparison must be a pandas DataFrame"
    )
    assert not comparison.empty, (
        "policy comparison is empty"
    )
    assert len(comparison) == 5, (
        f"comparison contains {len(comparison)} rows; expected 5"
    )

    assert "Policy" in comparison.columns, (
        "comparison is missing the Policy column"
    )
    assert comparison["Policy"].tolist() == EXPECTED_POLICIES, (
        "comparison policy labels or row order differ from the expected "
        "five-strategy structure"
    )

    _assert_equal_support_volume(comparison)

    return comparison, parameters


def test_s1_pipeline_smoke() -> None:
    """Verify execution, dimensions, outputs, and equal-volume controls."""
    comparison, parameters = _run_s1_pipeline()
    audit_table = _comparison_with_parameters(
        comparison,
        parameters,
    )

    assert not audit_table.empty
    assert len(audit_table) == 5
    assert "simulation_scenarios" in audit_table.columns
    assert "benchmark_seed" in audit_table.columns
    assert audit_table["simulation_scenarios"].eq(1).all()


def test_s1_default_matches_reference() -> None:
    """Verify default numerical output against the committed reference CSV."""
    comparison, parameters = _run_s1_pipeline()
    actual = _comparison_with_parameters(
        comparison,
        parameters,
    )

    _assert_matches_reference(actual)


def main() -> None:
    """Run the checks manually and export results with all run settings."""
    comparison, parameters = _run_s1_pipeline()
    audit_table = _comparison_with_parameters(
        comparison,
        parameters,
    )

    # Run the numerical regression check during manual execution as well.
    _assert_matches_reference(audit_table)

    # CODECHECK: write ten significant digits so negligible differences in
    # floating-point representation do not create noisy audit files.
    audit_table.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8",
        float_format=CSV_FLOAT_FORMAT,
    )

    print("S=1 pipeline smoke test passed.")
    print("S=1 reference-output regression test passed.")
    print(f"Reference CSV: {REFERENCE_CSV}")
    print(f"Audit CSV written to: {OUTPUT_CSV.resolve()}")
    print(audit_table.to_string(index=False))


if __name__ == "__main__":
    main()
