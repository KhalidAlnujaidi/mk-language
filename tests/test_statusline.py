"""Tests for products/dashboard/statusline.py — the live status-line chips.

Pure functions over an EventRecord list (thesis #1); cost honesty per vision §4.6.
"""

from __future__ import annotations

from kernel.contracts import EventRecord
from products.dashboard.statusline import DEFAULT_CHIPS, build, render


def _ev(
    tier: str,
    *,
    tin: int | None = None,
    tout: int | None = None,
    exact: bool = True,
    correction_of: str | None = None,
) -> EventRecord:
    return EventRecord(
        task_id="t",
        kind="agent",
        tier=tier,
        tokens_in=tin,
        tokens_out=tout,
        tokens_exact=exact,
        correction_of=correction_of,
    )


def test_empty_is_all_zero() -> None:
    m = build([])
    assert m.events == 0
    assert m.tokens_in == 0 and m.tokens_out == 0
    assert m.cost_usd == 0.0
    assert m.cost_exact is True
    assert m.top_tier is None


def test_local_tokens_are_free_and_exact() -> None:
    m = build([_ev("model:local:llama", tin=1000, tout=500)])
    assert m.tokens_in == 1000 and m.tokens_out == 500
    assert m.cost_usd == 0.0
    assert m.cost_exact is True


def test_cloud_tokens_cost_and_mark_estimate() -> None:
    # 1e6 in @ $0.50 + 1e6 out @ $1.50 = $2.00
    m = build([_ev("model:cloud:glm", tin=1_000_000, tout=1_000_000, exact=False)])
    assert m.cost_usd == 2.0
    assert m.cost_exact is False


def test_deterministic_tier_has_no_cost() -> None:
    m = build([_ev("deterministic", tin=10, tout=10)])
    assert m.cost_usd == 0.0
    assert m.cost_exact is True


def test_top_tier_is_most_frequent() -> None:
    events = [_ev("model:local:a"), _ev("model:local:a"), _ev("deterministic")]
    assert build(events).top_tier == "model:local:a"


def test_correction_rate() -> None:
    events = [_ev("deterministic"), _ev("deterministic", correction_of="prev")]
    assert build(events).correction_rate == 0.5


# --- rendering --------------------------------------------------------------


def test_render_default_chips() -> None:
    events = [_ev("model:cloud:glm", tin=500_000, tout=0, exact=False)]
    line = render(events)
    assert " · " in line
    assert "cloud:glm" in line  # tier chip, shortened
    assert "1 ev" in line
    assert "tok" in line
    assert "~$" in line  # cloud cost marked as estimate


def test_render_respects_chip_order_and_skips_unknown() -> None:
    events = [_ev("model:local:a", tin=10, tout=5)]
    line = render(events, chips=("events", "nonsense", "tier"))
    # "nonsense" is dropped; order is events then tier.
    assert line == "1 ev · local:a"


def test_default_chips_cover_known_renderers() -> None:
    # Guards against a chip name in DEFAULT_CHIPS that has no renderer.
    line = render([_ev("deterministic")], chips=DEFAULT_CHIPS)
    assert line  # non-empty, no KeyError
