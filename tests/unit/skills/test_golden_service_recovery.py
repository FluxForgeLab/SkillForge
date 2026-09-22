from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_SKILL = _REPO / "skills" / "golden" / "service-recovery"
_CATALOG = _REPO / "demo" / "ops-lab" / "faults" / "catalog.yaml"
_VERIFY = _REPO / "demo" / "ops-lab" / "verifier" / "verify.py"

_REQUIRED = (
    "SKILL.md",
    "skill-card.md",
    "scripts/diagnose.py",
    "scripts/recover.py",
    "scripts/verify.py",
    "references/source-map.json",
    "evals/evals.json",
)
_TOOLS = {
    "docker.inspect",
    "docker.logs",
    "docker.restart",
    "nginx.read_config",
    "nginx.write_config",
    "nginx.test",
    "nginx.reload",
    "http.get",
}
_F1_TOOLS = ("docker.inspect", "docker.logs", "docker.restart", "http.get")
_PROCEDURE_IDS = {1, 2, 3, 4, 5, 6, 7}
_PROHIBITION_IDS = {20, 21, 22}
_FORBIDDEN_ACTIONS = ["delete_volume", "restart_database"]
_BODY_BANNED = ("nginx -t", "nginx.test", "this_is_not_valid_nginx")
_INS_RE = re.compile(r"^ins_(\d+)\s+(.*)$", re.MULTILINE)
_SCRIPT_NAMES = ("diagnose.py", "recover.py", "verify.py")
_STDLIB_IMPORTS = {"json", "sys"}


def _read(relative: str) -> str:
    return (_SKILL / relative).read_text(encoding="utf-8")


def _split_skill(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---\n", 2)
    loaded = yaml.safe_load(frontmatter)
    assert isinstance(loaded, dict)
    return loaded, body


def _instructions(body: str) -> dict[str, str]:
    found = {f"ins_{int(num):02d}": text.strip() for num, text in _INS_RE.findall(body)}
    assert found
    return found


def _verifier_fields() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("ops_lab_verifier", _VERIFY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.RESULT_FIELDS)


def _catalog_fixtures() -> set[str]:
    loaded = yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))
    return {item["fixture"] for item in loaded["faults"]}


def _script_tree(name: str) -> ast.AST:
    return ast.parse(_read(f"scripts/{name}"))


def test_required_files_exist() -> None:
    for relative in _REQUIRED:
        assert (_SKILL / relative).is_file(), relative


def test_frontmatter_contract() -> None:
    meta, _body = _split_skill(_read("SKILL.md"))
    assert meta["name"] == "service-recovery"
    assert meta["version"] == "0.1.0"
    description = meta["description"]
    assert isinstance(description, str)
    assert len(description) <= 1024
    assert set(meta["tools"]) == _TOOLS
    assert meta["permissions"]["shell"]["destructive_commands"] is False
    assert meta["permissions"]["filesystem"]["read"] == ["/workspace"]
    assert meta["permissions"]["filesystem"]["write"] == ["/workspace/runtime"]
    assert meta["permissions"]["network"]["allow"] == ["localhost"]


def test_instruction_ids_match_source_map() -> None:
    _meta, body = _split_skill(_read("SKILL.md"))
    instructions = _instructions(body)
    ids = {int(key.removeprefix("ins_")) for key in instructions}
    assert ids == _PROCEDURE_IDS | _PROHIBITION_IDS
    source_map = json.loads(_read("references/source-map.json"))
    assert set(source_map) == set(instructions)
    assert all(value == {} for value in source_map.values())


def test_f1_tool_order_and_body_omits_appendix_b() -> None:
    _meta, body = _split_skill(_read("SKILL.md"))
    instructions = _instructions(body)
    for banned in _BODY_BANNED:
        assert banned not in body
    found = []
    for index, tool in enumerate(_F1_TOOLS, start=1):
        text = instructions[f"ins_{index:02d}"]
        hits = [name for name in _F1_TOOLS if name in text]
        assert hits == [tool]
        found.append(tool)
    assert tuple(found) == _F1_TOOLS


def test_evals_match_catalog_and_verifier() -> None:
    cases = json.loads(_read("evals/evals.json"))
    assert len(cases) == 3
    fixtures = _catalog_fixtures()
    fields = _verifier_fields()
    seen = set()
    for case in cases:
        assert case["fixture"] in fixtures
        assert set(case["expected"]) == fields
        assert case["forbidden"] == _FORBIDDEN_ACTIONS
        assert case["timeout_sec"] == 180
        seen.add(case["fixture"])
    assert seen == fixtures


def test_scripts_are_opslab_only() -> None:
    for name in _SCRIPT_NAMES:
        tree = _script_tree(name)
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module != "__future__"
        ]
        assert modules == ["skillforge.runtime.tools.opslab"]
        imported = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert set(imported) <= _STDLIB_IMPORTS
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "system":
                value = node.value
                assert not (isinstance(value, ast.Name) and value.id == "os")
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "nginx_test" not in names
