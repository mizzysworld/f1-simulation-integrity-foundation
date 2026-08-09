from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from f1sim.schemas import (
    ClassificationEntry,
    ClassificationStatus,
    DeterministicRaceStory,
    Event,
    NoPositionReason,
    OfficialClassification,
    Penalty,
    PhysicalStatus,
    RaceStoryEntry,
    RegulatoryDisposition,
    StartStatus,
)
from f1sim.settlement import settle

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def penalty(kind: str = "elapsed_time", *, seconds: float | None = 5) -> Penalty:
    return Penalty(
        penalty_id=f"p-{kind}",
        penalty_type=kind,
        seconds=seconds,
        reason="synthetic evidence",
        issued_at=NOW,
        applied_order=1,
        affects_current_race=True,
        official_document="fia-decision-synthetic.pdf",
    )


def entry(
    entrant_id: str,
    laps: int,
    order: int | None,
    *,
    retired: bool = False,
    dns: bool = False,
    elapsed: float | None = None,
    penalties: tuple[Penalty, ...] = (),
) -> RaceStoryEntry:
    return RaceStoryEntry(
        entrant_id=entrant_id,
        start_status=StartStatus.DNS if dns else StartStatus.GRID_START,
        terminal_physical_status=(
            PhysicalStatus.DID_NOT_START
            if dns
            else PhysicalStatus.RETIRED
            if retired
            else PhysicalStatus.RUNNING
        ),
        complete_laps=laps,
        same_lap_crossing_order=order,
        elapsed_seconds=elapsed,
        penalties=penalties,
    )


def story(
    event: Event, entries: tuple[RaceStoryEntry, ...], winner_laps: int = 10
) -> DeterministicRaceStory:
    return DeterministicRaceStory(event=event, entries=entries, official_winner_laps=winner_laps)


def by_id(result: OfficialClassification) -> dict[str, ClassificationEntry]:
    return {item.entrant_id: item for item in result.entries}


def test_running_retirement_threshold_and_line_crossing_order(toy_event: Event) -> None:
    result = settle(
        story(
            toy_event,
            (
                entry("car-1", 10, 2, elapsed=100),
                entry("car-2", 10, 1, elapsed=90),
                entry("car-3", 9, 1, retired=True),
                entry("car-4", 9, 2, retired=True),
                entry("car-5", 8, 1, retired=True),
            ),
        )
    )
    rows = by_id(result)
    assert result.classification_threshold_laps == 9
    assert rows["car-2"].official_position == 1  # elapsed time cannot override Line crossing
    assert rows["car-3"].official_position == 3
    assert rows["car-5"].classification_status == ClassificationStatus.UNCLASSIFIED


def test_known_dns_and_evidence_backed_official_disqualification(toy_event: Event) -> None:
    data = toy_event.model_dump()
    data["entrants"][4].update(assumed_start_location="known_dns", grid_position=None)
    event = Event.model_validate(data)
    result = settle(
        story(
            event,
            (
                entry("car-1", 10, 1),
                entry(
                    "car-2", 10, 2, penalties=(penalty("official_disqualification", seconds=None),)
                ),
                entry("car-3", 10, 3),
                entry("car-4", 9, 1, retired=True),
                entry("car-5", 0, None, dns=True),
            ),
        )
    )
    rows = by_id(result)
    assert rows["car-2"].classification_status == ClassificationStatus.DISQUALIFIED
    assert rows["car-3"].official_position == 2
    assert rows["car-5"].no_position_reason == NoPositionReason.DNS


def test_elapsed_penalty_requires_complete_group_timing_and_reorders(toy_event: Event) -> None:
    entries = (
        entry("car-1", 10, 1, elapsed=100, penalties=(penalty(),)),
        entry("car-2", 10, 2, elapsed=102),
        entry("car-3", 10, 3, elapsed=110),
        entry("car-4", 10, 4, elapsed=120),
        entry("car-5", 10, 5, elapsed=130),
    )
    assert by_id(settle(story(toy_event, entries)))["car-2"].official_position == 1
    incomplete = list(entries)
    incomplete[2] = entry("car-3", 10, 3)
    with pytest.raises(ValueError, match="timing must be complete"):
        settle(story(toy_event, tuple(incomplete)))
    contradictory = list(entries)
    contradictory[0] = entry("car-1", 10, 1, elapsed=110, penalties=(penalty(),))
    contradictory[1] = entry("car-2", 10, 2, elapsed=100)
    with pytest.raises(ValueError, match="contradicts Line-crossing order"):
        settle(story(toy_event, tuple(contradictory)))


def test_fail_closed_penalty_combinations_and_free_dq_boolean(toy_event: Event) -> None:
    with pytest.raises(ValidationError, match="multiple current-race"):
        entry(
            "car-1",
            10,
            1,
            penalties=(penalty(), penalty("official_disqualification", seconds=None)),
        )
    with pytest.raises(ValidationError, match="unsupported current-race"):
        entry("car-1", 10, 1, penalties=(penalty("other_recorded", seconds=None),))
    with pytest.raises(ValidationError, match="officially_disqualified"):
        RaceStoryEntry.model_validate(
            {**entry("car-1", 10, 1).model_dump(), "officially_disqualified": True}
        )


def test_story_rejects_ambiguous_order_start_laps_and_winner(toy_event: Event) -> None:
    valid = tuple(entry(f"car-{i}", 10, i) for i in range(1, 6))
    with pytest.raises(ValueError, match="Line-crossing"):
        settle(story(toy_event, (*valid[:-1], entry("car-5", 10, 4))))
    zero_lap = (
        entry("car-1", 10, None),
        *(entry(f"car-{i}", 0, i - 1, retired=True) for i in range(2, 6)),
    )
    zero_lap = (*zero_lap[:-1], entry("car-5", 0, None, retired=True))
    with pytest.raises(ValueError, match="zero-lap physical starters"):
        settle(story(toy_event, zero_lap))
    with pytest.raises(ValidationError, match="scheduled_laps"):
        story(toy_event, (entry("car-1", 11, 1), *valid[1:]))
    with pytest.raises(ValidationError, match="start_status"):
        story(toy_event, (entry("car-1", 0, None, dns=True), *valid[1:]))
    with pytest.raises(ValidationError, match="official_winner_laps"):
        story(toy_event, valid, winner_laps=9)


def test_winner_laps_survives_road_leader_dq(toy_event: Event) -> None:
    entries = (
        entry("car-1", 10, 1, penalties=(penalty("official_disqualification", seconds=None),)),
        entry("car-2", 9, 1),
        entry("car-3", 9, 2),
        entry("car-4", 8, 1),
        entry("car-5", 8, 2),
    )
    result = settle(story(toy_event, entries, winner_laps=9))
    assert result.classification_threshold_laps == 8


def test_story_rejects_penalties_across_multiple_entrants(toy_event: Event) -> None:
    entries = (
        entry("car-1", 10, 1, elapsed=100, penalties=(penalty(),)),
        entry("car-2", 10, 2, elapsed=101),
        entry("car-3", 10, 3, elapsed=102),
        entry("car-4", 10, 4, elapsed=103),
        entry("car-5", 8, 5, elapsed=104, penalties=(penalty(),)),
    )
    with pytest.raises(ValidationError, match="multiple current-race penalties"):
        story(toy_event, entries)


def test_winner_laps_must_equal_maximum_non_dq_laps(toy_event: Event) -> None:
    entries = (
        entry("car-1", 10, 1),
        entry("car-2", 9, 2),
        entry("car-3", 9, 3),
        entry("car-4", 8, 4),
        entry("car-5", 8, 5),
    )
    with pytest.raises(ValidationError, match="maximum completed laps"):
        story(toy_event, entries, winner_laps=9)


def test_threshold_rounding_for_57_lap_winner(toy_event: Event) -> None:
    event_data = toy_event.model_dump()
    event_data["circuit"]["scheduled_laps"] = 57
    event = Event.model_validate(event_data)
    entries = (
        entry("car-1", 57, 1),
        entry("car-2", 57, 2),
        entry("car-3", 51, 1, retired=True),
        entry("car-4", 50, 1, retired=True),
        entry("car-5", 50, 2, retired=True),
    )
    result = settle(story(event, entries, winner_laps=57))
    rows = by_id(result)
    assert result.classification_threshold_laps == 51
    assert rows["car-3"].classification_status == ClassificationStatus.CLASSIFIED
    assert rows["car-4"].classification_status == ClassificationStatus.UNCLASSIFIED
    huge_laps = 2**53 - 1
    huge_data = toy_event.model_dump()
    huge_data["circuit"]["scheduled_laps"] = huge_laps
    huge_event = Event.model_validate(huge_data)
    huge_entries = tuple(entry(f"car-{i}", huge_laps, i) for i in range(1, 6))
    huge_result = settle(story(huge_event, huge_entries, winner_laps=huge_laps))
    assert huge_result.classification_threshold_laps == 9 * huge_laps // 10


def test_unclassified_elapsed_penalty_remains_evidence_consistent(toy_event: Event) -> None:
    entries = (
        entry("car-1", 10, 1, elapsed=100),
        entry("car-2", 10, 2, elapsed=101),
        entry("car-3", 9, 1, retired=True, elapsed=102),
        entry("car-4", 9, 2, retired=True, elapsed=103),
        entry("car-5", 8, 1, retired=True, elapsed=104, penalties=(penalty(),)),
    )
    result = settle(story(toy_event, entries))
    row = by_id(result)["car-5"]
    assert row.classification_status == ClassificationStatus.UNCLASSIFIED
    assert row.final_regulatory_disposition == RegulatoryDisposition.PENALIZED


def test_public_classification_contract_rejects_impossible_states(toy_event: Event) -> None:
    entries = tuple(entry(f"car-{i}", 10, i) for i in range(1, 6))
    result = settle(story(toy_event, entries))

    bad_row = result.entries[0].model_dump()
    bad_row.update(
        start_status="dns",
        terminal_physical_status="running_at_finish",
        classification_status="officially_classified",
        official_position=1,
        no_position_reason=None,
        complete_laps=10,
    )
    with pytest.raises(ValidationError, match="DNS classification fields"):
        ClassificationEntry.model_validate(bad_row)

    dns_penalty = bad_row.copy()
    dns_penalty.update(
        terminal_physical_status="did_not_physically_start",
        classification_status="unclassified",
        official_position=None,
        no_position_reason="dns",
        complete_laps=0,
        penalties=[penalty().model_dump()],
        final_regulatory_disposition="classified_after_penalties",
    )
    with pytest.raises(ValidationError, match="DNS classification fields"):
        ClassificationEntry.model_validate(dns_penalty)

    bad_result = result.model_dump()
    bad_result["classification_threshold_laps"] = 999
    with pytest.raises(ValidationError, match=r"floor\(90%"):
        OfficialClassification.model_validate(bad_result)

    classified_below_threshold = result.model_dump()
    classified_below_threshold["entries"][0]["complete_laps"] = 0
    with pytest.raises(ValidationError, match="lap threshold"):
        OfficialClassification.model_validate(classified_below_threshold)

    unclassified_at_threshold = result.model_dump()
    last = unclassified_at_threshold["entries"][-1]
    last.update(
        classification_status="unclassified",
        official_position=None,
        no_position_reason="unclassified",
    )
    with pytest.raises(ValidationError, match="lap threshold"):
        OfficialClassification.model_validate(unclassified_at_threshold)


def test_forged_public_results_fail_closed(toy_event: Event) -> None:
    result = settle(story(toy_event, tuple(entry(f"car-{i}", 10, i) for i in range(1, 6))))

    bad_winner = result.model_dump()
    bad_winner.update(winner_laps=9, classification_threshold_laps=8)
    with pytest.raises(ValidationError, match="winner_laps"):
        OfficialClassification.model_validate(bad_winner)

    inverted = result.model_dump()
    inverted["entries"][0]["complete_laps"] = 9
    with pytest.raises(ValidationError, match="non-increasing"):
        OfficialClassification.model_validate(inverted)

    equal_lap_swap = result.model_dump()
    equal_lap_swap["entries"][0]["official_position"] = 2
    equal_lap_swap["entries"][1]["official_position"] = 1
    with pytest.raises(ValidationError, match="settlement evidence order"):
        OfficialClassification.model_validate(equal_lap_swap)

    duplicate_crossing = result.model_dump()
    duplicate_crossing["entries"][1]["same_lap_crossing_order"] = 1
    with pytest.raises(ValidationError, match="crossing evidence must be unique and contiguous"):
        OfficialClassification.model_validate(duplicate_crossing)

    dq_result = settle(
        story(
            toy_event,
            (
                entry("car-1", 10, 1, elapsed=100),
                entry(
                    "car-2",
                    10,
                    2,
                    elapsed=101,
                    penalties=(penalty("official_disqualification", seconds=None),),
                ),
                entry("car-3", 10, 3, elapsed=102),
                entry("car-4", 9, 1, retired=True, elapsed=103),
                entry("car-5", 9, 2, retired=True, elapsed=104),
            ),
        )
    )
    contradictory_dq_timing = dq_result.model_dump()
    contradictory_dq_timing["entries"][1]["elapsed_seconds"] = 50
    with pytest.raises(ValidationError, match="elapsed timing contradicts"):
        OfficialClassification.model_validate(contradictory_dq_timing)

    def recorded(penalty_id: str, applied_order: int) -> dict[str, object]:
        return {
            "penalty_id": penalty_id,
            "penalty_type": "other_recorded",
            "seconds": None,
            "reason": "future-only evidence",
            "issued_at": NOW,
            "applied_order": applied_order,
            "affects_current_race": False,
            "affects_future_event": True,
            "official_document": "fia-decision-synthetic.pdf",
        }

    duplicate_ids = result.model_dump()
    duplicate_ids["entries"][0]["penalties"] = [recorded("duplicate", 1)]
    duplicate_ids["entries"][1]["penalties"] = [recorded("duplicate", 2)]
    with pytest.raises(ValidationError, match="globally unique"):
        OfficialClassification.model_validate(duplicate_ids)

    duplicate_order = result.model_dump()
    duplicate_order["entries"][0]["penalties"] = [recorded("future-1", 1)]
    duplicate_order["entries"][1]["penalties"] = [recorded("future-2", 1)]
    with pytest.raises(ValidationError, match="aggregate penalty applied_order"):
        OfficialClassification.model_validate(duplicate_order)

    multiple_current = result.model_dump()
    for index, result_entry in enumerate(multiple_current["entries"]):
        result_entry["elapsed_seconds"] = 100.0 + index
    for index in (0, 1):
        multiple_current["entries"][index]["penalties"] = [
            {
                **recorded(f"elapsed-{index}", index + 1),
                "penalty_type": "elapsed_time",
                "seconds": 5,
                "affects_current_race": True,
            }
        ]
        multiple_current["entries"][index]["final_regulatory_disposition"] = (
            "classified_after_penalties"
        )
    with pytest.raises(ValidationError, match="multiple current-race"):
        OfficialClassification.model_validate(multiple_current)


def test_duplicate_story_entry_rejected(toy_event: Event) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        story(toy_event, tuple(entry("car-1", 10, i) for i in range(1, 6)))
