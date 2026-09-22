from pathlib import Path

from skillforge.sandbox.docker import container_run_kwargs


def test_container_spec_mounts_only_workspace(tmp_path: Path) -> None:
    kwargs = container_run_kwargs(tmp_path, name="sbx-test")
    mounts = kwargs["mounts"]
    assert len(mounts) == 1
    assert mounts[0]["Target"] == "/workspace"
    assert mounts[0]["Type"] == "bind"
    source = str(mounts[0]["Source"]).replace("\\", "/")
    assert "docker.sock" not in source
    assert kwargs["network_mode"] == "bridge"
    assert kwargs["network_mode"] != "host"
    assert "ALL" in kwargs["cap_drop"]
    assert "ports" not in kwargs
    assert kwargs["user"] == "1000:1000"
    assert kwargs["read_only"] is True
    assert kwargs["extra_hosts"]["host.docker.internal"] == "host-gateway"
