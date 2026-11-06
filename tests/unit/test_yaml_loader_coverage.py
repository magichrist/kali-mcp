"""Extra coverage tests for the YAML playbook loader (workflow/yaml_loader.py).

Targets the StepDefinition validation branches, the _is_structured_condition
decision, load_playbook dict/file/legacy-tool paths, and load_module
(including the monkeypatched MODULES_DIR fallback).
"""

from __future__ import annotations

import yaml

import pytest

from kali_mcp.workflow.yaml_loader import (
    MODULES_DIR,
    PlaybookDefinition,
    PlaybookError,
    StepDefinition,
    _is_structured_condition,
    load_module,
    load_playbook,
)


class TestStepDefinitionValidation:
    def test_invalid_step_type_raises(self):
        with pytest.raises(PlaybookError, match="Invalid step type"):
            StepDefinition(id="s", type="bogus")

    def test_invalid_on_failure_raises(self):
        with pytest.raises(PlaybookError, match="Invalid on_failure"):
            StepDefinition(id="s", on_failure="nuke")

    def test_negative_retry_raises(self):
        with pytest.raises(PlaybookError, match="retry must be >= 0"):
            StepDefinition(id="s", retry=-1)

    def test_when_condition_must_be_structured(self):
        with pytest.raises(PlaybookError, match="structured outputs only"):
            StepDefinition(id="s", when="rm -rf /tmp")

    def test_valid_step_definition(self):
        step = StepDefinition(id="s", tool="nmap", when="resolve.count > 0")
        assert step.type == "tool"
        assert step.on_failure == "abort"
        assert step.retry == 0


class TestIsStructuredCondition:
    def test_dangerous_construct_returns_false(self):
        assert _is_structured_condition("$(id)") is False
        assert _is_structured_condition("`whoami`") is False
        assert _is_structured_condition("exec something") is False
        assert _is_structured_condition("import os") is False

    def test_valid_dotted_field_reference_returns_true(self):
        assert _is_structured_condition("resolve.http_services_count > 0") is True
        assert _is_structured_condition("httpx.http_services_count > 0") is True

    def test_no_field_reference_returns_false(self):
        # No dotted field path -> the final bool() is False (line 84).
        assert _is_structured_condition("1 > 0") is False
        assert _is_structured_condition(">>>") is False


class TestLoadPlaybook:
    def test_load_from_dict(self):
        data = {
            "name": "my-pb",
            "version": "2.0",
            "inputs": {"target": {"type": "string"}},
            "execution": {"max_parallel": 2},
            "steps": [
                {
                    "id": "scan",
                    "tool": "nmap",
                    "type": "tool",
                    "args": {"target": "{{inputs.target}}"},
                }
            ],
        }
        defn = load_playbook(data)
        assert isinstance(defn, PlaybookDefinition)
        assert defn.name == "my-pb"
        assert defn.version == "2.0"
        assert defn.max_parallel == 2
        assert len(defn.steps) == 1
        assert defn.steps[0].tool == "nmap"

    def test_load_from_yaml_file_path(self, tmp_path):
        pb = tmp_path / "pb.yaml"
        pb.write_text(
            "name: file-pb\nsteps:\n  - id: scan\n    tool: nmap\n    args: {target: example.com}\n",
            encoding="utf-8",
        )
        defn = load_playbook(str(pb))
        assert defn.name == "file-pb"
        assert defn.steps[0].tool == "nmap"

    def test_load_from_yaml_string(self):
        defn = load_playbook("name: str-pb\nsteps: []\n")
        assert defn.name == "str-pb"

    def test_load_non_mapping_raises(self):
        with pytest.raises(PlaybookError, match="must be a mapping"):
            load_playbook("just a string")

    def test_duplicate_step_id_raises(self):
        data = {
            "steps": [
                {"id": "s", "tool": "nmap"},
                {"id": "s", "tool": "nmap"},
            ]
        }
        with pytest.raises(PlaybookError, match="Duplicate step id"):
            load_playbook(data)

    def test_step_missing_id_raises(self):
        data = {"steps": [{"tool": "nmap"}]}
        with pytest.raises(PlaybookError, match="must have an id"):
            load_playbook(data)

    def test_legacy_tools_list_format(self):
        data = {
            "steps": [
                {
                    "id": "s",
                    "tools": [{"tool": "nmap", "args": {"target": "example.com"}}],
                }
            ]
        }
        defn = load_playbook(data)
        # The legacy tools branch resolves the tool; args are taken from the
        # step level (line 174), which is empty here.
        assert defn.steps[0].tool == "nmap"
        assert defn.steps[0].args == {}

    def test_module_field_is_preserved(self):
        data = {
            "steps": [
                {"id": "s", "module": "dns.resolve", "type": "custom", "args": {"target": "example.com"}}
            ]
        }
        defn = load_playbook(data)
        assert defn.steps[0].module == "dns.resolve"
        assert defn.steps[0].type == "custom"

    def test_defaults_applied(self):
        data = {"steps": [{"id": "s", "tool": "nmap"}]}
        defn = load_playbook(data)
        assert defn.steps[0].retry == 0
        assert defn.steps[0].on_failure == "abort"
        assert defn.steps[0].checkpoint is False
        assert defn.steps[0].parallel is False
        assert defn.steps[0].depends_on == []
        assert defn.steps[0].args == {}


class TestLoadModule:
    def _make_modules_dir(self, tmp_path, files):
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        for rel, content in files.items():
            p = modules_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return modules_dir

    def test_load_module_existing(self, tmp_path, monkeypatch):
        modules_dir = self._make_modules_dir(
            tmp_path,
            {"network/nmap.yaml": "id: nmap\ntool: nmap\ntimeout: 600\n"},
        )
        monkeypatch.setattr("kali_mcp.workflow.yaml_loader.MODULES_DIR", modules_dir)
        data = load_module("nmap")
        assert isinstance(data, dict)
        assert data["id"] == "nmap"
        assert data["tool"] == "nmap"

    def test_load_module_yml_extension(self, tmp_path, monkeypatch):
        modules_dir = self._make_modules_dir(
            tmp_path, {"web/katana.yml": "id: katana\ntool: katana\n"}
        )
        monkeypatch.setattr("kali_mcp.workflow.yaml_loader.MODULES_DIR", modules_dir)
        data = load_module("katana")
        assert data["id"] == "katana"

    def test_load_module_missing_returns_none(self, tmp_path, monkeypatch):
        modules_dir = self._make_modules_dir(tmp_path, {"network/nmap.yaml": "id: nmap\n"})
        monkeypatch.setattr("kali_mcp.workflow.yaml_loader.MODULES_DIR", modules_dir)
        assert load_module("does-not-exist") is None

    def test_load_module_empty_id_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kali_mcp.workflow.yaml_loader.MODULES_DIR", tmp_path / "modules")
        assert load_module("") is None

    def test_load_module_non_dict_yaml_returns_none(self, tmp_path, monkeypatch):
        modules_dir = self._make_modules_dir(tmp_path, {"network/nmap.yaml": "- a\n- b\n"})
        monkeypatch.setattr("kali_mcp.workflow.yaml_loader.MODULES_DIR", modules_dir)
        assert load_module("nmap") is None

    def test_module_uses_real_modules_dir_by_default(self):
        # The real package ships module YAML files; nmap should resolve.
        data = load_module("nmap")
        assert isinstance(data, dict)
        assert data["id"] == "nmap"
