"""Unit tests for the playbook/module registry (src/kali_mcp/playbooks/registry.py)."""

from __future__ import annotations

from kali_mcp.playbooks.registry import (
    _modules,
    _playbooks,
    get_module,
    get_playbook,
    load_yaml_modules,
    load_yaml_playbooks,
    list_playbooks,
    register_module,
    register_playbook,
    ModuleNotFound,
    PlaybookNotFound,
)


def test_register_and_get_playbook():
    register_playbook("reg_pb_alpha", {"id": "reg_pb_alpha", "name": "Alpha", "steps": []})
    pb = get_playbook("reg_pb_alpha")
    assert pb["id"] == "reg_pb_alpha"
    assert pb["name"] == "Alpha"


def test_get_playbook_not_found():
    try:
        get_playbook("reg_pb_does_not_exist")
    except PlaybookNotFound:
        pass
    else:
        raise AssertionError("expected PlaybookNotFound")


def test_register_and_get_module():
    register_module("reg_mod_alpha", {"id": "reg_mod_alpha", "tool": "nmap"})
    mod = get_module("reg_mod_alpha")
    assert mod["id"] == "reg_mod_alpha"
    assert mod["tool"] == "nmap"


def test_get_module_not_found():
    try:
        get_module("reg_mod_does_not_exist")
    except ModuleNotFound:
        pass
    else:
        raise AssertionError("expected ModuleNotFound")


def test_playbook_not_found_is_keyerror():
    assert issubclass(PlaybookNotFound, KeyError)
    assert issubclass(ModuleNotFound, KeyError)


def test_register_playbook_overwrites():
    register_playbook("reg_pb_overwrite", {"id": "reg_pb_overwrite", "name": "v1"})
    register_playbook("reg_pb_overwrite", {"id": "reg_pb_overwrite", "name": "v2"})
    assert get_playbook("reg_pb_overwrite")["name"] == "v2"


def test_register_module_overwrites():
    register_module("reg_mod_overwrite", {"id": "reg_mod_overwrite", "tool": "a"})
    register_module("reg_mod_overwrite", {"id": "reg_mod_overwrite", "tool": "b"})
    assert get_module("reg_mod_overwrite")["tool"] == "b"


def test_list_playbooks_structure():
    register_playbook("reg_pb_list", {
        "id": "reg_pb_list",
        "name": "Listed",
        "description": "a listed playbook",
        "inputs": {"target": {"type": "string"}},
        "outputs": {},
        "execution": {"timeout": 120},
    })
    listed = list_playbooks()
    assert isinstance(listed, list)
    ids = {item["id"] for item in listed}
    assert "reg_pb_list" in ids
    item = next(i for i in listed if i["id"] == "reg_pb_list")
    assert item["name"] == "Listed"
    assert item["description"] == "a listed playbook"
    assert item["inputs"] == {"target": {"type": "string"}}
    assert item["estimated_duration"] == 120


def test_list_playbooks_item_keys():
    listed = list_playbooks()
    for item in listed:
        assert set(item.keys()) >= {
            "id", "name", "description", "inputs", "outputs", "estimated_duration",
        }


def test_load_yaml_playbooks_registers_definitions():
    load_yaml_playbooks()
    listed = {item["id"] for item in list_playbooks()}
    for expected in ("api_recon", "cloud_assessment", "container_assessment",
                     "custom_recon", "linux_assessment", "vulnerability_validation"):
        assert expected in listed
    pb = get_playbook("cloud_assessment")
    assert pb["id"] == "cloud_assessment"


def test_load_yaml_modules_registers_definitions():
    load_yaml_modules()
    assert len(_modules) > 0
    # every registered module is keyed by its own id
    for mod_id, mod in _modules.items():
        assert mod_id == mod.get("id")
    # a loaded module is retrievable by id
    any_id = next(iter(_modules))
    assert get_module(any_id) is _modules[any_id]


def test_load_yaml_playbooks_idempotent():
    load_yaml_playbooks()
    first = len(_playbooks)
    load_yaml_playbooks()
    assert len(_playbooks) == first
