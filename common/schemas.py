"""Shared data contracts (P0.6). FROZEN after team approval: changes need an ADR (RULEBOOK rule 5).

Implements PROJECT_PLAN §7, trimmed to PHASE_PLAN v2.1 scope. Every model rejects unknown fields
and is immutable. Mac-side only (Python 3.11): the VM returns plain JSON, and the collector and API
validate it here on arrival (RULEBOOK C-2).

Bounds split for actions (PROJECT_PLAN §7.3):
- Static bounds (channel set, tx-power range, min rate, loop-free path, ...) are enforced HERE.
- State-dependent bounds (<= 30% of an AP's clients per steer, target RSSI >= -75 dBm, tx-power
  step <= 3 dB, never down the last AP covering a zone) need live state and are enforced by the
  verifier (twin/verify, P3.4).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------- vocabulary

Zone = Literal["lecture_hall", "lab", "corridor", "library"]  # = config/campus_v1.yaml zones
AppClass = Literal["video", "web", "bulk"]
Impact = Literal["low", "medium", "high"]
ActionSource = Literal["optimizer.heuristic", "llm.intent", "operator"]
SimMode = Literal["analytical", "gnn", "emulation"]
Priority = Literal["high", "normal", "low"]

APName = Annotated[str, Field(pattern=r"^ap[0-9]+$")]
StationName = Annotated[str, Field(pattern=r"^sta[0-9]+$")]
NodeName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=32)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=64)]
NonNeg = Annotated[float, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, le=100)]
Ratio = Annotated[float, Field(ge=0, le=1)]

CHANNELS_24GHZ: tuple[int, ...] = (1, 6, 11)
TX_POWER_DBM_MIN, TX_POWER_DBM_MAX = 5.0, 20.0
RATE_LIMIT_MIN_MBPS = 1.0
QOS_QUEUE_IDS: tuple[int, ...] = (0, 1, 2)  # 0 = best effort, 1 = priority, 2 = background


class Contract(BaseModel):
    """Base for all contracts: unknown fields rejected, instances immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- telemetry (§7.1)


class TelemetryRecord(Contract):
    """Fields common to every telemetry record."""

    ts: AwareDatetime
    scenario_id: Identifier
    run_id: Identifier


class PortStats(TelemetryRecord):
    """InfluxDB `port_stats`: one switch/AP port."""

    dpid: Identifier
    port: Annotated[int, Field(ge=0)]
    rx_bytes: Annotated[int, Field(ge=0)]
    tx_bytes: Annotated[int, Field(ge=0)]
    rx_pkts: Annotated[int, Field(ge=0)]
    tx_pkts: Annotated[int, Field(ge=0)]
    rx_dropped: Annotated[int, Field(ge=0)]
    tx_dropped: Annotated[int, Field(ge=0)]
    rx_bps: NonNeg
    tx_bps: NonNeg


class FlowStats(TelemetryRecord):
    """InfluxDB `flow_stats`: one OpenFlow flow entry."""

    dpid: Identifier
    flow_id: Identifier
    app_class: AppClass | None = None
    bytes: Annotated[int, Field(ge=0)]
    pkts: Annotated[int, Field(ge=0)]
    duration_s: NonNeg
    bps: NonNeg


class APStats(TelemetryRecord):
    """InfluxDB `ap_stats`: one access point."""

    ap: APName
    channel: int
    n_clients: Annotated[int, Field(ge=0)]
    channel_util: Ratio
    tx_power_dbm: float
    retries: NonNeg
    noise_dbm: float

    @field_validator("channel")
    @classmethod
    def _channel_known(cls, v: int) -> int:
        return _check_channel(v)


class StationStats(TelemetryRecord):
    """InfluxDB `sta_stats`: one station (ap is None when not associated)."""

    sta: StationName
    ap: APName | None
    rssi_dbm: float | None = None
    snr_db: float | None = None
    tx_bitrate_mbps: NonNeg | None = None
    rx_bitrate_mbps: NonNeg | None = None
    x: float
    y: float


class KPIRecord(TelemetryRecord):
    """InfluxDB `kpi`: measured end-to-end KPIs of one traffic flow."""

    flow_id: Identifier
    app_class: AppClass
    throughput_mbps: NonNeg
    latency_ms: NonNeg
    jitter_ms: NonNeg
    loss_pct: Percent


class AlertRecord(TelemetryRecord):
    """InfluxDB `alerts`: an anomaly detector finding."""

    detector: Identifier
    entity: NodeName
    score: float
    details: dict[str, Any] = Field(default_factory=dict)


MEASUREMENTS: dict[type[TelemetryRecord], str] = {
    PortStats: "port_stats",
    FlowStats: "flow_stats",
    APStats: "ap_stats",
    StationStats: "sta_stats",
    KPIRecord: "kpi",
    AlertRecord: "alerts",
}


# --------------------------------------------------------------------------- actions (§7.3)


class RerouteFlowParams(Contract):
    """Move a flow onto an explicit, loop-free node path."""

    flow_id: Identifier
    path: Annotated[list[NodeName], Field(min_length=2)]

    @field_validator("path")
    @classmethod
    def _loop_free(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("path must be loop-free (no repeated nodes)")
        return v


class QosMatch(Contract):
    """Which traffic a QoS queue applies to (at least one selector)."""

    zone: Zone | None = None
    app_class: AppClass | None = None
    flow_id: Identifier | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> QosMatch:
        if self.zone is None and self.app_class is None and self.flow_id is None:
            raise ValueError("QoS match needs at least one of zone, app_class, flow_id")
        return self


class SetQosQueueParams(Contract):
    """Put matching traffic into a pre-provisioned OVS queue."""

    match: QosMatch
    queue_id: int

    @field_validator("queue_id")
    @classmethod
    def _known_queue(cls, v: int) -> int:
        if v not in QOS_QUEUE_IDS:
            raise ValueError(f"queue_id must be one of {QOS_QUEUE_IDS}")
        return v


class RateLimitFlowParams(Contract):
    """Cap a flow's rate."""

    flow_id: Identifier
    max_mbps: Annotated[float, Field(ge=RATE_LIMIT_MIN_MBPS)]


class SteerClientsParams(Contract):
    """Move stations from one AP to another (state bounds checked by the verifier)."""

    from_ap: APName
    to_ap: APName
    stations: Annotated[list[StationName], Field(min_length=1)]

    @model_validator(mode="after")
    def _distinct(self) -> SteerClientsParams:
        if self.from_ap == self.to_ap:
            raise ValueError("from_ap and to_ap must differ")
        if len(set(self.stations)) != len(self.stations):
            raise ValueError("stations must be unique")
        return self


class SetApTxPowerParams(Contract):
    """Set an AP's transmit power (step size checked by the verifier)."""

    ap: APName
    dbm: Annotated[float, Field(ge=TX_POWER_DBM_MIN, le=TX_POWER_DBM_MAX)]


class SetApChannelParams(Contract):
    """Move an AP to another 2.4 GHz channel."""

    ap: APName
    channel: int

    @field_validator("channel")
    @classmethod
    def _channel_allowed(cls, v: int) -> int:
        return _check_channel(v)


class ApAdminStateParams(Contract):
    """Bring an AP up or down (last-AP-in-zone rule checked by the verifier)."""

    ap: APName
    state: Literal["up", "down"]


class _ActionBase(Contract):
    action_id: Annotated[str, Field(pattern=r"^act_[A-Za-z0-9_]+$", max_length=64)]
    source: ActionSource
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    created_at: AwareDatetime


class RerouteFlow(_ActionBase):
    """Allow-listed action: reroute_flow (impact low)."""

    type: Literal["reroute_flow"]
    params: RerouteFlowParams


class SetQosQueue(_ActionBase):
    """Allow-listed action: set_qos_queue (impact low)."""

    type: Literal["set_qos_queue"]
    params: SetQosQueueParams


class RateLimitFlow(_ActionBase):
    """Allow-listed action: rate_limit_flow (impact medium)."""

    type: Literal["rate_limit_flow"]
    params: RateLimitFlowParams


class SteerClients(_ActionBase):
    """Allow-listed action: steer_clients (impact medium)."""

    type: Literal["steer_clients"]
    params: SteerClientsParams


class SetApTxPower(_ActionBase):
    """Allow-listed action: set_ap_tx_power (impact medium)."""

    type: Literal["set_ap_tx_power"]
    params: SetApTxPowerParams


class SetApChannel(_ActionBase):
    """Allow-listed action: set_ap_channel (impact high)."""

    type: Literal["set_ap_channel"]
    params: SetApChannelParams


class ApAdminState(_ActionBase):
    """Allow-listed action: ap_admin_state (impact high)."""

    type: Literal["ap_admin_state"]
    params: ApAdminStateParams


Action = Annotated[
    RerouteFlow
    | SetQosQueue
    | RateLimitFlow
    | SteerClients
    | SetApTxPower
    | SetApChannel
    | ApAdminState,
    Field(discriminator="type"),
]
ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)

IMPACT: dict[str, Impact] = {
    "reroute_flow": "low",
    "set_qos_queue": "low",
    "rate_limit_flow": "medium",
    "steer_clients": "medium",
    "set_ap_tx_power": "medium",
    "set_ap_channel": "high",
    "ap_admin_state": "high",
}


def impact_of(action: Action) -> Impact:
    """Impact class of an action (PROJECT_PLAN §8)."""
    return IMPACT[action.type]


# --------------------------------------------------------------------------- policy (§7.4)

KPIName = Literal["throughput_mbps", "latency_ms", "jitter_ms", "loss_pct"]


class PolicyScope(Contract):
    """Which traffic a policy is about."""

    zone: Zone | None = None
    app_class: Annotated[list[AppClass], Field(min_length=1)] | None = None


class Objective(Contract):
    """A KPI target (`latency_ms <= 50`) or a priority (`priority = high`)."""

    kpi: KPIName | Literal["priority"]
    op: Literal["<=", ">=", "="]
    value: float | Priority

    @model_validator(mode="after")
    def _consistent(self) -> Objective:
        if self.kpi == "priority":
            if self.op != "=" or not isinstance(self.value, str):
                raise ValueError("priority objectives must be: priority = high|normal|low")
        elif self.op == "=" or isinstance(self.value, str):
            raise ValueError(f"{self.kpi} objectives need op <= or >= and a numeric value")
        elif self.value < 0:
            raise ValueError(f"{self.kpi} target must be >= 0")
        return self


class Constraint(Contract):
    """A hard KPI limit the verifier must never let an action violate."""

    kpi: KPIName
    op: Literal["<=", ">="]
    value: NonNeg
    scope: Literal["all", "policy"] = "policy"


class Validity(Contract):
    """Optional time window during which a policy is active."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    valid_from: AwareDatetime | None = Field(default=None, alias="from")
    until: AwareDatetime | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Validity:
        if self.valid_from and self.until and self.valid_from >= self.until:
            raise ValueError("valid.from must be before valid.until")
        return self


class Policy(Contract):
    """Structured policy produced from an operator intent (LLM output, validated here)."""

    policy_id: Annotated[str, Field(pattern=r"^pol_[a-z0-9_]+$", max_length=64)]
    intent_text: Annotated[str, Field(min_length=1, max_length=1000)]
    scope: PolicyScope
    objectives: Annotated[list[Objective], Field(min_length=1)]
    constraints: list[Constraint] = Field(default_factory=list)
    valid: Validity = Field(default_factory=Validity)
    created_by: Literal["llm.intent", "operator"]


# --------------------------------------------------------------------------- verdict (§7.5)


class KPIValues(Contract):
    """Network-level KPIs predicted by the twin or measured live."""

    throughput_mbps: NonNeg
    latency_ms: NonNeg
    loss_pct: Percent
    jain: Ratio


class Verdict(Contract):
    """Verifier decision for one action."""

    action_id: Annotated[str, Field(pattern=r"^act_[A-Za-z0-9_]+$", max_length=64)]
    accepted: bool
    predicted: KPIValues
    baseline: KPIValues
    violations: list[str] = Field(default_factory=list)
    impact: Impact
    needs_approval: bool
    sim_mode: SimMode
    sim_time_ms: NonNeg

    @model_validator(mode="after")
    def _consistent(self) -> Verdict:
        if self.accepted and self.violations:
            raise ValueError("an accepted verdict cannot have violations")
        if self.impact == "high" and not self.needs_approval:
            raise ValueError("high-impact actions always need approval (PROJECT_PLAN §8)")
        return self


# --------------------------------------------------------------------------- scenario (§7.6)


class CrowdGroup(Contract):
    """A group of stations walking from one zone to another."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    stations: Annotated[int, Field(gt=0)]
    from_zone: Zone = Field(alias="from")
    to_zone: Zone = Field(alias="to")
    start_s: NonNeg
    spread_s: NonNeg = 0.0

    @model_validator(mode="after")
    def _moves(self) -> CrowdGroup:
        if self.from_zone == self.to_zone:
            raise ValueError("crowd group must move between different zones")
        return self


class Mobility(Contract):
    """Station mobility for a scenario."""

    model: Literal["static", "scheduled_crowd"] = "static"
    groups: list[CrowdGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _groups_match_model(self) -> Mobility:
        if self.model == "static" and self.groups:
            raise ValueError("static mobility cannot have crowd groups")
        if self.model == "scheduled_crowd" and not self.groups:
            raise ValueError("scheduled_crowd needs at least one group")
        return self


class TrafficItem(Contract):
    """A traffic profile applied to a set of stations."""

    profile: AppClass
    stations: Annotated[str, Field(pattern=r"^(\*|[a-z_]+:\*|sta[0-9]+)$")]
    start_s: NonNeg = 0.0
    rate_mbps: Annotated[float, Field(gt=0)] | None = None


class ScenarioEvent(Contract):
    """A scripted event: AP failure/recovery or a forced channel (interference)."""

    at_s: NonNeg
    type: Literal["ap_down", "ap_up", "force_channel"]
    ap: APName
    channel: int | None = None

    @model_validator(mode="after")
    def _channel_iff_force(self) -> ScenarioEvent:
        if self.type == "force_channel":
            if self.channel is None:
                raise ValueError("force_channel needs a channel")
            _check_channel(self.channel)
        elif self.channel is not None:
            raise ValueError(f"{self.type} takes no channel")
        return self


class Scenario(Contract):
    """A scenario file (experiments/scenarios/*.yaml)."""

    scenario_id: Identifier
    duration_s: Annotated[float, Field(gt=0)]
    seed: int
    topology: Identifier
    mobility: Mobility = Field(default_factory=Mobility)
    traffic: list[TrafficItem] = Field(default_factory=list)
    events: list[ScenarioEvent] = Field(default_factory=list)
    labels: list[Literal["normal", "congestion", "ap_failure", "interference"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _within_duration(self) -> Scenario:
        times = [e.at_s for e in self.events] + [t.start_s for t in self.traffic]
        times += [g.start_s + g.spread_s for g in self.mobility.groups]
        if any(t > self.duration_s for t in times):
            raise ValueError("all events, traffic and crowd moves must happen within duration_s")
        return self


# --------------------------------------------------------------------------- helpers


def _check_channel(v: int) -> int:
    if v not in CHANNELS_24GHZ:
        raise ValueError(f"channel must be one of {CHANNELS_24GHZ}")
    return v
