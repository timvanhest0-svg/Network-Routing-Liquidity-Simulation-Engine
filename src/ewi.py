"""
ewi.py - Controlled early-warning indicator for simulation experiments.

Purpose
-------
This module creates an early-warning signal with a controlled recall,
precision, and lead time. It does not estimate an indicator from historical
predictors. Instead, it generates a reproducible signal whose statistical
quality is specified by the user. This allows the policy simulation to test
how a warning system with a given level of performance would affect liquidity
buffers or other preventive interventions.

The input ``events`` is a two-dimensional Boolean array with shape
``(scenarios, trading_days)``. A value of ``True`` identifies a liquidity-risk
day in a particular Monte-Carlo path.

Definitions
-----------
Lead time
    Number of trading days between an early-warning signal and the risk day it
    is intended to predict. With ``lead_time=5``, a signal on day t predicts an
    event on day t+5.

Recall
    Share of evaluable event days that receive an advance signal:

        recall = correctly signalled event days / evaluable event days.

Precision
    Share of all signal days that correctly predict a later risk day:

        precision = correct signal days / all signal days.

The final ``lead_time`` days of every path cannot contain evaluable signals,
because there are not enough future observations to determine whether such a
signal would be correct.

Method
------
1. Identify all event days that have a valid signal date exactly ``lead_time``
   days earlier.
2. Randomly select the requested share of those events according to
   ``target_recall`` and place a true-positive signal on the corresponding
   earlier date.
3. Calculate the total number of signals required to approximate
   ``target_precision``.
4. Add false-positive signals on eligible dates that do not predict an event
   exactly ``lead_time`` days later.
5. Return the Boolean signal array and a summary of target and realized
   performance.

Because integer counts must be used, the realized recall and precision may
vary slightly from their targets, especially in small samples. The random seed
makes the selected signal dates fully reproducible.

Important interpretation
------------------------
This is a simulation device, not an empirically fitted forecasting model. The
specified recall and precision should therefore be interpreted as scenario
assumptions used to evaluate the value of advance information.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class EWIConfig:
    """Configuration of the synthetic early-warning indicator.

    Parameters
    ----------
    target_recall:
        Desired fraction of evaluable risk events that receive a correct
        advance signal. Must lie in the interval [0, 1].
    target_precision:
        Desired fraction of all generated signals that correctly predict an
        event. Must lie in the interval (0, 1].
    lead_time:
        Number of trading days between the signal and the predicted event.
    seed:
        Seed used for reproducible selection of true- and false-positive days.
    """

    target_recall: float = 0.70
    target_precision: float = 0.25
    lead_time: int = 5
    seed: int = 42


def future_event_mask(events: np.ndarray, lead: int) -> np.ndarray:
    """Align future events with the dates on which signals would be issued.

    If an event occurs on day ``t + lead``, the returned mask is ``True`` on
    day ``t``. For example, with a five-day lead, an event on day 20 appears as
    a future event on signal day 15.

    The final ``lead`` columns remain ``False`` because no event exactly
    ``lead`` days ahead is observable within the simulated path.
    """

    out = np.zeros_like(events, dtype=bool)
    out[:, :-lead] = events[:, lead:]
    return out


def detected_event_mask(
    events: np.ndarray,
    flags: np.ndarray,
    lead: int,
) -> np.ndarray:
    """Return event days correctly preceded by a signal at the chosen lead.

    The returned array is aligned with the event date, not the signal date.
    An entry is ``True`` on day ``t`` only when an event occurs on day ``t``
    and a warning flag was present on day ``t - lead``.
    """

    out = np.zeros_like(events, dtype=bool)
    out[:, lead:] = events[:, lead:] & flags[:, :-lead]
    return out


def create_ewi(
    events: np.ndarray,
    c: EWIConfig,
) -> tuple[np.ndarray, dict[str, int | float]]:
    """Create a reproducible synthetic early-warning signal.

    Parameters
    ----------
    events:
        Two-dimensional Boolean array of shape ``(scenarios, trading_days)``.
        ``True`` identifies a liquidity-risk day.
    c:
        Early-warning configuration.

    Returns
    -------
    flags:
        Boolean array with the same shape as ``events``. ``True`` indicates
        that the early-warning indicator is active on that day.
    metrics:
        Dictionary containing event counts and target and realized recall and
        precision percentages.

    Notes
    -----
    A warning predicts an event exactly ``lead_time`` days later. The function
    does not define a broader prediction window. Consecutive risk days are
    therefore treated as separate event-day observations.
    """

    events = np.asarray(events, dtype=bool)

    if events.ndim != 2:
        raise ValueError("events must be a 2D array: scenarios x trading days")
    if not 0.0 <= c.target_recall <= 1.0:
        raise ValueError("target_recall must be between 0 and 1")
    if not 0.0 < c.target_precision <= 1.0:
        raise ValueError("target_precision must be greater than 0 and at most 1")
    if not 1 <= c.lead_time < events.shape[1]:
        raise ValueError("lead_time must be at least 1 and shorter than the path")

    rng = np.random.default_rng(c.seed)

    # Event days in the first lead_time columns are not evaluable because a
    # warning cannot be placed before the start of the simulated path.
    event_positions = np.argwhere(events[:, c.lead_time:])
    if len(event_positions):
        event_positions[:, 1] += c.lead_time

    n_events = len(event_positions)

    # Select the number of event days required by the recall assumption.
    n_true_signals = min(n_events, round(c.target_recall * n_events))
    if n_true_signals:
        selected_events = event_positions[
            rng.choice(n_events, size=n_true_signals, replace=False)
        ]
    else:
        selected_events = np.empty((0, 2), dtype=int)

    flags = np.zeros_like(events, dtype=bool)

    # Place every correct signal exactly lead_time days before its event.
    if n_true_signals:
        flags[
            selected_events[:, 0],
            selected_events[:, 1] - c.lead_time,
        ] = True

    # Precision = true signals / total signals. Rearranging gives the total
    # number of signal days needed for the requested precision.
    desired_total_signals = (
        round(n_true_signals / c.target_precision)
        if n_true_signals
        else 0
    )

    # A false-positive signal must be placed early enough to be evaluated and
    # must not predict an event exactly lead_time days later.
    eligible = np.ones_like(events, dtype=bool)
    eligible[:, -c.lead_time:] = False

    false_positive_candidates = np.argwhere(
        eligible
        & ~flags
        & ~future_event_mask(events, c.lead_time)
    )

    n_false_signals = min(
        max(0, desired_total_signals - n_true_signals),
        len(false_positive_candidates),
    )

    if n_false_signals:
        selected_false_positives = false_positive_candidates[
            rng.choice(
                len(false_positive_candidates),
                size=n_false_signals,
                replace=False,
            )
        ]
        flags[
            selected_false_positives[:, 0],
            selected_false_positives[:, 1],
        ] = True

    # Recalculate realized performance from the completed signal array rather
    # than assuming that rounded target counts were attained exactly.
    detected = detected_event_mask(events, flags, c.lead_time)
    n_detected = int(detected.sum())
    n_signals = int(flags.sum())

    metrics = {
        "evaluable_event_days": n_events,
        "true_positive_signal_days": n_detected,
        "false_positive_signal_days": n_signals - n_detected,
        "total_signal_days": n_signals,
        "target_recall_pct": c.target_recall * 100.0,
        "realized_recall_pct": (
            n_detected / n_events * 100.0 if n_events else np.nan
        ),
        "target_precision_pct": c.target_precision * 100.0,
        "realized_precision_pct": (
            n_detected / n_signals * 100.0 if n_signals else np.nan
        ),
    }

    return flags, metrics

