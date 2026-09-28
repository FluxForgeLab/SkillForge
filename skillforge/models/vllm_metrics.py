"""Read measured vLLM Prometheus series. Missing series stay unset."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import httpx

_TOKEN_METRIC = "vllm:request_time_per_output_token_seconds"
_LINE = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)(?:\s+\d+)?$"
)
_LABEL = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"\\])*)"')


def metrics_url(base_url: str) -> str:
    """vLLM publishes /metrics beside /v1, not under it."""
    parts = urlsplit(base_url.strip())
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/metrics", "", ""))


def parse_tokens_per_second(text: str, model_name: str | None) -> float | None:
    """Cumulative tokens/s from the per-output-token histogram: count / sum.

    vLLM records seconds per output token. Dividing the histogram count by its
    sum is 1 / mean seconds, which is tokens/s since process start. A histogram
    for a different model_name is ignored. No samples yields None.
    """
    total_count = 0.0
    total_sum = 0.0
    saw = False
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        matched = _LINE.match(line.strip())
        if matched is None:
            continue
        name = matched.group("name")
        if name not in {f"{_TOKEN_METRIC}_count", f"{_TOKEN_METRIC}_sum"}:
            continue
        labels = _labels(matched.group("labels") or "")
        if not _model_matches(labels, model_name):
            continue
        try:
            value = float(matched.group("value"))
        except ValueError:
            continue
        saw = True
        if name.endswith("_count"):
            total_count += value
        else:
            total_sum += value
    if not saw or total_count <= 0 or total_sum <= 0:
        return None
    return total_count / total_sum


async def read_vllm_tokens_per_second(
    base_url: str,
    model_name: str,
    *,
    timeout: float = 2.0,
    client: httpx.AsyncClient | None = None,
) -> float | None:
    """Fetch /metrics. Network and HTTP failures return None."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(metrics_url(base_url))
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    finally:
        if owns_client:
            await http.aclose()
    return parse_tokens_per_second(response.text, model_name)


def _labels(raw: str) -> dict[str, str]:
    return {name: value.replace(r"\"", '"') for name, value in _LABEL.findall(raw)}


def _model_matches(labels: dict[str, str], model_name: str | None) -> bool:
    labeled = labels.get("model_name")
    if model_name and labeled is not None:
        return labeled == model_name
    return True
