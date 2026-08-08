"""Visualization utilities for simulated network-routing capacity.

The module contains reusable, deterministic Matplotlib functions for:

* one selected routing-capacity scenario;
* the full Monte Carlo simulation ensemble; and
* realized tail-exponent and routing-multiplier distributions.

The plotting layer does not access Streamlit session state. All values required
for a figure are supplied explicitly by the caller. This separation makes the
figures easier to test and supports independent reproduction.

The Matplotlib ``Agg`` backend permits figure generation in non-interactive
environments, including Streamlit, automated tests, and reproducibility runs.
"""

from __future__ import annotations

from typing import Optional

import matplotlib

# CODECHECK: select the backend before importing pyplot so the module also works
# in headless and automated environments.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
import numpy as np
from numpy.typing import ArrayLike, NDArray


def _as_finite_2d(values: ArrayLike, name: str) -> NDArray[np.float64]:
    """Return a finite two-dimensional float array.
    """
    array = np.asarray(values, dtype=float)

    if array.ndim != 2:
        raise ValueError(f"{name} must be a two-dimensional array.")
    if array.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values.")

    return array


def _finite_1d(values: ArrayLike, name: str) -> NDArray[np.float64]:
    """Return the finite observations from a one-dimensional representation."""
    array = np.asarray(values, dtype=float).ravel()
    array = array[np.isfinite(array)]

    if array.size == 0:
        raise ValueError(f"{name} contains no finite observations.")

    return array


def _set_trading_day_axis(ax: Axes, trading_days: int) -> None:
    """Apply a common one-based trading-day axis."""
    ax.set_xlim(1, trading_days)
    ax.margins(x=0)


def realized_gamma_halflife(gamma_path: ArrayLike) -> float:
    """Estimate the realized AR(1) half-life of one gamma scenario.

    The simulation is specified for log-gamma, so persistence is estimated from
    ``log(gamma_t)``. The estimator first demeans that path and then estimates
    the no-intercept AR(1) coefficient by ordinary least squares.

    Parameters
    ----------
    gamma_path:
        Positive daily gamma observations for one scenario.

    Returns
    -------
    float
        Estimated half-life in trading days. ``numpy.nan`` is returned when
        there are fewer than three valid observations or when the estimated
        persistence is outside ``0 < phi < 1``.
    """
    path = np.asarray(gamma_path, dtype=float).ravel()
    path = path[np.isfinite(path) & (path > 0.0)]

    if path.size < 3:
        return float("nan")

    log_gamma = np.log(path)
    centered = log_gamma - np.mean(log_gamma)
    lagged = centered[:-1]
    current = centered[1:]

    denominator = float(np.dot(lagged, lagged))
    if denominator <= 0.0:
        return float("nan")

    phi_hat = float(np.dot(lagged, current) / denominator)
    if not 0.0 < phi_hat < 1.0:
        return float("nan")

    return float(np.log(0.5) / np.log(phi_hat))


def routing_paths_figure(
    direct: ArrayLike,
    indirect: ArrayLike,
    threshold: float,
    scenario: int = 0,
    investment_base: float = 100.0,
) -> Figure:
    """Plot direct and indirect routing capacity for one selected scenario."""
    direct_array = _as_finite_2d(direct, "direct")
    indirect_array = _as_finite_2d(indirect, "indirect")

    if direct_array.shape != indirect_array.shape:
        raise ValueError("direct and indirect must have identical shapes.")
    if not 0 <= scenario < direct_array.shape[0]:
        raise IndexError("scenario is outside the available scenario range.")

    x = np.arange(1, direct_array.shape[1] + 1)
    fig, ax = plt.subplots(figsize=(11, 5.8))

    ax.plot(
        x,
        direct_array[scenario],
        label="Network-adjusted direct routing capacity",
        linewidth=2,
    )
    ax.plot(
        x,
        indirect_array[scenario],
        label="Network-adjusted indirect routing capacity",
        linestyle="--",
        alpha=0.75,
    )
    ax.axhline(
        investment_base,
        color="#6b7280",
        linestyle="-.",
        label=f"Investment-base reference ({investment_base:g})",
    )
    ax.axhline(
        threshold,
        color="firebrick",
        linestyle=":",
        label="Liquidity-risk threshold",
    )

    risk = direct_array[scenario] < threshold
    ax.scatter(
        x[risk],
        direct_array[scenario, risk],
        color="firebrick",
        s=22,
        label="Direct-capacity risk day",
    )
    ax.set(
        xlabel="Trading day",
        ylabel="Network-adjusted routing capacity",
        title=f"Routing-capacity paths - scenario {scenario + 1}",
    )
    _set_trading_day_axis(ax, direct_array.shape[1])
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        frameon=False,
        ncol=2,
    )
    fig.subplots_adjust(bottom=0.27)

    return fig


def all_simulation_paths_figure(
    direct: ArrayLike,
    indirect: ArrayLike,
    threshold: float,
    investment_base: float = 100.0,
    max_paths: Optional[int] = None,
) -> Figure:
    """Plot the ensemble of direct and indirect routing-capacity paths."""
    direct_array = _as_finite_2d(direct, "direct")
    indirect_array = _as_finite_2d(indirect, "indirect")

    if direct_array.shape != indirect_array.shape:
        raise ValueError("direct and indirect must have identical shapes.")
    if max_paths is not None and max_paths < 1:
        raise ValueError("max_paths must be positive when supplied.")

    n_scenarios, trading_days = direct_array.shape
    if max_paths is not None and n_scenarios > max_paths:
        # CODECHECK: evenly spaced indices make visual subsampling reproducible.
        ids = np.linspace(0, n_scenarios - 1, max_paths, dtype=int)
    else:
        ids = np.arange(n_scenarios)

    x = np.arange(1, trading_days + 1)
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5), sharex=True)
    alpha = min(0.2, max(0.015, 20 / len(ids)))
    panels = (
        (axes[0], direct_array, "A. Direct network-routing capacity", "#1f77b4"),
        (axes[1], indirect_array, "B. Indirect network-routing capacity", "#ff7f0e"),
    )

    for ax, values, title, color in panels:
        ax.plot(x, values[ids].T, color=color, alpha=alpha, linewidth=0.55)
        ax.plot(
            x,
            np.median(values, axis=0),
            color="black",
            linewidth=2,
            label="Cross-scenario median",
        )
        ax.axhline(
            investment_base,
            color="#6b7280",
            linestyle="-.",
            label=f"Investment-base reference ({investment_base:g})",
        )
        ax.set(
            title=title,
            xlabel="Trading day",
            ylabel="Network-adjusted routing capacity",
        )
        _set_trading_day_axis(ax, trading_days)
        ax.grid(True, linestyle="--", alpha=0.35)

    axes[0].axhline(
        threshold,
        color="firebrick",
        linestyle=":",
        label="Liquidity-risk threshold",
    )
    axes[0].legend(frameon=False, loc="best")
    axes[1].legend(frameon=False, loc="best")
    fig.suptitle(
        f"Simulation ensemble ({len(ids):,} of {n_scenarios:,} paths shown)",
        y=1.02,
    )
    fig.tight_layout()

    return fig


def multiplier_distribution_figure(
    gamma: ArrayLike,
    direct_lm: ArrayLike,
    indirect_lm: ArrayLike,
    risk_quantile_pct: float,
) -> Figure:
    """Plot gamma and direct and indirect routing-multiplier distributions.

    The gamma half-life is estimated separately for each scenario. The median
    across estimable scenarios is reported as a text-only legend entry in panel
    A. Calculating half-life before flattening is essential because flattening
    would incorrectly join the end of one path to the start of the next.
    """
    gamma_array = np.asarray(gamma, dtype=float)
    if gamma_array.ndim == 1:
        gamma_paths = gamma_array.reshape(1, -1)
    elif gamma_array.ndim == 2:
        gamma_paths = gamma_array
    else:
        raise ValueError(
            "gamma must have shape (trading_days,) or "
            "(scenarios, trading_days)."
        )

    if not 0.0 <= risk_quantile_pct <= 100.0:
        raise ValueError("risk_quantile_pct must be between 0 and 100.")

    # estimate persistence scenario by scenario before pooling the
    # observations for the histogram.
    scenario_halflives = np.asarray(
        [realized_gamma_halflife(path) for path in gamma_paths],
        dtype=float,
    )
    valid_halflives = scenario_halflives[np.isfinite(scenario_halflives)]
    median_halflife = (
        float(np.median(valid_halflives))
        if valid_halflives.size > 0
        else float("nan")
    )

    g = _finite_1d(gamma_array, "gamma")
    m = _finite_1d(direct_lm, "direct_lm")
    i = _finite_1d(indirect_lm, "indirect_lm")

    if np.any(g <= 0.0):
        raise ValueError("gamma must contain only positive values.")

    g_mean = float(np.mean(g))
    m_mean = float(np.mean(m))
    i_mean = float(np.mean(i))
    g_std = float(np.std(g))
    direct_quantile = float(np.percentile(m, risk_quantile_pct))

    fig, (ax_left, ax_middle, ax_right) = plt.subplots(
        1,
        3,
        figsize=(17, 3.6),
    )

    # Panel A: realized tail-exponent distribution.
    ax_left.hist(
        g,
        bins=60,
        color="#1f5fa8",
        alpha=0.85,
        edgecolor="white",
        linewidth=0.3,
    )
    ax_left.axvline(
        g_mean,
        color="#27d63e",
        linewidth=2,
        linestyle="--",
        label=f"Mean = {g_mean:.2f}",
    )
    ax_left.axvline(
        g_mean + g_std,
        color="#d62728",
        linewidth=2,
        linestyle="--",
        label=f"Mean + 1 SD = {g_mean + g_std:.2f}",
    )

    halflife_label = (
        f"Median realized half-life = {median_halflife:.2f} days"
        if np.isfinite(median_halflife)
        else "Median realized half-life = not estimable"
    )
    # half-life measures time, whereas the horizontal axis measures
    # gamma. A text-only legend entry is therefore used 
    ax_left.plot([], [], linestyle="none", marker="", label=halflife_label)

    ax_left.set_xlabel("Tail exponent gamma")
    ax_left.set_ylabel("Frequency (scenario-days)")
    ax_left.set_xlim(0, max(5, float(np.max(g)) * 1.05))
    ax_left.set_title("A. Distribution of the tail exponent")
    ax_left.legend(loc="upper right", frameon=False)
    ax_left.grid(axis="y", alpha=0.3)

    # Panel B: direct routing-multiplier distribution.
    ax_middle.hist(
        m,
        bins=60,
        color="#2ca02c",
        alpha=0.85,
        edgecolor="white",
        linewidth=0.3,
    )
    ax_middle.axvline(
        m_mean,
        color="#27d63e",
        linewidth=2,
        linestyle="--",
        label=f"Mean = {m_mean:.2f}x",
    )
    ax_middle.axvline(
        direct_quantile,
        color="#d62728",
        linewidth=2,
        linestyle="--",
        label=(
            f"Risk quantile ({risk_quantile_pct:g}%) "
            f"= {direct_quantile:.2f}x"
        ),
    )
    ax_middle.set_xlabel("Direct routing multiplier E[k]")
    ax_middle.set_ylabel("Frequency (scenario-days)")
    ax_middle.set_title("B. Resulting direct routing multiplier")
    ax_middle.legend(loc="upper right", frameon=False)
    ax_middle.grid(axis="y", alpha=0.3)

    # Panel C: indirect routing-multiplier distribution.
    ax_right.hist(
        i,
        bins=60,
        color="#ff7f0e",
        alpha=0.85,
        edgecolor="white",
        linewidth=0.3,
    )
    ax_right.axvline(
        i_mean,
        color="#27d63e",
        linewidth=2,
        linestyle="--",
        label=f"Mean = {i_mean:.2f}",
    )
    ax_right.set_xlabel("Indirect routing multiplier E[k^2]/E[k] - 1")
    ax_right.set_ylabel("Frequency (scenario-days)")
    ax_right.set_title("C. Resulting indirect routing multiplier")
    ax_right.legend(frameon=False)
    ax_right.grid(axis="y", alpha=0.3)

    fig.suptitle(
        "Realized network state: how the tail-exponent distribution "
        "maps into routing capacity",
        y=1.03,
    )
    fig.tight_layout()

    return fig
