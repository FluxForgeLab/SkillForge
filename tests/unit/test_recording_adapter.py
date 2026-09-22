from pathlib import Path

from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.adapters.recording import RecordingAdapter
from skillforge.models.gateway import load_fake_script
from skillforge.models.types import ModelRequest, ModelResponse, ToolCall


def _request() -> ModelRequest:
    return ModelRequest(run_id="run_rec", messages=[])


async def test_recording_adapter_round_trips_tool_calls(tmp_path: Path) -> None:
    script = [
        ModelResponse(
            tool_calls=[
                ToolCall(id="c1", name="docker.inspect", arguments='{"service": "backend"}')
            ],
            finish_reason="tool_calls",
        ),
        ModelResponse(
            tool_calls=[
                ToolCall(
                    id="c2", name="http.get", arguments='{"url": "http://127.0.0.1:8088/health"}'
                )
            ],
            finish_reason="tool_calls",
        ),
    ]
    path = tmp_path / "transcript.json"
    adapter = RecordingAdapter(FakeModelAdapter(script), path)
    await adapter.generate(_request())
    await adapter.generate(_request())
    loaded = load_fake_script(path)
    assert [call.name for call in loaded[0].tool_calls] == ["docker.inspect"]
    assert loaded[0].tool_calls[0].arguments == '{"service": "backend"}'
    assert [call.name for call in loaded[1].tool_calls] == ["http.get"]


def test_f1_transcript_replays() -> None:
    path = Path("tests/fixtures/transcripts/f1-golden-openai.json")
    loaded = load_fake_script(path)
    names = [call.name for row in loaded for call in row.tool_calls]
    assert "docker.restart" in names
    assert loaded[-1].tool_calls == []
    assert loaded[-1].model == "kimi-k3"
