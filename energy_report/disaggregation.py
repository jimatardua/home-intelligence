"""Splits each hour's whole-house usage into A/C, EV charging, and "other."

Neither A/C nor EV charging is separately metered -- both are estimated from
indirect signals (on/off timing for A/C, instantaneous charger power for
EVs) and subtracted from the real whole-house RMP reading. "Other/baseline"
is deliberately a residual, not a separately-measured category: whenever
A/C or EV data has a gap (sensor unknown/unavailable), that stretch's
energy falls into "other" by default rather than being guessed at. This is
the correct conservative behavior, not a bug -- "other" always means
"not confidently attributed," which includes both genuine baseline load
(lighting, refrigeration, etc.) and any mis-attribution during a data gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .ha_recorder import NumericSample, OnOffInterval

# Lennox XC14-060 nameplate: compressor RLA 26.4A + fan FLA 1.8A = 28.2A at
# 230V x ~0.9 assumed power factor. Nameplate-derived, not measured -- see
# docs/tou-report.md for the derivation and why this was chosen over
# statistical estimation from usage spikes.
AC_ESTIMATED_KW = 5.8


@dataclass(frozen=True)
class HourDisaggregation:
    hour_start: datetime
    total_kwh: float | None  # None if RMP itself has no reading for this hour
    ac_kwh: float
    ev_kwh: dict[str, float]  # per car name/entity, e.g. {"jim": 0.4, "irina": 0.0}
    other_kwh: float | None  # None if total_kwh is None (nothing to subtract from)
    negative_other_flag: bool  # True if ac+ev estimate exceeded total_kwh (clamped to 0)


def _overlap_hours(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    """Overlap between two time spans, in hours (0 if no overlap)."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max((end - start).total_seconds() / 3600.0, 0.0)


def ac_kwh_for_hour(
    intervals: list[OnOffInterval], hour_start: datetime, ac_kw: float = AC_ESTIMATED_KW
) -> float:
    """A/C energy for [hour_start, hour_start+1h) from on/off intervals."""
    hour_end = hour_start + timedelta(hours=1)
    on_hours = sum(
        _overlap_hours(iv.start_local, iv.end_local, hour_start, hour_end)
        for iv in intervals
        if iv.is_on
    )
    return on_hours * ac_kw


def _global_step_segments(
    samples: list[NumericSample],
) -> list[tuple[datetime, datetime, float | None]]:
    """Step-held (zero-order-hold) segments spanning the *entire* sample list.

    A sample's value is assumed to hold from its own timestamp until the
    next sample -- built once across all samples (not per-hour), so a
    value that started well before an hour of interest correctly carries
    into it; only clipped to a specific hour later, at integration time.

    Before the very first sample and after the very last, there is simply
    no segment at all -- that time is unknown, not guessed at. A sample
    whose own value is None (the state itself was unknown/unavailable)
    produces a None segment, which contributes nothing when integrated.
    This is a deliberate conservative simplification (real power can also
    change *between* samples, e.g. mid-charge current ramping; this tool
    doesn't attempt linear interpolation given how sparse real samples are).
    """
    return [(s.at_local, nxt.at_local, s.value) for s, nxt in zip(samples, samples[1:])]


def ev_kwh_for_hour(samples: list[NumericSample], hour_start: datetime) -> float:
    """EV charger energy for [hour_start, hour_start+1h) from power samples."""
    hour_end = hour_start + timedelta(hours=1)
    total = 0.0
    for seg_start, seg_end, kw in _global_step_segments(samples):
        if kw is None:
            continue
        total += kw * _overlap_hours(seg_start, seg_end, hour_start, hour_end)
    return total


def disaggregate_hour(
    hour_start: datetime,
    total_kwh: float | None,
    ac_intervals: list[OnOffInterval],
    ev_samples_by_car: dict[str, list[NumericSample]],
) -> HourDisaggregation:
    ac_kwh = ac_kwh_for_hour(ac_intervals, hour_start)
    ev_kwh = {car: ev_kwh_for_hour(samples, hour_start) for car, samples in ev_samples_by_car.items()}

    if total_kwh is None:
        return HourDisaggregation(
            hour_start=hour_start,
            total_kwh=None,
            ac_kwh=ac_kwh,
            ev_kwh=ev_kwh,
            other_kwh=None,
            negative_other_flag=False,
        )

    accounted = ac_kwh + sum(ev_kwh.values())
    other_kwh = total_kwh - accounted
    negative_flag = other_kwh < 0
    if negative_flag:
        other_kwh = 0.0

    return HourDisaggregation(
        hour_start=hour_start,
        total_kwh=total_kwh,
        ac_kwh=ac_kwh,
        ev_kwh=ev_kwh,
        other_kwh=other_kwh,
        negative_other_flag=negative_flag,
    )
