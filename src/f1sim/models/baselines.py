"""Transparent bounded baselines using the canonical result contract."""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping

from f1sim.schemas import (
    AssumedStartLocation,
    BaselineInput,
    CanonicalPrediction,
    EntrantDistribution,
    Event,
    SnapshotIdentity,
)

MODEL_VERSION = "0b.2"


def _prediction(
    event: Event,
    model_id: str,
    rankings: list[str] | None,
    *,
    parameters: Mapping[str, str | int | float | bool | None],
    snapshot: SnapshotIdentity | None = None,
) -> CanonicalPrediction:
    n = len(event.entrants)
    active = [
        entrant
        for entrant in event.entrants
        if entrant.assumed_start_location != AssumedStartLocation.KNOWN_DNS
    ]
    active_n = len(active)
    if active_n == 0:
        raise ValueError("baseline requires at least one assumed starter")
    baseline_input = BaselineInput(
        event=event,
        snapshot=snapshot,
        model_id=model_id,
        model_version=MODEL_VERSION,
        ruleset_id=event.ruleset.ruleset_id,
        configuration={"known_dns_policy": "deterministic_no_position"},
        model_parameters=dict(parameters),
    )
    position_by_id = {entrant_id: index for index, entrant_id in enumerate(rankings or [], 1)}
    distributions = []
    for entrant in event.entrants:
        dns = entrant.assumed_start_location == AssumedStartLocation.KNOWN_DNS
        if dns:
            probabilities = (0.0,) * n
        elif rankings is None:
            probabilities = tuple(
                1.0 / active_n if position < active_n else 0.0 for position in range(n)
            )
        else:
            probabilities = tuple(
                1.0 if position == position_by_id[entrant.entrant_id] else 0.0
                for position in range(1, n + 1)
            )
        distributions.append(
            EntrantDistribution(
                entrant_id=entrant.entrant_id,
                position_probabilities=probabilities,
                no_official_position_probability=1.0 if dns else 0.0,
                completion_probability=0.0 if dns else 1.0,
                retirement_probability=0.0,
                physical_status_probabilities=(0.0, 0.0, 1.0) if dns else (1.0, 0.0, 0.0),
                classification_status_probabilities=(0.0, 1.0, 0.0) if dns else (1.0, 0.0, 0.0),
                regulatory_disposition_probabilities=(1.0, 0.0, 0.0),
            )
        )
    return CanonicalPrediction(
        event_id=event.event_id,
        model_id=model_id,
        model_version=MODEL_VERSION,
        ruleset_id=event.ruleset.ruleset_id,
        input_hash=baseline_input.canonical_hash(),
        baseline_input=baseline_input,
        field_size=n,
        distributions=tuple(distributions),
        synthetic=event.is_synthetic,
        warnings=("Phase 0B.2 baseline: not a designated or validated forecast model",),
    )


def equal_strength(
    event: Event, *, snapshot: SnapshotIdentity | None = None
) -> CanonicalPrediction:
    return _prediction(event, "phase0b-equal-strength", None, parameters={}, snapshot=snapshot)


def _ranked(event: Event, team_strength: Mapping[str, float] | None = None) -> list[str]:
    return [
        entrant.entrant_id
        for entrant in sorted(
            event.entrants,
            key=lambda entrant: (
                -(team_strength or {}).get(entrant.team_id, 0.0),
                entrant.grid_position is None,
                entrant.grid_position or len(event.entrants) + 1,
                entrant.entrant_id,
            ),
        )
        if entrant.assumed_start_location != AssumedStartLocation.KNOWN_DNS
    ]


def grid_only(event: Event, *, snapshot: SnapshotIdentity | None = None) -> CanonicalPrediction:
    return _prediction(event, "phase0b-grid-only", _ranked(event), parameters={}, snapshot=snapshot)


def team_priority_then_grid(
    event: Event,
    team_strength: Mapping[str, float],
    *,
    snapshot: SnapshotIdentity | None = None,
) -> CanonicalPrediction:
    """Rank by descending team strength, then grid; this is not an additive score."""
    active_teams = {
        entrant.team_id
        for entrant in event.entrants
        if entrant.assumed_start_location != AssumedStartLocation.KNOWN_DNS
    }
    missing = active_teams - team_strength.keys()
    if missing:
        raise ValueError(f"missing team strengths: {sorted(missing)}")
    non_finite = sorted(
        team_id for team_id in active_teams if not math.isfinite(team_strength[team_id])
    )
    if non_finite:
        raise ValueError(f"team strengths must be finite: {non_finite}")
    normalized = {team_id: team_strength[team_id] for team_id in sorted(active_teams)}
    return _prediction(
        event,
        "phase0b-team-priority-then-grid",
        _ranked(event, team_strength),
        parameters={f"team_strength.{key}": value for key, value in normalized.items()},
        snapshot=snapshot,
    )


def grid_and_team(event: Event, team_strength: Mapping[str, float]) -> CanonicalPrediction:
    """Deprecated compatibility alias for :func:`team_priority_then_grid`."""
    warnings.warn(
        "grid_and_team is deprecated; use team_priority_then_grid",
        DeprecationWarning,
        stacklevel=2,
    )
    return team_priority_then_grid(event, team_strength)
