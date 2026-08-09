from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from f1sim.schemas import (
    AssumedStartLocation,
    DeterministicRaceStory,
    Entrant,
    EntrantDistribution,
    Event,
    PhysicalStatus,
    RaceStoryEntry,
    Rating,
    RetirementInput,
    StartStatus,
)


def test_event_rejects_duplicate_and_bad_dynamic_grid(toy_event: Event) -> None:
    data = toy_event.model_dump()
    data["entrants"] = [data["entrants"][0], data["entrants"][0]]
    with pytest.raises(ValidationError, match="duplicate entrant_id"):
        Event.model_validate(data)
    data = toy_event.model_dump()
    data["entrants"][0]["grid_position"] = 99
    with pytest.raises(ValidationError, match="dynamic field size"):
        Event.model_validate(data)


def test_event_rejects_missing_ruleset_and_bad_start() -> None:
    with pytest.raises(ValidationError, match="only grid starters"):
        Entrant(
            entrant_id="x",
            driver_name="X",
            team_id="t",
            assumed_start_location=AssumedStartLocation.KNOWN_DNS,
            grid_position=1,
        )


def test_contradictory_dns_status_rejected() -> None:
    with pytest.raises(ValidationError, match="must agree"):
        RaceStoryEntry(
            entrant_id="x",
            start_status=StartStatus.DNS,
            terminal_physical_status=PhysicalStatus.RETIRED,
            complete_laps=0,
        )


def test_numeric_values_are_finite_and_retirement_has_no_timing() -> None:
    for value in (-0.01, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            Rating(
                entity_id="x",
                mean=0,
                uncertainty_sd=value,
                evidence_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
                prior_source="test",
            )
    with pytest.raises(ValidationError, match="Extra inputs"):
        RetirementInput.model_validate(
            {"entrant_id": "x", "terminal_physical_status": "retired", "retirement_lap": 4}
        )


def distribution(**changes: object) -> EntrantDistribution:
    data: dict[str, object] = {
        "entrant_id": "x",
        "position_probabilities": (1.0,),
        "no_official_position_probability": 0.0,
        "completion_probability": 1.0,
        "retirement_probability": 0.0,
        "physical_status_probabilities": (1.0, 0.0, 0.0),
        "classification_status_probabilities": (1.0, 0.0, 0.0),
        "regulatory_disposition_probabilities": (1.0, 0.0, 0.0),
    }
    data.update(changes)
    return EntrantDistribution.model_validate(data)


def test_invalid_probabilities_and_independent_axes_rejected() -> None:
    with pytest.raises(ValidationError):
        distribution(position_probabilities=(0.7, 0.7), completion_probability=1.2)
    with pytest.raises(ValidationError, match="status axis"):
        distribution(physical_status_probabilities=(0.8, 0.8, 0.0))
    with pytest.raises(ValidationError, match="classified probability"):
        distribution(classification_status_probabilities=(0.0, 1.0, 0.0))
    with pytest.raises(ValidationError, match="physical running probability"):
        distribution(
            completion_probability=1.0,
            retirement_probability=0.0,
            physical_status_probabilities=(0.0, 1.0, 0.0),
        )
    with pytest.raises(ValidationError, match="physical retirement probability"):
        distribution(
            completion_probability=0.5,
            retirement_probability=0.5,
            physical_status_probabilities=(0.5, 0.4, 0.1),
        )
    with pytest.raises(ValidationError, match="disqualification probability"):
        distribution(
            regulatory_disposition_probabilities=(0.0, 0.0, 1.0),
        )


def test_json_fixtures_are_parseable_canonical_payloads() -> None:
    root = Path(__file__).parents[1] / "fixtures"
    story = DeterministicRaceStory.model_validate_json((root / "toy_event.json").read_text())
    event = Event.model_validate_json((root / "dynamic_full_field.json").read_text())
    bad = json.loads((root / "contradictions.json").read_text())
    assert len(story.entries) == 4 and len(event.entrants) == 6
    with pytest.raises(ValidationError, match="duplicate entrant_id"):
        Event.model_validate(bad["duplicate_entrant"])
    with pytest.raises(ValidationError, match="must agree"):
        RaceStoryEntry.model_validate(bad["contradictory_entry"])
