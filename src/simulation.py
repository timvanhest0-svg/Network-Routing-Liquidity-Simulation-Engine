"""
simulation.py - Baseline network-routing liquidity paths.

This module generates the mean-reverting Monte-Carlo baseline for the routing-liquidity
engine. It simulates a strictly positive network tail exponent, maps each
simulated topology into direct and indirect routing multipliers, and flags
liquidity-risk days.

Gamma inputs and log-gamma simulation
-------------------------------------
The application asks users for intuitive parameters on the original gamma
scale:

- ``mu``: desired long-run arithmetic mean of gamma;
- ``sigma``: desired long-run standard deviation of gamma;
- ``halftime``: assumed half-life of a topology shock in trading days.

The stochastic process itself is specified for:

    x_t = log(gamma_t).

Before simulation, ``mu`` and ``sigma`` are converted into the parameters of
the corresponding stationary lognormal distribution:

    sigma_x^2 = log(1 + sigma^2 / mu^2)
    mu_x      = log(mu) - 0.5 * sigma_x^2

These transformations ensure that, before any topology-grid clipping,
``exp(x_t)`` has the requested long-run arithmetic mean ``mu`` and standard
deviation ``sigma``.

Mean-reverting process (Equation 8.1)
-------------------------------------
Log-gamma follows the first-order mean-reverting process:

    x_t = mu_x + rho * (x_(t-1) - mu_x) + sigma_eta_x * epsilon_t,
    epsilon_t ~ N(0, 1).

Memory is expressed through a half-life in trading days:

    rho = 0.5 ** (1 / halftime).

A half-life of zero gives the no-memory case, ``rho = 0``. For a selected
memory parameter, daily innovation volatility is:

    sigma_eta_x = sigma_x * sqrt(1 - rho^2).

Consequently, every memory scenario retains the same stationary log-gamma
variance and therefore the same long-run gamma distribution. Scenarios differ
only in the persistence of topology shocks.

Finally, the simulated state is transformed back to the original scale:

    gamma_t = exp(x_t).

The exponential transformation guarantees ``gamma_t > 0`` without flooring
negative draws or creating an artificial probability mass at zero.

Configuration (SimulationConfig)
--------------------------------
- n_nodes           : number of intermediary nodes.
- scenarios         : number of Monte-Carlo paths.
- trading_days      : path length in trading-day steps.
- investment        : base liquidity routed per period.
- buffer_normal_pct : normal-times liquidity buffer withheld from routing.
- liquidity_risk_q  : lower-tail risk quantile in percentage points.
- seed              : random-number seed.
- mu                : desired long-run arithmetic mean of gamma.
- sigma             : desired long-run standard deviation of gamma.
- halftime          : assumed half-life of a topology shock in trading days.

app.py integration
------------------
The Streamlit application supplies the intuitive gamma-scale inputs:

    config = SimulationConfig(
        mu=float(s.mu),
        sigma=float(s.sigma),
        halftime=float(s.halftime),
        # plus the remaining application settings
    )

Returns
-------
A dictionary containing log-gamma and gamma paths, routing multipliers and
liquidity paths, the risk threshold, the risk-day mask, baseline available
liquidity, the original gamma-scale inputs, and the derived log-scale and
memory parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .topology import make_multiplier_grids


@dataclass(frozen=True)
class SimulationConfig:
    """Complete and reproducible configuration for one baseline run."""

    n_nodes: int = 24
    scenarios: int = 1_000
    trading_days: int = 200

    investment: float = 100.0
    buffer_normal_pct: float = 40.0
    liquidity_risk_q: float = 2.5
    seed: int = 42

    # User-facing parameters on the original gamma scale.
    # Defaults use all 750 positive observations in the 2010-2014 window.
    mu: float = 1.15732
    sigma: float = 0.5381096234868743

    # Behavioural scenario assumption, not an econometric estimate.
    # Set to 0 for no memory; examples: 10 for moderate and 20 for longer memory.
    halftime: float = 10.0


def _gamma_to_log_parameters(mu: float, sigma: float) -> tuple[float, float]:
    """Convert gamma-scale moments to stationary log-gamma parameters.

    Parameters
    ----------
    mu:
        Desired arithmetic mean of gamma, E[gamma].
    sigma:
        Desired standard deviation of gamma, SD[gamma].

    Returns
    -------
    mu_x:
        Stationary mean of x = log(gamma).
    sigma_x:
        Stationary standard deviation of x = log(gamma).

    Notes
    -----
    The conversion assumes that stationary gamma is lognormally distributed.
    It exactly matches the requested first two moments before multiplier-grid
    clipping.
    """

    if mu <= 0 or sigma <= 0:
        raise ValueError("mu and sigma must be positive")

    sigma_x_sq = np.log1p((sigma / mu) ** 2)
    sigma_x = np.sqrt(sigma_x_sq)
    mu_x = np.log(mu) - 0.5 * sigma_x_sq
    return float(mu_x), float(sigma_x)


def _memory_parameters(
    halftime: float,
    sigma_x: float,
) -> tuple[float, float]:
    """Return daily memory rho and log-scale innovation volatility."""

    if halftime < 0:
        raise ValueError("halftime must be non-negative")

    rho = 0.0 if halftime == 0 else 0.5 ** (1.0 / halftime)

    # Preserve the configured stationary log-gamma standard deviation under
    # every memory assumption.
    sigma_eta_x = sigma_x * np.sqrt(1.0 - rho**2)
    return float(rho), float(sigma_eta_x)


def _simulate_gamma_paths(
    c: SimulationConfig,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, float, float, float, float]:
    """Simulate Equation 8.1 for log-gamma and transform back to gamma."""

    mu_x, sigma_x = _gamma_to_log_parameters(c.mu, c.sigma)
    rho, sigma_eta_x = _memory_parameters(c.halftime, sigma_x)

    x = np.empty((c.scenarios, c.trading_days), dtype=float)

    # Draw the first day from the stationary log-gamma distribution. This gives
    # day 1 the same unconditional distribution as every later simulation day.
    x[:, 0] = rng.normal(
        loc=mu_x,
        scale=sigma_x,
        size=c.scenarios,
    )

    shocks = rng.standard_normal((c.scenarios, c.trading_days - 1))

    for day in range(1, c.trading_days):
        x[:, day] = (
            mu_x
            + rho * (x[:, day - 1] - mu_x)
            + sigma_eta_x * shocks[:, day - 1]
        )

    # Exponentiation guarantees strictly positive tail exponents.
    gamma = np.exp(x)

    return gamma, x, rho, sigma_eta_x, mu_x, sigma_x


def simulate_base_paths(c: SimulationConfig) -> dict[str, np.ndarray | float]:
    """Generate baseline topology and routing-liquidity Monte-Carlo paths."""

    if c.n_nodes < 2 or c.scenarios < 1 or c.trading_days < 2:
        raise ValueError("invalid dimensions")
    if c.investment <= 0 or not 0 <= c.buffer_normal_pct < 100:
        raise ValueError("invalid liquidity settings")
    if not 0 < c.liquidity_risk_q < 100:
        raise ValueError("liquidity_risk_q must be in percentage points (0, 100)")
    if c.mu <= 0 or c.sigma <= 0:
        raise ValueError("mu and sigma must be positive")
    if c.halftime < 0:
        raise ValueError("halftime must be non-negative")

    rng = np.random.default_rng(c.seed)
    gamma, log_gamma, rho, sigma_eta_x, mu_x, sigma_x = (
        _simulate_gamma_paths(c, rng)
    )

    # Map simulated gamma to precomputed topology multiplier grids. Clipping is
    # retained only for interpolation safety; gamma itself is not overwritten.
    grid, direct_grid, indirect_grid = make_multiplier_grids(c.n_nodes)
    gamma_clipped = np.clip(gamma, grid[0], grid[-1])
    direct_lm = np.interp(gamma_clipped, grid, direct_grid)
    indirect_lm = np.interp(gamma_clipped, grid, indirect_grid)

    # Report clipping frequencies so grid-boundary effects remain transparent.
    below_grid = gamma < grid[0]
    above_grid = gamma > grid[-1]
    gamma_grid_clip_pct = float(
        np.mean(below_grid | above_grid) * 100.0
    )

    # Scale routing multipliers by available baseline liquidity.
    baseline_available = c.investment * (1.0 - c.buffer_normal_pct / 100.0)
    direct_liquidity = baseline_available * direct_lm
    indirect_liquidity = baseline_available * indirect_lm

    # liquidity_risk_q is expressed in percentage points, e.g. 2.5 means 2.5%.
    risk_threshold = float(
        np.quantile(direct_liquidity, c.liquidity_risk_q / 100.0)
    )
    event_day = direct_liquidity < risk_threshold

    return {
        "log_gamma": log_gamma,
        "gamma": gamma,
        "gamma_clipped_for_grid": gamma_clipped,
        "direct_lm": direct_lm,
        "indirect_lm": indirect_lm,
        "direct_liquidity": direct_liquidity,
        "indirect_liquidity": indirect_liquidity,
        "risk_threshold": risk_threshold,
        "event_day": event_day,
        "baseline_available": float(baseline_available),
        # Original user-facing gamma-scale parameters.
        "gamma_mean": float(c.mu),
        "gamma_long_run_std": float(c.sigma),
        "memory_half_life_days": float(c.halftime),
        # Derived parameters used internally in Equation 8.1.
        "log_gamma_mean": mu_x,
        "log_gamma_long_run_std": sigma_x,
        "memory_rho": rho,
        "log_gamma_innovation_sigma": sigma_eta_x,
        # Interpolation diagnostics.
        "gamma_below_grid_pct": float(np.mean(below_grid) * 100.0),
        "gamma_above_grid_pct": float(np.mean(above_grid) * 100.0),
        "gamma_grid_clip_pct": gamma_grid_clip_pct,
    }
