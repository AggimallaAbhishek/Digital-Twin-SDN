"""testbed/connectivity.py: ping parsing and the reachability + loss-budget verdict."""

import pytest

from testbed.connectivity import evaluate, ping_received

PING_OK = """PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=3.21 ms

--- 10.0.0.2 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
"""
PING_LOST = """PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.

--- 10.0.0.2 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""
PING_PARTIAL = "3 packets transmitted, 1 received, +2 errors, 66.6667% packet loss, time 2003ms\n"


@pytest.mark.parametrize(
    ("output", "expected"),
    [(PING_OK, True), (PING_LOST, False), (PING_PARTIAL, True), ("", False), ("garbage", False)],
)
def test_ping_received(output: str, expected: bool) -> None:
    assert ping_received(output) is expected


def _pairs(n: int) -> list[tuple[str, str]]:
    hosts = [f"h{i}" for i in range(n)]
    return [(a, b) for a in hosts for b in hosts if a != b]


def test_all_first_try_ok_passes_with_zero_loss() -> None:
    first = dict.fromkeys(_pairs(5), True)
    report = evaluate(first, {}, max_loss_pct=2.0)
    assert report.passed
    assert report.loss_pct == 0.0
    assert report.first_try_failures == []
    assert report.unreachable == []


def test_transient_loss_within_budget_passes() -> None:
    pairs = _pairs(11)  # 110 pairs
    first = dict.fromkeys(pairs, True)
    first[pairs[0]] = False
    first[pairs[1]] = False  # 2 / 110 = 1.8 %
    retry = {pairs[0]: True, pairs[1]: True}
    report = evaluate(first, retry, max_loss_pct=2.0)
    assert report.passed
    assert report.loss_pct == pytest.approx(100 * 2 / 110)
    assert report.first_try_failures == [pairs[0], pairs[1]]


def test_unreachable_pair_fails_even_within_budget() -> None:
    pairs = _pairs(11)
    first = dict.fromkeys(pairs, True)
    first[pairs[3]] = False
    report = evaluate(first, {pairs[3]: False}, max_loss_pct=2.0)
    assert not report.passed
    assert report.unreachable == [pairs[3]]


def test_loss_above_budget_fails_even_if_all_reachable() -> None:
    pairs = _pairs(5)  # 20 pairs
    first = dict.fromkeys(pairs, True)
    first[pairs[0]] = False  # 5 %
    report = evaluate(first, {pairs[0]: True}, max_loss_pct=2.0)
    assert not report.passed
    assert report.unreachable == []


def test_failed_pair_without_retry_result_counts_as_unreachable() -> None:
    pairs = _pairs(3)
    first = dict.fromkeys(pairs, True)
    first[pairs[0]] = False
    report = evaluate(first, {}, max_loss_pct=50.0)
    assert report.unreachable == [pairs[0]]
    assert not report.passed


def test_empty_matrix_is_rejected() -> None:
    with pytest.raises(ValueError, match="no ping results"):
        evaluate({}, {}, max_loss_pct=2.0)


def test_summary_line_is_greppable() -> None:
    first = dict.fromkeys(_pairs(3), True)
    line = evaluate(first, {}, max_loss_pct=2.0).summary(
        "CAMPUS_RESULT", assoc_ok=20, assoc_total=20
    )
    assert line.startswith("CAMPUS_RESULT assoc=20/20 reachable=6/6 loss=0.00% (budget 2.0%)")
    assert line.endswith("-> PASS")
