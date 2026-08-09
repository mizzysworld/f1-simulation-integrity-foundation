from __future__ import annotations

from datetime import date

import pytest

from f1sim.schemas import AssumedStartLocation, Circuit, Entrant, Event, Ruleset


@pytest.fixture
def toy_event() -> Event:
    entrants = tuple(
        Entrant(
            entrant_id=f"car-{i}",
            driver_name=f"Driver {i}",
            team_id=f"team-{(i + 1) // 2}",
            assumed_start_location=AssumedStartLocation.GRID,
            grid_position=i,
        )
        for i in range(1, 6)
    )
    return Event(
        event_id="synthetic-toy-2026",
        name="Synthetic Toy GP",
        event_date=date(2026, 1, 1),
        circuit=Circuit(circuit_id="toy", name="Toy Circuit", scheduled_laps=10),
        ruleset=Ruleset(
            ruleset_id="fia-f1-2026-section-b-issue-07",
            source_url="https://fia.example/rules.pdf",
            issue="07",
            publication_date=date(2026, 6, 25),
            effective_event_range="2026-current",
        ),
        entrants=entrants,
        is_synthetic=True,
    )
