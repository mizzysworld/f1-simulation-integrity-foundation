"""Deterministic FIA B2.5.5 settlement for the bounded verified subset."""

from __future__ import annotations

import math

from f1sim.schemas import (
    ClassificationEntry,
    ClassificationStatus,
    DeterministicRaceStory,
    NoPositionReason,
    OfficialClassification,
    Penalty,
    RegulatoryDisposition,
    StartStatus,
)
from f1sim.schemas.models import RaceStoryEntry


def _current_penalty(entry: RaceStoryEntry) -> Penalty | None:
    penalties = [penalty for penalty in entry.penalties if penalty.affects_current_race]
    return penalties[0] if penalties else None


def _is_disqualified(entry: RaceStoryEntry) -> bool:
    penalty = _current_penalty(entry)
    return penalty is not None and penalty.penalty_type == "official_disqualification"


def _validate_order(entries: list[RaceStoryEntry]) -> None:
    groups: dict[int, list[RaceStoryEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.complete_laps, []).append(entry)
    for laps, group in groups.items():
        requires_evidence = len(group) > 1 or laps == 0
        orders = [entry.same_lap_crossing_order for entry in group]
        if requires_evidence and any(order is None for order in orders):
            if laps == 0:
                raise ValueError(
                    "zero-lap physical starters require authoritative group-local order; "
                    "unsupported evidence fails closed"
                )
            raise ValueError("complete group-local Line-crossing order is required for tied laps")
        concrete = [order for order in orders if order is not None]
        if concrete and sorted(concrete) != list(range(1, len(group) + 1)):
            raise ValueError(
                "Line-crossing order must be unique and contiguous within each complete-laps group"
            )


def _ordered(entries: list[RaceStoryEntry]) -> list[RaceStoryEntry]:
    """Order by complete laps then official Line-crossing evidence, with one bounded penalty."""
    ordered = sorted(
        entries,
        key=lambda entry: (-entry.complete_laps, entry.same_lap_crossing_order or 0),
    )
    penalized = [
        entry
        for entry in ordered
        if (penalty := _current_penalty(entry)) is not None
        and penalty.penalty_type == "elapsed_time"
    ]
    if len(penalized) > 1:
        raise ValueError("unsupported elapsed-time penalty combination")
    if not penalized:
        return ordered

    affected = penalized[0]
    group = [entry for entry in ordered if entry.complete_laps == affected.complete_laps]
    present = [entry.elapsed_seconds is not None for entry in group]
    if not all(present):
        raise ValueError("elapsed timing must be complete for the affected same-lap group")
    penalty = _current_penalty(affected)
    assert penalty is not None and penalty.seconds is not None
    penalty_seconds = penalty.seconds

    def adjusted(entry: RaceStoryEntry) -> float:
        assert entry.elapsed_seconds is not None
        return entry.elapsed_seconds + (penalty_seconds if entry is affected else 0.0)

    reordered = sorted(
        group,
        key=lambda entry: (adjusted(entry), entry.same_lap_crossing_order or 0),
    )
    iterator = iter(reordered)
    return [
        next(iterator) if entry.complete_laps == affected.complete_laps else entry
        for entry in ordered
    ]


def settle(story: DeterministicRaceStory) -> OfficialClassification:
    """Settle one complete deterministic story; no generalized sanction precedence."""
    active = [entry for entry in story.entries if entry.start_status != StartStatus.DNS]
    if not active:
        raise ValueError("settlement requires at least one physical starter")
    _validate_order(active)
    winner_laps = story.official_winner_laps
    threshold = math.floor(0.9 * winner_laps)

    classified = [entry for entry in active if entry.complete_laps >= threshold]
    classified = [entry for entry in _ordered(classified) if not _is_disqualified(entry)]
    position_by_id = {entry.entrant_id: index for index, entry in enumerate(classified, 1)}

    result: list[ClassificationEntry] = []
    for entry in story.entries:
        if _is_disqualified(entry):
            status = ClassificationStatus.DISQUALIFIED
            position = None
            reason = NoPositionReason.DISQUALIFIED
            disposition = RegulatoryDisposition.DISQUALIFIED
        elif entry.start_status == StartStatus.DNS:
            status = ClassificationStatus.UNCLASSIFIED
            position = None
            reason = NoPositionReason.DNS
            disposition = RegulatoryDisposition.VALID
        elif entry.complete_laps < threshold:
            status = ClassificationStatus.UNCLASSIFIED
            position = None
            reason = NoPositionReason.UNCLASSIFIED
            disposition = (
                RegulatoryDisposition.PENALIZED
                if _current_penalty(entry) is not None
                else RegulatoryDisposition.VALID
            )
        else:
            status = ClassificationStatus.CLASSIFIED
            position = position_by_id[entry.entrant_id]
            reason = None
            disposition = (
                RegulatoryDisposition.PENALIZED
                if _current_penalty(entry) is not None
                else RegulatoryDisposition.VALID
            )
        result.append(
            ClassificationEntry(
                entrant_id=entry.entrant_id,
                start_status=entry.start_status,
                terminal_physical_status=entry.terminal_physical_status,
                classification_status=status,
                official_position=position,
                no_position_reason=reason,
                final_regulatory_disposition=disposition,
                complete_laps=entry.complete_laps,
                penalties=entry.penalties,
            )
        )
    return OfficialClassification(
        event_id=story.event.event_id,
        ruleset_id=story.event.ruleset.ruleset_id,
        field_size=len(story.event.entrants),
        winner_laps=winner_laps,
        classification_threshold_laps=threshold,
        entries=tuple(result),
    )
