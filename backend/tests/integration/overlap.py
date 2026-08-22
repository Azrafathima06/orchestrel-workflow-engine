"""Mechanical interval-overlap detection for parallelism evidence.

Used instead of eyeballing timestamps: two tasks ran concurrently if and
only if their [started_at, finished_at] intervals intersect.
"""

from __future__ import annotations

from datetime import datetime


def intervals_overlap(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """True if [a_start, a_end] and [b_start, b_end] intersect.

    Strict inequality on both sides: intervals that merely touch at an
    endpoint are not treated as concurrent execution.
    """
    return a_start < b_end and b_start < a_end


def count_overlapping_pairs(intervals: list[tuple[str, datetime, datetime]]) -> int:
    """Number of distinct pairs whose execution intervals intersect."""
    pairs = 0
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            _, a_start, a_end = intervals[i]
            _, b_start, b_end = intervals[j]
            if intervals_overlap(a_start, a_end, b_start, b_end):
                pairs += 1
    return pairs


def overlapping_pair_labels(
    intervals: list[tuple[str, datetime, datetime]],
) -> list[tuple[str, str]]:
    """Labels of every overlapping pair, for reporting."""
    result: list[tuple[str, str]] = []
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            a_label, a_start, a_end = intervals[i]
            b_label, b_start, b_end = intervals[j]
            if intervals_overlap(a_start, a_end, b_start, b_end):
                result.append((a_label, b_label))
    return result
