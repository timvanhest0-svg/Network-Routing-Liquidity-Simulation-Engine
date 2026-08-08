"""S=1 integration smoke test for the routing-liquidity pipeline.

This test verifies that the smallest supported scenario dimension passes through
the baseline simulation, EWI, policy, randomized benchmark, and five-strategy
comparison pipeline without runtime, shape, indexing, broadcasting, or
missing-field errors.

The test does not validate economic calibration, statistical inference, Monte
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


BENCHMARK_REPLICATIONS = 10
BENCHMARK_SEED_OFFSET = 1_000
OUTPUT_CSV = Path("s1_smoke_test_comparison.csv")

REQUIRED_POLICY_KEYS = {
    "risk_scenario_rate",
    "risk_day_rate",
    "total_shortfall",
}


def _assert_shape(name: str, values: Any, expected_shape: tuple[int, int]) -> None:
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
    parameters.update(_public_attributes(simulation_config, "simulation_"))
    parameters.update(_public_attributes(ewi_config, "ewi_"))
    parameters.update(_public_attributes(policy_config, "policy_"))

    # Derived and execution-specific settings are recorded explicitly because
    # they may not be stored as fields on the configuration objects.
    parameters.update(
        {
            "policy_combined_support_pct": policy_config.combined_support_pct,
            "benchmark_replications": BENCHMARK_REPLICATIONS,
            "benchmark_seed": simulation_config.seed + BENCHMARK_SEED_OFFSET,
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
        _assert_shape("log_gamma", simulation["log_gamma"], expected_shape)

    gamma = np.asarray(simulation["gamma"], dtype=float)
    assert np.all(np.isfinite(gamma)), "gamma contains non-finite values"
    assert np.all(gamma > 0.0), "gamma must remain strictly positive"
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
    missing_diagnostics = required_ewi_diagnostics.difference(ewi_diagnostics)
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
    countercyclical_result = {**counter_metrics, **counter_extra}
    oracle_result = {**oracle_metrics, **oracle_extra}

    _assert_policy_result("EWI", ewi_result)
    _assert_policy_result("countercyclical", countercyclical_result)
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
    assert not randomized_result.empty, "randomized benchmark is empty"

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
    assert not comparison.empty, "policy comparison is empty"
    assert len(comparison) == 5, (
        f"comparison contains {len(comparison)} rows; expected 5"
    )

    return comparison, parameters


def test_s1_pipeline_smoke() -> None:
    """Verify the S=1 pipeline and its self-contained audit export."""
    comparison, parameters = _run_s1_pipeline()
    audit_table = _comparison_with_parameters(comparison, parameters)

    assert not audit_table.empty
    assert len(audit_table) == 5
    assert "simulation_scenarios" in audit_table.columns
    assert "benchmark_seed" in audit_table.columns
    assert audit_table["simulation_scenarios"].eq(1).all()


def main() -> None:
    """Run the smoke test manually and export results with all run settings."""
    comparison, parameters = _run_s1_pipeline()
    audit_table = _comparison_with_parameters(comparison, parameters)
    audit_table.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    print("S=1 pipeline smoke test passed.")
    print(f"Audit CSV written to: {OUTPUT_CSV.resolve()}")
    print(audit_table.to_string(index=False))


if __name__ == "__main__":
    main()
