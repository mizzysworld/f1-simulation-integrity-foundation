from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

import f1sim
from f1sim.models.baselines import (
    equal_strength,
    grid_only,
    team_priority_then_grid,
)
from f1sim.reporting.receipt import prediction_hash
from f1sim.schemas import (
    AssumedStartLocation,
    CanonicalPrediction,
    Circuit,
    Entrant,
    Event,
    Ruleset,
)


def dynamic_event(size: int) -> Event:
    return Event(
        event_id=f"synthetic-full-field-{size}",
        name="Synthetic Dynamic Full Field",
        event_date=date(2026, 1, 1),
        circuit=Circuit(circuit_id="dynamic", name="Dynamic", scheduled_laps=50),
        ruleset=Ruleset(
            ruleset_id="fia-f1-2026-section-b-issue-07",
            source_url="https://fia.example/rules.pdf",
            issue="07",
            publication_date=date(2026, 6, 25),
            effective_event_range="2026-current",
        ),
        entrants=tuple(
            Entrant(
                entrant_id=f"e{i}",
                driver_name=f"D{i}",
                team_id=f"t{i // 2}",
                assumed_start_location=AssumedStartLocation.GRID,
                grid_position=i + 1,
            )
            for i in range(size)
        ),
        is_synthetic=True,
    )


@pytest.mark.parametrize("size", [2, 3, 5, 10, 22, 24])
def test_all_baselines_use_dynamic_canonical_contract(size: int) -> None:
    assert f1sim.__version__ == "0.1.0"
    event = dynamic_event(size)
    strengths = {entrant.team_id: float(index) for index, entrant in enumerate(event.entrants)}
    for result in (
        equal_strength(event),
        grid_only(event),
        team_priority_then_grid(event, strengths),
    ):
        assert result.field_size == size
        assert len(result.distributions) == size
        assert all(len(row.position_probabilities) == size for row in result.distributions)
        assert all(abs(sum(row.position_probabilities) - 1) < 1e-12 for row in result.distributions)
        assert result.synthetic


def test_grid_only_follows_grid(toy_event: Event) -> None:
    result = grid_only(toy_event)
    row = next(row for row in result.distributions if row.entrant_id == "car-1")
    assert row.position_probabilities[0] == 1


def test_grid_team_requires_complete_strengths(toy_event: Event) -> None:
    with pytest.raises(ValueError, match="missing team strengths"):
        team_priority_then_grid(toy_event, {})


def test_known_dns_is_deterministic_no_position(toy_event: Event) -> None:
    data = toy_event.model_dump()
    data["entrants"][4].update(assumed_start_location="known_dns", grid_position=None)
    event = Event.model_validate(data)
    active_strengths = {
        entrant.team_id: 1.0
        for entrant in event.entrants
        if entrant.assumed_start_location != AssumedStartLocation.KNOWN_DNS
    }
    for result in (
        equal_strength(event),
        grid_only(event),
        team_priority_then_grid(event, active_strengths),
    ):
        row = next(item for item in result.distributions if item.entrant_id == "car-5")
        assert row.no_official_position_probability == 1
        assert row.completion_probability == 0
        assert row.retirement_probability == 0
        assert sum(row.position_probabilities) == 0


@given(size=st.integers(min_value=2, max_value=30))
def test_dynamic_field_probability_normalization_property(size: int) -> None:
    result = equal_strength(dynamic_event(size))
    assert all(
        abs(sum(row.position_probabilities) + row.no_official_position_probability - 1) < 1e-12
        for row in result.distributions
    )


def test_canonical_input_hash_covers_team_parameters_and_is_stable(toy_event: Event) -> None:
    first = {"team-1": 1.0, "team-2": 2.0, "team-3": 3.0}
    reordered = {"team-3": 3.0, "team-1": 1.0, "team-2": 2.0}
    changed = {**first, "team-1": 9.0}
    hash_one = team_priority_then_grid(toy_event, first).input_hash
    assert team_priority_then_grid(toy_event, reordered).input_hash == hash_one
    assert team_priority_then_grid(toy_event, changed).input_hash != hash_one
    prediction = team_priority_then_grid(toy_event, first)
    payload = prediction.model_dump()
    parameters = payload["baseline_input"]["model_parameters"]
    payload["baseline_input"]["model_parameters"] = {
        key: parameters[key] for key in reversed(parameters)
    }
    semantically_identical = CanonicalPrediction.model_validate(payload)
    assert prediction_hash(semantically_identical) == prediction_hash(prediction)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_grid_team_rejects_non_finite_strength(toy_event: Event, value: float) -> None:
    strengths = {entrant.team_id: 1.0 for entrant in toy_event.entrants}
    strengths[toy_event.entrants[0].team_id] = value
    with pytest.raises(ValueError, match="must be finite"):
        team_priority_then_grid(toy_event, strengths)


def test_prediction_distributions_match_event_entrant_set(toy_event: Event) -> None:
    prediction = grid_only(toy_event)
    payload = prediction.model_dump()
    payload["distributions"][0]["entrant_id"] = "not-in-event"
    with pytest.raises(ValidationError, match="event entrant set"):
        CanonicalPrediction.model_validate(payload)
    impossible = prediction.model_dump()
    first_position = tuple(
        1.0 if index == 0 else 0.0 for index in range(prediction.field_size)
    )
    for row in impossible["distributions"]:
        row["position_probabilities"] = first_position
    with pytest.raises(ValidationError, match="position column"):
        CanonicalPrediction.model_validate(impossible)


def test_prediction_rejects_did_not_start_mass_with_classified_position_mass() -> None:
    prediction = equal_strength(dynamic_event(2))
    payload = prediction.model_dump()
    payload["distributions"][0].update(
        completion_probability=0.0,
        retirement_probability=0.0,
        physical_status_probabilities=(0.0, 0.0, 1.0),
    )
    with pytest.raises(ValidationError, match="did-not-start probability"):
        CanonicalPrediction.model_validate(payload)


def test_prediction_rejects_noncontiguous_position_occupancy_marginals() -> None:
    prediction = equal_strength(dynamic_event(2))
    payload = prediction.model_dump()
    for row in payload["distributions"]:
        row.update(
            position_probabilities=(0.0, 0.5),
            no_official_position_probability=0.5,
            classification_status_probabilities=(0.5, 0.5, 0.0),
        )
    with pytest.raises(ValidationError, match="non-increasing"):
        CanonicalPrediction.model_validate(payload)
