"""
comparison.py - Policy-comparison table, figure, and export helpers.

The module compares five strategies:

1. Baseline: no intervention.
2. Reactive countercyclical intervention.
3. EWI-targeted intervention.
4. Randomized timing with the same support volume as the EWI intervention.
5. Perfect-information oracle with the same support volume as the EWI intervention.

Each deterministic strategy is passed as one dictionary containing both its
liquidity metrics and its policy-output values. For example, merge the outputs
of ``run_policy`` before calling this module:

    ewi_result = {**ewi_metrics, **ewi_extras}

This avoids separate ``extra`` arguments. The countercyclical delay is also not
part of this module; the comparison table uses a fixed strategy label.
"""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


_COLUMNS = [
    "Policy",
    "Risk-scenario rate (%)",
    "Risk-day rate (%)",
    "Total routing-capacity shortfall",
    "Total support volume",
]


def _policy_row(label: str, result: dict) -> dict:
    """Convert one deterministic strategy result to the common table schema."""
    if result is None:
        raise ValueError(f"result must be supplied for {label!r}")

    required = {
        "risk_scenario_rate",
        "risk_day_rate",
        "total_shortfall",
    }
    missing = required.difference(result)
    if missing:
        raise ValueError(
            f"{label!r} is missing result keys: " + ", ".join(sorted(missing))
        )
# return with two figures behind the comma
    return {
        "Policy": label,
        "Risk-scenario rate (%)": round(float(result["risk_scenario_rate"]), 2),
        "Risk-day rate (%)": round(float(result["risk_day_rate"]), 2),
        "Total routing-capacity shortfall": round(float(result["total_shortfall"]), 0),
        "Total support volume": round(float(result.get("total_support_volume", 0.0)), 0),
    }


def _randomized_timing_row(randomized: pd.DataFrame) -> dict:
    """Summarize randomized-timing replications by column medians."""
    required = {
        "risk_scenario_rate",
        "risk_day_rate",
        "total_shortfall",
        "total_support_volume",
    }
    missing = required.difference(randomized.columns)
    if missing:
        raise ValueError(
            "randomized-timing results are missing columns: "
            + ", ".join(sorted(missing))
        )
    if randomized.empty:
        raise ValueError("randomized-timing results must not be empty")

    return {
        "Policy": "Randomized timing (equal volume)",
        "Risk-scenario rate (%)": round(float(randomized["risk_scenario_rate"].median()), 2),
        "Risk-day rate (%)": round(float(randomized["risk_day_rate"].median()), 2),
        "Total routing-capacity shortfall": round(float(randomized["total_shortfall"].median()), 0),
        "Total support volume": round(float(randomized["total_support_volume"].median()), 0),
    }


def build_policy_comparison(
    baseline: dict,
    countercyclical: dict,
    ewi: dict,
    randomized: pd.DataFrame,
    oracle: dict,
) -> pd.DataFrame:
    """Build the five-row policy-comparison table.

    Parameters
    ----------
    baseline:
        Baseline liquidity metrics. Its support volume is normally zero.
    countercyclical:
        Combined countercyclical metrics and policy outputs.
    ewi:
        Combined EWI metrics and policy outputs.
    randomized:
        Replication-level randomized-timing results. Medians are reported.
    oracle:
        Combined oracle metrics and policy outputs.

    Returns
    -------
    pandas.DataFrame
        Five strategies ordered as baseline, reactive countercyclical, EWI,
        randomized timing, and perfect-information oracle.
    """
    rows = [
        _policy_row("Baseline: no intervention", baseline),
        _policy_row("Reactive countercyclical intervention", countercyclical),
        _policy_row("EWI-targeted intervention", ewi),
        _randomized_timing_row(randomized),
        _policy_row("Perfect-information oracle (equal volume)", oracle),
    ]
    return pd.DataFrame(rows, columns=_COLUMNS)


def policy_comparison_figure(
    df: pd.DataFrame,
    total_available: float | None = None,
):
    """Create a three-panel comparison for every strategy in ``df``.

    Panel A shows the scenario-based liquidity-risk rate. Panel B shows the
    liquidity-risk day rate. Panel C shows routing-capacity shortfall as a
    percentage of total available routing liquidity.
    """
    required = {
        "Policy",
        "Risk-scenario rate (%)",
        "Risk-day rate (%)",
        "Total routing-capacity shortfall",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            "policy comparison is missing columns: "
            + ", ".join(sorted(missing))
        )
    if df.empty:
        raise ValueError("policy comparison must contain at least one strategy")

    relative_column = "Routing-capacity shortfall (% of available)"
    if relative_column in df.columns:
        shortfall_pct = pd.to_numeric(
            df[relative_column], errors="coerce"
        ).to_numpy(float)
    else:
        if (
            total_available is None
            or not np.isfinite(total_available)
            or total_available <= 0
        ):
            raise ValueError(
                "policy_comparison_figure needs the relative-shortfall column "
                "or a positive total_available"
            )
        shortfall_abs = pd.to_numeric(
            df["Total routing-capacity shortfall"], errors="coerce"
        ).to_numpy(float)
        shortfall_pct = shortfall_abs / float(total_available) * 100.0

    labels = df["Policy"].astype(str).tolist()
    number_of_policies = len(labels)
    x = np.arange(number_of_policies)

    # Colors follow the fixed five-row strategy order.
    standard_colors = [
        "#6b7280",  # baseline
        "#31a354",  # reactive countercyclical
        "#d95f0e",  # EWI-targeted
        "#9ecae1",  # randomized timing
        "#756bb1",  # oracle
    ]

    figure_width = max(16.0, 2.4 * number_of_policies + 5.0)
    fig, axes = plt.subplots(1, 3, figsize=(figure_width, 6.2))

    specifications = [
        (
            pd.to_numeric(
                df["Risk-scenario rate (%)"], errors="coerce"
            ).to_numpy(float),
            "A. Scenario-based liquidity-risk rate",
        ),
        (
            pd.to_numeric(
                df["Risk-day rate (%)"], errors="coerce"
            ).to_numpy(float),
            "B. Liquidity-risk day rate",
        ),
        (
            shortfall_pct,
            "C. Routing-capacity shortfall (% of available)",
        ),
    ]

    for ax, (values, title) in zip(axes, specifications):
        bars = ax.bar(
            x,
            values,
            color=standard_colors[:number_of_policies],
            edgecolor="black",
            linewidth=0.7,
        )
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=25, ha="right")
        ax.set_ylabel(title.split(". ", 1)[-1])
        ax.grid(axis="y", alpha=0.2)

        value_labels = [
            f"{value:.2f}%" if np.isfinite(value) else "N/A"
            for value in values
        ]
        ax.bar_label(bars, labels=value_labels, padding=3, fontsize=8)

        finite_values = values[np.isfinite(values)]
        maximum = float(np.max(finite_values)) if finite_values.size else 1.0
        ax.set_ylim(0, max(maximum * 1.14, 1e-9))

    fig.suptitle(
        "Liquidity-support timing strategies and information benchmarks",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def figure_to_png_bytes(fig, dpi: int = 300) -> bytes:
    """Render one Matplotlib figure as PNG bytes."""
    buffer = BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=dpi,
        bbox_inches="tight",
        facecolor="white",
    )
    return buffer.getvalue()


def png_zip_bytes(figures: dict, dpi: int = 300) -> bytes:
    """Bundle named Matplotlib figures into a ZIP archive of PNG files."""
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, figure in figures.items():
            archive.writestr(name, figure_to_png_bytes(figure, dpi))
    return buffer.getvalue()


def tables_to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Write named DataFrames to a multi-sheet Excel workbook in memory."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, dataframe in sheets.items():
            dataframe.to_excel(
                writer,
                sheet_name=name[:31],
                index=False,
            )
    return buffer.getvalue()
