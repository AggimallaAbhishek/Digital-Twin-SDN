"""P1.6 contract: every scenario file is a valid common/schemas.py Scenario, and the VM-side
parser (testbed/scenario_plan.py) reads it the same way."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from common.schemas import Scenario
from testbed.scenario_plan import parse_scenario

SCENARIOS = Path(__file__).resolve().parents[2] / "experiments" / "scenarios"
FILES = sorted(SCENARIOS.glob("*.yaml"))
EXPECTED = {"normal", "lecture_flash_crowd", "ap_failure", "cochannel_interference"}


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def test_the_four_scenarios_exist() -> None:
    assert {path.stem for path in FILES} == EXPECTED


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_scenario_file_validates_as_scenario(path: Path) -> None:
    scenario = Scenario.model_validate(_load(path))
    assert scenario.scenario_id == path.stem


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_vm_parser_agrees_with_the_schema(path: Path) -> None:
    raw = _load(path)
    scenario, spec = Scenario.model_validate(raw), parse_scenario(raw)
    assert (spec.scenario_id, spec.duration_s, spec.seed) == (
        scenario.scenario_id,
        scenario.duration_s,
        scenario.seed,
    )
    assert [(t.profile, t.stations, t.start_s, t.rate_mbps) for t in spec.traffic] == [
        (t.profile, t.stations, t.start_s, t.rate_mbps) for t in scenario.traffic
    ]
    assert [(e.at_s, e.type, e.ap, e.channel) for e in spec.events] == [
        (e.at_s, e.type, e.ap, e.channel) for e in scenario.events
    ]
    assert len(spec.groups) == len(scenario.mobility.groups)
