"""Render nginx.conf from nginx.conf.tpl. Independent of the skillforge package."""

from pathlib import Path

PLACEHOLDER = "__UPSTREAM_PORT__"
DEFAULT_PORT = 8080
_DIR = Path(__file__).resolve().parent
TPL_PATH = _DIR / "nginx.conf.tpl"
CONF_PATH = _DIR / "nginx.conf"


def render(port: int) -> str:
    if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
        raise ValueError(f"upstream port must be a positive integer, got {port!r}")
    template = TPL_PATH.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(f"template missing {PLACEHOLDER}")
    return template.replace(PLACEHOLDER, str(port))


def write_conf(port: int = DEFAULT_PORT, dest: Path | None = None) -> Path:
    path = dest or CONF_PATH
    path.write_text(render(port), encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    write_conf(port)
