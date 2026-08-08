"""
policy.py — EWI-triggered liquidity-support policies and the equal-spend benchmark.

This module sits on top of the baseline simulation (simulation.py) and answers the
engine's headline question: at the same total spend, does support *targeted* by an
early-warning indicator (EWI) reduce routing-capacity shortfalls more than *untargeted*
(random) support? It builds the policy runs that feed the Mitigation-comparison page.

Support design
--------------
On an active support day, liquidity is delivered through two economically additive
channels (see PolicyConfig):
  * buffer_release_pct - self-funded liquidity: percentage points of the *normal*
                         buffer released back into routing.
  * injection_pct      - external central-bank liquidity added on top.
Both enter as extra *base* liquidity that is then network-scaled by the routing
multiplier (dm = E[k]). The engine therefore drives the simulation with their sum,
the combined liquidity-support level. This is the mechanism behind the intervention
asymmetry: because support is scaled by the multiplier, a fixed injection reaches
fewer routes when the multiplier is low — i.e. weakest exactly on risk days.

Timing
------
forward_active_mask() turns EWI risk flags into an active-support window: support
starts start_delay days after a signal and lasts support_days, propagated forward
along each scenario path. This captures realistic activation lag and a finite
support duration rather than instantaneous, permanent support.

Equal-spend comparison
----------------------
The targeted vs. random comparison is only meaningful if both spend the same volume.
random_active_mask_same_volume() places the *same number* of active support days as
the targeted policy, but at random positions. run_random_benchmarks() repeats this
over many replications; the app reports the median. Any difference in outcomes is
therefore attributable to *targeting*, not to spending more.

Relative shortfall
------------------
run_policy() and run_random_benchmarks() accept total_available — total routing
liquidity available, i.e. the sum of baseline direct routing liquidity across all
scenario-days. When supplied, results include shortfall_pct: the cumulative
routing-capacity shortfall as a share of available routing liquidity. This makes the
shortfall scale-invariant (comparable across investment base, scenario count, and
horizon) for the metric tiles and Panel C. The absolute total_shortfall is retained
alongside it as the audit figure.


Key functions
-------------
  PolicyConfig                     : support-policy parameters and validation.
  forward_active_mask              : EWI flags -> active-support window (delay + duration).
  run_policy                       : one policy run; returns liquidity path, metrics,
                                     extras (incl. shortfall_pct), and realized support.
  support_split                    : split realized support into buffer vs. injection volume.
  random_active_mask_same_volume   : equal-volume random support mask.
  run_random_benchmarks            : median random-support benchmark over replications.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np, pandas as pd
from .metrics import evaluate_liquidity, policy_extras


@dataclass(frozen=True)
class PolicyConfig:
    """Liquidity-support policy parameters and validation."""
    buffer_release_pct: float = 5.; injection_pct: float = 5.; support_days: int = 10; start_delay: int = 5

    @property
    def combined_support_pct(self) -> float:
        return float(self.buffer_release_pct + self.injection_pct)

    def validate(self, buffer_normal_pct: float) -> None:
        if self.buffer_release_pct < 0 or self.injection_pct < 0:
            raise ValueError("support percentages must be non-negative")
        if self.buffer_release_pct > buffer_normal_pct:
            raise ValueError("buffer release cannot exceed the normal buffer")


def forward_active_mask(flags, duration, start_delay):
    """Turn EWI risk flags into an active-support window (delay + duration)."""
    if duration < 1 or start_delay < 1:
        raise ValueError("duration and delay must be positive")
    f = np.asarray(flags, bool); out = np.zeros_like(f); t = f.shape[1]
    for off in range(start_delay, start_delay + duration):
        if off < t:
            out[:, off:] |= f[:, :t - off]
    return out



def event_delayed_active_mask(event_day, duration, start_delay):
    """Reactive rule: start support a fixed delay after each realized event day."""
    return forward_active_mask(event_day, duration, start_delay)


def oracle_active_mask_same_volume(direct_liquidity, threshold, ref):
    """Ex-post perfect-information ceiling with the same active-day count as ref."""
    liquidity = np.asarray(direct_liquidity, dtype=float)
    reference = np.asarray(ref, dtype=bool)
    if liquidity.shape != reference.shape:
        raise ValueError("direct_liquidity and ref must have the same shape")
    out = np.zeros_like(reference, dtype=bool)
    n = int(reference.sum())
    if n:
        order = np.argsort(liquidity, axis=None, kind="stable")
        out.flat[order[:n]] = True
    return out

def run_policy(dm, threshold, base, investment, buffer_pct, mask, support_pct, total_available=None):
    """Run one policy configuration.

    When total_available is provided, extras include 'shortfall_pct' — the cumulative
    routing-capacity shortfall as a share of available routing liquidity.
    """
    available = investment * (1 - buffer_pct / 100)
    support = investment * support_pct / 100 * np.asarray(mask, bool)
    liq = (available + support) * dm
    met = evaluate_liquidity(liq, threshold)
    extras = policy_extras(base, met, support, available)
    # Relative shortfall against total routing liquidity available.
    if total_available is not None and total_available > 0:
        extras['shortfall_pct'] = float(extras['total_shortfall'] / total_available * 100)
    else:
        extras['shortfall_pct'] = float('nan')
    return liq, met, extras, support


def support_split(investment, buffer_release_pct, injection_pct, active_days):
    """Split total realized support volume into its two channels (proportional)."""
    br = investment * buffer_release_pct / 100 * active_days
    inj = investment * injection_pct / 100 * active_days
    return {'buffer_release_volume': float(br), 'injection_volume': float(inj),
            'combined_support_volume': float(br + inj)}


def random_active_mask_same_volume(ref, rng):
    """Equal-volume random support mask: same active-day count as ref, random positions."""
    out = np.zeros_like(ref, bool); n = int(np.asarray(ref, bool).sum())
    if n:
        out.flat[rng.choice(out.size, n, False)] = True
    return out


def run_random_benchmarks(dm, threshold, base, investment, buffer_pct, ref, support_pct,
                          replications=500, seed=1042, total_available=None):
    """Randomized-timing equal-volume benchmark over replications."""
    rng = np.random.default_rng(seed); rows = []
    for i in range(replications):
        mask = random_active_mask_same_volume(ref, rng)
        _, m, x, _ = run_policy(dm, threshold, base, investment, buffer_pct, mask, support_pct,
                                total_available=total_available)
        rows.append({'replication': i + 1, **m, **x})
    return pd.DataFrame(rows)