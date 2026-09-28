"""C8.3: skillforge demo --replay prints every DoD step and exits 0."""

from __future__ import annotations

from skillforge.cli import main
from skillforge.demo.dod import DEMO_STEPS


def test_demo_replay_prints_all_steps_and_exits_0(capsys) -> None:
    injected: list[str] = []
    resets: list[str] = []
    verifies: list[str] = []

    def fake_verify():
        verifies.append("verify")
        return {"ok": True}

    code = main(
        ["demo", "--replay"],
        inject=lambda fault_id: injected.append(fault_id),
        reset=lambda: resets.append("reset"),
        verify=fake_verify,
    )
    out = capsys.readouterr().out
    assert code == 0
    for step in DEMO_STEPS:
        assert step in out, f"missing step {step!r} in stdout:\n{out}"
    assert injected == ["nginx_bad_config_reload"]
    assert resets == ["reset"]
    assert verifies == ["verify"]
