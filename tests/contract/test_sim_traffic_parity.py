"""The twin's traffic assumptions (config/sim.yaml) must match the testbed's traffic profiles."""

from pathlib import Path

import yaml

from testbed.traffic.profiles import IperfProfile, load_traffic_config
from twin.sim.analytical import load_sim_params

ROOT = Path(__file__).resolve().parents[2]
SIM = load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text()))
TRAFFIC = load_traffic_config(
    yaml.safe_load((ROOT / "testbed" / "traffic" / "profiles.yaml").read_text())
)


def test_video_demand_is_the_profile_rate() -> None:
    video = TRAFFIC.profiles["video"]
    assert isinstance(video, IperfProfile)
    assert video.rate_mbps == SIM.video_mbps


def test_a_dead_flow_has_the_probe_timeout_as_latency() -> None:
    assert TRAFFIC.ping_timeout_s * 1000 == SIM.dead_latency_ms
