"""The testbed runs on the VM's Python 3.8 without pydantic, so it keeps its own copies of the
schema vocabulary. These tests fail if a copy drifts from common/schemas.py."""

from typing import get_args

from common.schemas import AppClass, ScenarioEvent
from testbed import scenario_plan
from testbed.traffic import profiles


def test_traffic_classes_match_the_schema() -> None:  # scenario_plan imports this copy
    assert set(profiles.APP_CLASSES) == set(get_args(AppClass))


def test_event_types_match_the_schema() -> None:
    event_type = ScenarioEvent.model_fields["type"].annotation
    assert set(scenario_plan.EVENT_TYPES) == set(get_args(event_type))
