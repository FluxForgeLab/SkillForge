"""C8.3 / C8.4: skillforge demo replay profile and live single-case switch."""

from __future__ import annotations

import pytest

from skillforge.cli import main
from skillforge.config import get_settings
from skillforge.demo.dod import DEMO_STEPS, resolve_demo_replay
from skillforge.runtime.agent import RunResult


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


def test_resolve_demo_replay_cli_overrides_live() -> None:
    assert resolve_demo_replay(cli_replay=True, demo_mode="live") is True
    assert resolve_demo_replay(cli_replay=False, demo_mode="live") is False
    assert resolve_demo_replay(cli_replay=False, demo_mode="replay") is True


def test_demo_mode_replay_default_without_flag_uses_replay_hook(capsys, monkeypatch) -> None:
    monkeypatch.delenv("SKILLFORGE_DEMO_MODE", raising=False)
    get_settings.cache_clear()
    live_calls: list[str] = []
    replay_calls: list[str] = []
    injected: list[str] = []

    code = main(
        ["demo"],
        inject=lambda fault_id: injected.append(fault_id),
        reset=lambda: None,
        verify=lambda: {"ok": True},
        live_runner=lambda: live_calls.append("live"),
        replay_runner=lambda: replay_calls.append("replay"),
    )
    capsys.readouterr()
    assert code == 0
    assert replay_calls == ["replay"]
    assert live_calls == []
    assert injected == ["nginx_bad_config_reload"]


def test_demo_mode_live_invokes_live_hook_once(capsys, monkeypatch) -> None:
    monkeypatch.setenv("SKILLFORGE_DEMO_MODE", "live")
    get_settings.cache_clear()
    live_calls: list[str] = []
    replay_calls: list[str] = []
    injected: list[str] = []

    code = main(
        ["demo"],
        inject=lambda fault_id: injected.append(fault_id),
        reset=lambda: None,
        verify=lambda: {"ok": True},
        live_runner=lambda: live_calls.append("live"),
        replay_runner=lambda: replay_calls.append("replay"),
    )
    out = capsys.readouterr().out
    assert code == 0
    for step in DEMO_STEPS:
        assert step in out, f"missing step {step!r} in stdout:\n{out}"
    assert live_calls == ["live"]
    assert replay_calls == []
    assert injected == ["backend_stopped"]


def test_demo_replay_flag_forces_replay_when_settings_live(capsys, monkeypatch) -> None:
    monkeypatch.setenv("SKILLFORGE_DEMO_MODE", "live")
    get_settings.cache_clear()
    live_calls: list[str] = []
    replay_calls: list[str] = []
    injected: list[str] = []

    code = main(
        ["demo", "--replay"],
        inject=lambda fault_id: injected.append(fault_id),
        reset=lambda: None,
        verify=lambda: {"ok": True},
        live_runner=lambda: live_calls.append("live"),
        replay_runner=lambda: replay_calls.append("replay"),
    )
    capsys.readouterr()
    assert code == 0
    assert replay_calls == ["replay"]
    assert live_calls == []
    assert injected == ["nginx_bad_config_reload"]


def test_demo_mode_live_uses_injected_harness_once(capsys, monkeypatch) -> None:
    monkeypatch.setenv("SKILLFORGE_DEMO_MODE", "live")
    get_settings.cache_clear()
    seen: list[tuple[str, str | None, str]] = []

    class FakeHarness:
        async def run(self, task: str, skill_path: str | None, workspace: str) -> RunResult:
            seen.append((task, skill_path, workspace))
            return RunResult(
                run_id="run_live_demo",
                status="completed",
                final_content="ok",
                steps=1,
                tool_errors=0,
                tokens=1,
                latency_ms=1,
                policy_violations=0,
            )

    code = main(
        ["demo"],
        inject=lambda _fault: None,
        reset=lambda: None,
        verify=lambda: {"ok": True},
        harness=FakeHarness(),
    )
    capsys.readouterr()
    assert code == 0
    assert len(seen) == 1
    assert "502" in seen[0][0] or "Restore" in seen[0][0]
    assert seen[0][1] is not None
    assert "service-recovery" in seen[0][1].replace("\\", "/")
