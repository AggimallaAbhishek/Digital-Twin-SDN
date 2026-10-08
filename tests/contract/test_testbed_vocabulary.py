"""The testbed runs on the VM's Python 3.8 without pydantic, so it keeps its own copies of the
schema vocabulary. These tests fail if a copy drifts from common/schemas.py."""

from typing import get_args

from common.schemas import QOS_QUEUE_IDS, RATE_LIMIT_MIN_MBPS, AppClass, ScenarioEvent
from testbed import qos, scenario_plan
from testbed.traffic import profiles


def test_traffic_classes_match_the_schema() -> None:  # scenario_plan imports this copy
    assert set(profiles.APP_CLASSES) == set(get_args(AppClass))


def test_event_types_match_the_schema() -> None:
    event_type = ScenarioEvent.model_fields["type"].annotation
    assert set(scenario_plan.EVENT_TYPES) == set(get_args(event_type))


def test_qos_queues_and_rate_limit_floor_match_the_schema() -> None:
    assert qos.QOS_QUEUE_IDS == QOS_QUEUE_IDS
    assert qos.RATE_LIMIT_MIN_MBPS == RATE_LIMIT_MIN_MBPS
