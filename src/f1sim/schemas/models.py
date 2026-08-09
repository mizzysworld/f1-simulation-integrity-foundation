"""Strict canonical data contracts for bounded Phase 0B."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
PositivePosition = Annotated[int, Field(ge=1)]


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_as_utc)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssumedStartLocation(StrEnum):
    GRID = "grid"
    PIT_LANE = "pit_lane"
    KNOWN_DNS = "known_dns"


class StartStatus(StrEnum):
    GRID_START = "grid_start"
    PIT_LANE_START = "pit_lane_start"
    DNS = "dns"


class PhysicalStatus(StrEnum):
    RUNNING = "running_at_finish"
    RETIRED = "retired"
    DID_NOT_START = "did_not_physically_start"


class ClassificationStatus(StrEnum):
    CLASSIFIED = "officially_classified"
    UNCLASSIFIED = "unclassified"
    DISQUALIFIED = "disqualified_from_results"


class RegulatoryDisposition(StrEnum):
    VALID = "valid_without_classification_change"
    PENALIZED = "classified_after_penalties"
    DISQUALIFIED = "disqualified_from_results"


class NoPositionReason(StrEnum):
    DNS = "dns"
    UNCLASSIFIED = "unclassified"
    DISQUALIFIED = "disqualified_from_results"
    EVENT_SPECIFIC = "event_specific_other"


class Circuit(StrictModel):
    circuit_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scheduled_laps: int = Field(gt=0)


class Ruleset(StrictModel):
    ruleset_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    issue: str = Field(min_length=1)
    publication_date: date
    effective_event_range: str = Field(min_length=1)


class Entrant(StrictModel):
    entrant_id: str = Field(min_length=1)
    driver_name: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    assumed_start_location: AssumedStartLocation
    grid_position: PositivePosition | None = None

    @model_validator(mode="after")
    def validate_start(self) -> Entrant:
        if self.assumed_start_location == AssumedStartLocation.GRID and self.grid_position is None:
            raise ValueError("grid starters require grid_position")
        if (
            self.assumed_start_location != AssumedStartLocation.GRID
            and self.grid_position is not None
        ):
            raise ValueError("only grid starters may have grid_position")
        return self


class Event(StrictModel):
    event_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    event_date: date
    circuit: Circuit
    ruleset: Ruleset
    entrants: tuple[Entrant, ...] = Field(min_length=1)
    is_synthetic: bool

    @model_validator(mode="after")
    def validate_field(self) -> Event:
        ids = [entrant.entrant_id for entrant in self.entrants]
        grids = [e.grid_position for e in self.entrants if e.grid_position is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate entrant_id")
        if len(grids) != len(set(grids)):
            raise ValueError("duplicate grid_position")
        if any(position > len(self.entrants) for position in grids):
            raise ValueError("grid_position exceeds dynamic field size")
        return self


class Penalty(StrictModel):
    penalty_id: str = Field(min_length=1)
    penalty_type: Literal["elapsed_time", "official_disqualification", "other_recorded"]
    seconds: NonNegative | None = None
    reason: str = Field(min_length=1)
    issued_at: UtcDatetime
    applied_order: int = Field(ge=1)
    affects_current_race: bool
    affects_future_event: bool = False
    official_document: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_value(self) -> Penalty:
        if (self.penalty_type == "elapsed_time") != (self.seconds is not None):
            raise ValueError("seconds must be present only for elapsed_time penalties")
        if self.affects_current_race and self.penalty_type not in {
            "elapsed_time",
            "official_disqualification",
        }:
            raise ValueError("unsupported current-race penalty")
        return self


class Rating(StrictModel):
    entity_id: str = Field(min_length=1)
    mean: FiniteFloat
    uncertainty_sd: NonNegative
    evidence_cutoff: UtcDatetime
    prior_source: str = Field(min_length=1)


class SimulationConfig(StrictModel):
    event_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    ruleset_id: str = Field(min_length=1)
    runs: int = Field(gt=0)
    seed: int = Field(ge=0)
    cutoff: UtcDatetime
    conditions: Literal["fixed_dry"] = "fixed_dry"


class RaceStoryEntry(StrictModel):
    entrant_id: str = Field(min_length=1)
    start_status: StartStatus
    terminal_physical_status: PhysicalStatus
    complete_laps: int = Field(ge=0)
    same_lap_crossing_order: int | None = Field(default=None, ge=1)
    elapsed_seconds: NonNegative | None = None
    penalties: tuple[Penalty, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> RaceStoryEntry:
        dns = self.start_status == StartStatus.DNS
        if dns != (self.terminal_physical_status == PhysicalStatus.DID_NOT_START):
            raise ValueError("DNS and did_not_physically_start must agree")
        if dns and self.complete_laps != 0:
            raise ValueError("DNS cannot complete laps")
        if len({p.penalty_id for p in self.penalties}) != len(self.penalties):
            raise ValueError("duplicate penalty_id")
        current = [p for p in self.penalties if p.affects_current_race]
        if len(current) > 1:
            raise ValueError("multiple current-race penalties are outside the bounded contract")
        if current and current[0].penalty_type not in {
            "elapsed_time",
            "official_disqualification",
        }:
            raise ValueError("unsupported current-race penalty")
        return self


class DeterministicRaceStory(StrictModel):
    event: Event
    entries: tuple[RaceStoryEntry, ...]
    official_winner_laps: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_entries(self) -> DeterministicRaceStory:
        expected = {e.entrant_id for e in self.event.entrants}
        actual = [e.entrant_id for e in self.entries]
        if len(actual) != len(set(actual)):
            raise ValueError("duplicate race-story entrant")
        if set(actual) != expected:
            raise ValueError("race story must contain every event entrant exactly once")
        event_entrants = {e.entrant_id: e for e in self.event.entrants}
        expected_start = {
            AssumedStartLocation.GRID: StartStatus.GRID_START,
            AssumedStartLocation.PIT_LANE: StartStatus.PIT_LANE_START,
            AssumedStartLocation.KNOWN_DNS: StartStatus.DNS,
        }
        for entry in self.entries:
            if (
                entry.start_status
                != expected_start[event_entrants[entry.entrant_id].assumed_start_location]
            ):
                raise ValueError("assumed_start_location contradicts race-story start_status")
            if entry.complete_laps > self.event.circuit.scheduled_laps:
                raise ValueError("complete_laps exceeds scheduled_laps")
        if self.official_winner_laps > self.event.circuit.scheduled_laps:
            raise ValueError("official_winner_laps exceeds scheduled_laps")
        current_penalties = [
            penalty
            for entry in self.entries
            for penalty in entry.penalties
            if penalty.affects_current_race
        ]
        if len(current_penalties) > 1:
            raise ValueError("multiple current-race penalties are outside the bounded contract")
        non_dq_laps = [
            entry.complete_laps
            for entry in self.entries
            if not any(
                penalty.penalty_type == "official_disqualification" and penalty.affects_current_race
                for penalty in entry.penalties
            )
        ]
        if not non_dq_laps or self.official_winner_laps != max(non_dq_laps):
            raise ValueError(
                "official_winner_laps must equal maximum completed laps among non-DQ entrants"
            )
        return self


class RetirementInput(StrictModel):
    """Physical terminal state only; predictive retirement timing is gated."""

    entrant_id: str = Field(min_length=1)
    terminal_physical_status: PhysicalStatus


class ClassificationEntry(StrictModel):
    entrant_id: str
    start_status: StartStatus
    terminal_physical_status: PhysicalStatus
    classification_status: ClassificationStatus
    official_position: PositivePosition | None
    no_position_reason: NoPositionReason | None
    final_regulatory_disposition: RegulatoryDisposition
    complete_laps: int = Field(ge=0)
    same_lap_crossing_order: PositivePosition | None
    elapsed_seconds: NonNegative | None
    penalties: tuple[Penalty, ...] = ()

    @model_validator(mode="after")
    def validate_position(self) -> ClassificationEntry:
        penalty_ids = [penalty.penalty_id for penalty in self.penalties]
        if len(penalty_ids) != len(set(penalty_ids)):
            raise ValueError("duplicate penalty_id")
        applied_orders = [penalty.applied_order for penalty in self.penalties]
        if len(applied_orders) != len(set(applied_orders)):
            raise ValueError("penalty applied_order must be unique")
        if sum(penalty.affects_current_race for penalty in self.penalties) > 1:
            raise ValueError("multiple current-race penalties are outside the bounded contract")
        is_dns = self.start_status == StartStatus.DNS
        if is_dns:
            if (
                self.terminal_physical_status != PhysicalStatus.DID_NOT_START
                or self.classification_status != ClassificationStatus.UNCLASSIFIED
                or self.no_position_reason != NoPositionReason.DNS
                or self.official_position is not None
                or self.complete_laps != 0
                or any(penalty.affects_current_race for penalty in self.penalties)
                or self.final_regulatory_disposition != RegulatoryDisposition.VALID
            ):
                raise ValueError("DNS classification fields are internally inconsistent")
        elif self.terminal_physical_status == PhysicalStatus.DID_NOT_START:
            raise ValueError("did_not_physically_start requires DNS start status")
        has_position = self.official_position is not None
        if has_position != (self.classification_status == ClassificationStatus.CLASSIFIED):
            raise ValueError("only classified entrants have an official position")
        if has_position == (self.no_position_reason is not None):
            raise ValueError("exactly one of position and no_position_reason is required")
        if (
            self.classification_status == ClassificationStatus.UNCLASSIFIED
            and self.no_position_reason not in {NoPositionReason.UNCLASSIFIED, NoPositionReason.DNS}
        ):
            raise ValueError("no_position_reason contradicts unclassified status")
        if (
            self.classification_status == ClassificationStatus.DISQUALIFIED
            and self.no_position_reason != NoPositionReason.DISQUALIFIED
        ):
            raise ValueError("no_position_reason contradicts disqualified status")
        current_dqs = [
            penalty
            for penalty in self.penalties
            if penalty.affects_current_race and penalty.penalty_type == "official_disqualification"
        ]
        is_dq = self.classification_status == ClassificationStatus.DISQUALIFIED
        if is_dq != (self.final_regulatory_disposition == RegulatoryDisposition.DISQUALIFIED):
            raise ValueError("disqualified status and disposition must agree")
        if is_dq and not current_dqs:
            raise ValueError("disqualification requires controlling penalty evidence")
        if not is_dq and current_dqs:
            raise ValueError("controlling disqualification evidence requires disqualified status")
        current_non_dq = [
            penalty
            for penalty in self.penalties
            if penalty.affects_current_race and penalty.penalty_type != "official_disqualification"
        ]
        if (
            self.final_regulatory_disposition == RegulatoryDisposition.PENALIZED
            and not current_non_dq
        ):
            raise ValueError("penalized disposition requires current-race penalty evidence")
        if self.final_regulatory_disposition == RegulatoryDisposition.VALID and current_non_dq:
            raise ValueError("current-race penalty evidence requires penalized disposition")
        return self


class OfficialClassification(StrictModel):
    event_id: str
    ruleset_id: str
    field_size: int = Field(gt=0)
    winner_laps: int = Field(ge=0)
    classification_threshold_laps: int = Field(ge=0)
    entries: tuple[ClassificationEntry, ...]

    @model_validator(mode="after")
    def validate_classification(self) -> OfficialClassification:
        if len(self.entries) != self.field_size:
            raise ValueError("entries must equal dynamic field_size")
        if self.classification_threshold_laps != 9 * self.winner_laps // 10:
            raise ValueError("classification threshold must equal floor(90% of winner laps)")
        entrant_ids = [entry.entrant_id for entry in self.entries]
        if len(entrant_ids) != len(set(entrant_ids)):
            raise ValueError("classification entrant IDs must be unique")
        positions = [e.official_position for e in self.entries if e.official_position is not None]
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise ValueError("classified positions must be unique and contiguous")
        non_dq_laps = [
            entry.complete_laps
            for entry in self.entries
            if entry.start_status != StartStatus.DNS
            and entry.classification_status != ClassificationStatus.DISQUALIFIED
        ]
        if not non_dq_laps or self.winner_laps != max(non_dq_laps):
            raise ValueError(
                "winner_laps must equal maximum completed laps among applicable non-DQ entrants"
            )
        ordered = sorted(
            (entry for entry in self.entries if entry.official_position is not None),
            key=lambda entry: entry.official_position or 0,
        )
        if any(
            left.complete_laps < right.complete_laps for left, right in pairwise(ordered)
        ):
            raise ValueError(
                "official positions must have non-increasing complete_laps and respect "
                "the lap threshold"
            )
        penalties = [penalty for entry in self.entries for penalty in entry.penalties]
        if sum(penalty.affects_current_race for penalty in penalties) > 1:
            raise ValueError("multiple current-race penalties are outside the bounded contract")
        groups: dict[int, list[ClassificationEntry]] = {}
        for entry in ordered:
            groups.setdefault(entry.complete_laps, []).append(entry)
        for group in groups.values():
            if len(group) < 2:
                continue
            if any(entry.same_lap_crossing_order is None for entry in group):
                raise ValueError("same-lap classification requires retained crossing evidence")
            crossing_order = sorted(
                group, key=lambda entry: entry.same_lap_crossing_order or 0
            )
            elapsed_values = [entry.elapsed_seconds for entry in crossing_order]
            concrete_elapsed = [value for value in elapsed_values if value is not None]
            if len(concrete_elapsed) == len(elapsed_values) and any(
                left > right for left, right in pairwise(concrete_elapsed)
            ):
                raise ValueError("elapsed timing contradicts Line-crossing order")
            elapsed_penalties = [
                entry
                for entry in group
                if any(
                    penalty.affects_current_race and penalty.penalty_type == "elapsed_time"
                    for penalty in entry.penalties
                )
            ]
            if elapsed_penalties:
                if not all(value is not None for value in elapsed_values):
                    raise ValueError("elapsed timing must be complete for penalized same-lap group")

                def adjusted(entry: ClassificationEntry) -> float:
                    assert entry.elapsed_seconds is not None
                    penalty_seconds = sum(
                        penalty.seconds or 0.0
                        for penalty in entry.penalties
                        if penalty.affects_current_race and penalty.penalty_type == "elapsed_time"
                    )
                    return entry.elapsed_seconds + penalty_seconds

                expected = sorted(
                    group,
                    key=lambda entry: (
                        adjusted(entry),
                        entry.same_lap_crossing_order or 0,
                    ),
                )
            else:
                expected = crossing_order
            actual = sorted(group, key=lambda entry: entry.official_position or 0)
            if [entry.entrant_id for entry in actual] != [entry.entrant_id for entry in expected]:
                raise ValueError("official positions contradict retained settlement evidence order")
        penalty_ids = [penalty.penalty_id for penalty in penalties]
        if len(penalty_ids) != len(set(penalty_ids)):
            raise ValueError("penalty IDs must be globally unique")
        applied_orders = [penalty.applied_order for penalty in penalties]
        if len(applied_orders) != len(set(applied_orders)) or sorted(applied_orders) != list(
            range(1, len(applied_orders) + 1)
        ):
            raise ValueError("aggregate penalty applied_order must be unique and contiguous")
        if sum(penalty.affects_current_race for penalty in penalties) > 1:
            raise ValueError("multiple current-race penalties are outside the bounded contract")
        for entry in self.entries:
            if entry.start_status == StartStatus.DNS or (
                entry.classification_status == ClassificationStatus.DISQUALIFIED
            ):
                continue
            should_be_classified = entry.complete_laps >= self.classification_threshold_laps
            is_classified = entry.classification_status == ClassificationStatus.CLASSIFIED
            if should_be_classified != is_classified:
                raise ValueError("classification status contradicts the lap threshold")
        return self


class EntrantDistribution(StrictModel):
    entrant_id: str
    position_probabilities: tuple[Probability, ...]
    no_official_position_probability: Probability
    completion_probability: Probability
    retirement_probability: Probability
    physical_status_probabilities: tuple[Probability, Probability, Probability]
    classification_status_probabilities: tuple[Probability, Probability, Probability]
    regulatory_disposition_probabilities: tuple[Probability, Probability, Probability]

    @model_validator(mode="after")
    def validate_probabilities(self) -> EntrantDistribution:
        if abs(sum(self.position_probabilities) + self.no_official_position_probability - 1) > 1e-9:
            raise ValueError("position probabilities plus no-position probability must sum to 1")
        legacy_total = self.completion_probability + self.retirement_probability
        if min(abs(legacy_total), abs(legacy_total - 1)) > 1e-9:
            raise ValueError("completion and retirement probabilities must sum to 1, or 0 for DNS")
        for axis in (
            self.physical_status_probabilities,
            self.classification_status_probabilities,
            self.regulatory_disposition_probabilities,
        ):
            if abs(sum(axis) - 1) > 1e-9:
                raise ValueError("each canonical status axis must independently sum to 1")
        classified_probability = self.classification_status_probabilities[0]
        if abs(sum(self.position_probabilities) - classified_probability) > 1e-9:
            raise ValueError("position mass must equal classified probability")
        unclassified_or_dq = sum(self.classification_status_probabilities[1:])
        if abs(self.no_official_position_probability - unclassified_or_dq) > 1e-9:
            raise ValueError(
                "no-position probability must equal unclassified plus disqualified probability"
            )
        return self


class SnapshotIdentity(StrictModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cutoff: UtcDatetime
    event_id: str = Field(min_length=1)
    synthetic: bool

    @model_validator(mode="after")
    def validate_content_address(self) -> SnapshotIdentity:
        if self.snapshot_id != f"snap-{self.snapshot_hash[:16]}":
            raise ValueError("snapshot_id must derive from snapshot_hash")
        return self


class BaselineInput(StrictModel):
    """Complete canonical identity of one bounded baseline invocation."""

    event: Event
    snapshot: SnapshotIdentity | None = None
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    ruleset_id: str = Field(min_length=1)
    configuration: dict[str, str | int | float | bool | None]
    model_parameters: dict[str, str | int | float | bool | None]

    @model_validator(mode="after")
    def validate_relationships(self) -> BaselineInput:
        if self.event.ruleset.ruleset_id != self.ruleset_id:
            raise ValueError("baseline input ruleset does not match event")
        if self.snapshot is not None and self.snapshot.event_id != self.event.event_id:
            raise ValueError("baseline event does not match snapshot event")
        if self.snapshot is not None and self.snapshot.synthetic != self.event.is_synthetic:
            raise ValueError("baseline event and snapshot synthetic states must match")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()

    def canonical_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class CanonicalPrediction(StrictModel):
    event_id: str
    model_id: str
    model_version: str
    ruleset_id: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_input: BaselineInput
    field_size: int = Field(gt=0)
    distributions: tuple[EntrantDistribution, ...]
    synthetic: bool
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_dimensions(self) -> CanonicalPrediction:
        relationships = (
            (self.event_id, self.baseline_input.event.event_id, "event"),
            (self.model_id, self.baseline_input.model_id, "model"),
            (self.model_version, self.baseline_input.model_version, "model version"),
            (self.ruleset_id, self.baseline_input.ruleset_id, "ruleset"),
            (self.input_hash, self.baseline_input.canonical_hash(), "input hash"),
        )
        for actual, expected, label in relationships:
            if actual != expected:
                raise ValueError(f"prediction {label} does not match canonical baseline input")
        if self.synthetic != self.baseline_input.event.is_synthetic:
            raise ValueError("prediction synthetic flag does not match embedded event")
        if len(self.distributions) != self.field_size:
            raise ValueError("one distribution required per entrant")
        ids = [d.entrant_id for d in self.distributions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate distribution entrant")
        expected_ids = {entrant.entrant_id for entrant in self.baseline_input.event.entrants}
        if set(ids) != expected_ids:
            raise ValueError("prediction distributions must match the event entrant set exactly")
        if any(len(d.position_probabilities) != self.field_size for d in self.distributions):
            raise ValueError("position vector must match dynamic field size")
        for position in range(self.field_size):
            if sum(row.position_probabilities[position] for row in self.distributions) > 1 + 1e-9:
                raise ValueError("position column probability mass cannot exceed 1")
        return self


class PredictionReceipt(StrictModel):
    receipt_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    event_id: str = Field(min_length=1)
    snapshot_id: str | None = None
    snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cutoff: UtcDatetime
    created_at: UtcDatetime
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    field_size: int = Field(gt=0)
    schema_version: str = Field(min_length=1)
    ruleset_id: str = Field(min_length=1)
    code_version: str = Field(min_length=1)
    dependency_lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    python_version: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    calibration_version: str | None = None
    warnings: tuple[str, ...] = ()
    seed: int = Field(ge=0)
    runs: int = Field(gt=0)
    status: Literal["complete", "failed"]
    synthetic: bool

    @model_validator(mode="after")
    def validate_snapshot_pair(self) -> PredictionReceipt:
        if (self.snapshot_id is None) != (self.snapshot_hash is None):
            raise ValueError("snapshot ID and hash must be supplied together")
        return self
