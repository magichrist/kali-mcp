"""Comprehensive unit tests for ``src/kali_mcp/tools/agent_interface.py``.

Covers every registered tool's input schema, validation (happy + error paths),
execution (happy + error paths with all external calls mocked), the
``assessment_run`` workflow branches, ``report_generate`` formats, vault
read/write/query paths, remediation mapping, playbook helpers, and error
handling.

All database, vault, playbook-engine, registry, execution-engine, and
assessment-context calls are mocked so tests are deterministic and fast.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from kali_mcp.models import ExecutionResult, utc_now_iso
from kali_mcp.tools.agent_interface import (
    AGENT_MODE_TOOLS,
    EXPERT_MODE_TOOLS,
    TOOL_LAYERS,
    AssessmentDiffTool,
    AssessmentRunTool,
    AssetGraphTool,
    BatchRunTool,
    CoverageSummaryTool,
    EvidenceGetTool,
    FindingsQueryTool,
    FindingTransitionTool,
    JobControlTool,
    ReportGenerateTool,
    ToolCatalogTool,
    _extract_assets_from_findings,
    _make_assessment_result,
    _new_id,
    _normalize_output_level,
    _now_utc,
)

# ── helpers ──────────────────────────────────────────────────────────────


def _payload(res: dict):
    """Decode an MCP tool response into the inner payload.

    ``result.to_dict()["stdout"]`` is either a JSON string (json/sarif/stix
    formats, most execute() results) or a raw string (markdown/html/pdf/csv
    reports). Return the decoded object when it is JSON, otherwise the raw
    string.
    """
    text = res["content"][0]["text"]
    outer = json.loads(text)
    stdout = outer.get("stdout")
    if stdout is None:
        return outer
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return stdout


def _exec_result(stdout="{}"):
    return ExecutionResult(
        tool="t",
        command="t",
        stdout=json.dumps(stdout) if not isinstance(stdout, str) else stdout,
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.0,
        start_time=utc_now_iso(),
        end_time=utc_now_iso(),
    )


# ── fakes ────────────────────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def execute(self, sql, params=()):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, rows_by_sql=None):
        self.rows_by_sql = rows_by_sql or {}
        self.executed = []
        self.committed = False

    def execute(self, sql, params=()):
        self.executed.append((sql, params or ()))
        for needle, rows in self.rows_by_sql.items():
            if needle in sql:
                return FakeCursor(rows)
        return FakeCursor([])

    def commit(self):
        self.committed = True

    def close(self):
        pass


class FakeDB:
    def __init__(
        self,
        *,
        query_findings=None,
        get_evidence=None,
        get_asset_graph=None,
        conn=None,
        upsert_target_return=1,
    ):
        self.query_findings_result = query_findings or {"findings": [], "count": 0}
        self.get_evidence_result = get_evidence
        self.get_asset_graph_result = get_asset_graph or {
            "assets": [],
            "relationships": [],
        }
        self.conn = conn or FakeConn()
        self.upsert_target_return = upsert_target_return
        self.upsert_calls = []

    def query_findings(self, **kwargs):
        return dict(self.query_findings_result)

    def get_evidence(self, evidence_id):
        return self.get_evidence_result

    def get_asset_graph(self, target=None):
        return dict(self.get_asset_graph_result)

    def upsert_target(self, target, target_type="host", scope="in-scope"):
        self.upsert_calls.append((target, target_type, scope))
        return self.upsert_target_return


class FakeCatalogTool:
    def __init__(self, name, description, timeout=30):
        self.name = name
        self.description = description
        self._timeout = timeout

    def input_schema(self):
        return {"type": "object", "properties": {}}

    @property
    def default_timeout(self):
        return self._timeout


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def patch_db(monkeypatch):
    """Patch ``dbm.get_db`` to return the supplied FakeDB (or None)."""

    def install(db):
        monkeypatch.setattr("kali_mcp.tools.agent_interface.dbm.get_db", lambda: db)
        return db

    return install


@pytest.fixture()
def patch_vault(monkeypatch):
    """Patch vault helpers used by agent_interface."""

    def install(query=None, read=None, write=None, can_access=None):
        if query is not None:
            monkeypatch.setattr("kali_mcp.tools.agent_interface.vault_query", query)
        if read is not None:
            monkeypatch.setattr("kali_mcp.tools.agent_interface.vault_read", read)
        if write is not None:
            monkeypatch.setattr("kali_mcp.tools.agent_interface.vault_write", write)
        if can_access is not None:
            monkeypatch.setattr("kali_mcp.tools.agent_interface.can_access", can_access)

    return install


@pytest.fixture()
def patch_context(monkeypatch):
    """Patch get_assessment_context (module global + identifiers source)."""

    def install(aid="assessment_abcdef123456", jid="job_abcdef123456"):
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.get_assessment_context",
            lambda: (aid, jid),
        )
        monkeypatch.setattr(
            "kali_mcp.identifiers.get_assessment_context",
            lambda: (aid, jid),
        )
        return aid, jid

    return install


@pytest.fixture()
def patch_playbook(monkeypatch):
    """Patch run_playbook_async to return an empty-step-results ExecutionResult."""

    def install(res=None):
        if res is None:
            res = _exec_result({"step_results": {}})
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.run_playbook_async",
            AsyncMock(return_value=res),
        )
        return res

    return install


@pytest.fixture()
def patch_registry(monkeypatch):
    """Patch registry.get / registry.list_all used by batch_run / tool_catalog."""

    def install(get_tool=None, list_all=None):
        if get_tool is not None:
            monkeypatch.setattr("kali_mcp.registry.registry.get", lambda name: get_tool)
        if list_all is not None:
            monkeypatch.setattr(
                "kali_mcp.registry.registry.list_all",
                lambda: list_all,
            )

    return install


@pytest.fixture()
def patch_engine(monkeypatch):
    """Patch engine.get_active_jobs / engine.kill_job."""

    def install(active_jobs=None, kill_result=True):
        if active_jobs is not None:
            monkeypatch.setattr(
                "kali_mcp.tools.agent_interface.engine.get_active_jobs",
                lambda: active_jobs,
            )
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.engine.kill_job",
            AsyncMock(return_value=kill_result),
        )

    return install


# ── module-level helpers ───────────────────────────────────────────────


class TestHelpers:
    def test_new_id_shape(self):
        aid = _new_id("assessment")
        assert aid.startswith("assessment_")
        assert len(aid) == len("assessment_") + 12

    def test_now_utc_ends_in_z(self):
        now = _now_utc()
        assert now.endswith("Z")
        # _now_utc() appends "Z" to an already-offset isoformat string.
        datetime.fromisoformat(now[:-1])  # strip trailing "Z" -> valid offset

    def test_normalize_output_level_valid(self):
        assert _normalize_output_level("full") == "full"
        assert _normalize_output_level("normal") == "normal"
        assert _normalize_output_level("summary") == "summary"

    def test_normalize_output_level_invalid_defaults_to_summary(self):
        assert _normalize_output_level("bogus") == "summary"
        assert _normalize_output_level("") == "summary"

    def test_make_assessment_result_without_job(self):
        res = _make_assessment_result(
            "assessment_run",
            "a1",
            "completed",
            {"assets_discovered": 1},
            [],
            ["review"],
        )
        payload = _payload(res)
        assert payload["assessment_id"] == "a1"
        assert payload["status"] == "completed"
        assert "job_id" not in payload
        assert payload["output_level"] == "summary"

    def test_make_assessment_result_with_job(self):
        res = _make_assessment_result(
            "assessment_run",
            "a1",
            "accepted",
            {},
            [],
            ["track"],
            job_id="j1",
            detail="full",
            raw_included=True,
        )
        payload = _payload(res)
        assert payload["job_id"] == "j1"
        assert payload["output_level"] == "full"
        assert payload["raw_included"] is True

    def test_extract_assets_from_findings(self):
        findings = [
            {"asset_id": "a1", "asset_name": "host1", "asset_type": "host", "severity": "high"},
            {"asset_id": "a1"},  # duplicate, skipped
            {"asset_id": "a2", "severity": "low"},
            {},  # no asset_id, skipped
        ]
        assets = _extract_assets_from_findings(findings)
        assert len(assets) == 2
        assert assets[0]["asset_id"] == "a1"
        assert assets[1]["asset_id"] == "a2"


# ── input schemas ────────────────────────────────────────────────────────


class TestInputSchemas:
    def test_assessment_run_schema(self):
        schema = AssessmentRunTool().input_schema()
        assert schema["type"] == "object"
        assert schema["required"] == ["workflow", "targets"]
        assert "workflow" in schema["properties"]
        assert "targets" in schema["properties"]

    def test_batch_run_schema(self):
        schema = BatchRunTool().input_schema()
        assert schema["required"] == ["operations"]

    def test_job_control_schema(self):
        schema = JobControlTool().input_schema()
        assert schema["required"] == ["job_id"]

    def test_findings_query_schema(self):
        schema = FindingsQueryTool().input_schema()
        assert "limit" in schema["properties"]
        assert "offset" in schema["properties"]

    def test_evidence_get_schema(self):
        schema = EvidenceGetTool().input_schema()
        assert schema["required"] == ["evidence_id"]

    def test_asset_graph_schema(self):
        schema = AssetGraphTool().input_schema()
        assert "relationship_type" in schema["properties"]

    def test_tool_catalog_schema(self):
        schema = ToolCatalogTool().input_schema()
        assert "layer" in schema["properties"]
        assert "mode" in schema["properties"]

    def test_report_generate_schema(self):
        schema = ReportGenerateTool().input_schema()
        assert schema["required"] == ["assessment_id"]

    def test_finding_transition_schema(self):
        schema = FindingTransitionTool().input_schema()
        assert schema["required"] == ["finding_id", "new_state"]

    def test_assessment_diff_schema(self):
        schema = AssessmentDiffTool().input_schema()
        assert schema["required"] == ["assessment_id_a", "assessment_id_b"]

    def test_coverage_summary_schema(self):
        schema = CoverageSummaryTool().input_schema()
        assert schema["required"] == ["assessment_id"]


# ── build_command / default_timeout / name ───────────────────────────────


class TestMetadata:
    def test_tool_names(self):
        assert AssessmentRunTool().name == "assessment_run"
        assert BatchRunTool().name == "batch_run"
        assert JobControlTool().name == "job_control"
        assert FindingsQueryTool().name == "findings_query"
        assert EvidenceGetTool().name == "evidence_get"
        assert AssetGraphTool().name == "asset_graph"
        assert ToolCatalogTool().name == "tool_catalog"
        assert ReportGenerateTool().name == "report_generate"
        assert FindingTransitionTool().name == "finding_transition"
        assert AssessmentDiffTool().name == "assessment_diff"
        assert CoverageSummaryTool().name == "coverage_summary"

    def test_build_commands(self):
        assert AssessmentRunTool().build_command({}) == ["assessment_run"]
        assert BatchRunTool().build_command({}) == ["batch_run"]
        assert JobControlTool().build_command({"job_id": "j1"}) == ["job_control", "j1"]
        assert EvidenceGetTool().build_command({"evidence_id": "e1"}) == ["evidence_get", "e1"]
        assert ReportGenerateTool().build_command({"assessment_id": "a1"}) == [
            "report_generate",
            "a1",
        ]

    def test_default_timeouts(self):
        assert AssessmentRunTool().default_timeout == 3600
        assert BatchRunTool().default_timeout == 3600
        assert JobControlTool().default_timeout == 120


# ── validate() ───────────────────────────────────────────────────────────


class TestValidateAssessmentRun:
    def test_valid_happy_path(self):
        AssessmentRunTool().validate(
            {
                "workflow": "web_assessment",
                "targets": ["example.test"],
            }
        )

    def test_valid_full(self):
        AssessmentRunTool().validate(
            {
                "workflow": "network_assessment",
                "targets": ["127.0.0.1"],
                "scope_id": "scope-1",
                "profile": "aggressive",
                "execution": {"max_parallel": 10, "max_duration": 600, "resume": True},
                "output": {"detail": "full", "include_raw": True},
            }
        )

    def test_missing_workflow(self):
        with pytest.raises(ValueError, match="workflow is required"):
            AssessmentRunTool().validate({"targets": ["x"]})

    def test_empty_targets(self):
        with pytest.raises(ValueError, match="targets must be a non-empty array"):
            AssessmentRunTool().validate({"workflow": "web_assessment", "targets": []})
        with pytest.raises(ValueError, match="targets must be a non-empty array"):
            AssessmentRunTool().validate({"workflow": "web_assessment", "targets": "notalist"})

    def test_invalid_profile(self):
        with pytest.raises(ValueError, match="profile must be"):
            AssessmentRunTool().validate(
                {
                    "workflow": "web_assessment",
                    "targets": ["x"],
                    "profile": "bogus",
                }
            )

    def test_bad_max_parallel(self):
        with pytest.raises(ValueError, match="max_parallel must be"):
            AssessmentRunTool().validate(
                {
                    "workflow": "w",
                    "targets": ["x"],
                    "execution": {"max_parallel": 0},
                }
            )
        with pytest.raises(ValueError, match="max_parallel must be"):
            AssessmentRunTool().validate(
                {
                    "workflow": "w",
                    "targets": ["x"],
                    "execution": {"max_parallel": 99},
                }
            )

    def test_bad_max_duration(self):
        with pytest.raises(ValueError, match="max_duration must be"):
            AssessmentRunTool().validate(
                {
                    "workflow": "w",
                    "targets": ["x"],
                    "execution": {"max_duration": 30},
                }
            )
        with pytest.raises(ValueError, match="max_duration must be"):
            AssessmentRunTool().validate(
                {
                    "workflow": "w",
                    "targets": ["x"],
                    "execution": {"max_duration": 9999},
                }
            )

    def test_bad_detail(self):
        with pytest.raises(ValueError, match="output.detail must be"):
            AssessmentRunTool().validate(
                {
                    "workflow": "w",
                    "targets": ["x"],
                    "output": {"detail": "xml"},
                }
            )


class TestValidateBatchRun:
    def test_valid(self):
        BatchRunTool().validate({"operations": [{"tool": "nmap"}]})

    def test_empty_ops(self):
        with pytest.raises(ValueError, match="operations must be a non-empty array"):
            BatchRunTool().validate({"operations": []})
        with pytest.raises(ValueError, match="operations must be a non-empty array"):
            BatchRunTool().validate({"operations": "x"})

    def test_op_missing_tool(self):
        with pytest.raises(ValueError, match="must have a 'tool' field"):
            BatchRunTool().validate({"operations": [{"target_ref": "x"}]})

    def test_bad_max_parallel(self):
        with pytest.raises(ValueError, match="max_parallel must be between"):
            BatchRunTool().validate({"operations": [{"tool": "nmap"}], "max_parallel": 0})
        with pytest.raises(ValueError, match="max_parallel must be between"):
            BatchRunTool().validate({"operations": [{"tool": "nmap"}], "max_parallel": 99})


class TestValidateJobControl:
    def test_valid(self):
        JobControlTool().validate({"job_id": "j1"})

    def test_missing_job_id(self):
        with pytest.raises(ValueError, match="job_id is required"):
            JobControlTool().validate({})

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="action must be"):
            JobControlTool().validate({"job_id": "j1", "action": "nuke"})

    def test_bad_timeout(self):
        with pytest.raises(ValueError, match="timeout must be between"):
            JobControlTool().validate({"job_id": "j1", "timeout": 0})
        with pytest.raises(ValueError, match="timeout must be between"):
            JobControlTool().validate({"job_id": "j1", "timeout": 9999})


class TestValidateFindingsQuery:
    def test_valid_defaults(self):
        FindingsQueryTool().validate({})

    def test_bad_limit(self):
        with pytest.raises(ValueError, match="limit must be between"):
            FindingsQueryTool().validate({"limit": 0})
        with pytest.raises(ValueError, match="limit must be between"):
            FindingsQueryTool().validate({"limit": 9999})

    def test_bad_offset(self):
        with pytest.raises(ValueError, match="offset must be a non-negative"):
            FindingsQueryTool().validate({"offset": -1})


class TestValidateEvidenceGet:
    def test_valid(self):
        EvidenceGetTool().validate({"evidence_id": "e1"})

    def test_missing_evidence_id(self):
        with pytest.raises(ValueError, match="evidence_id is required"):
            EvidenceGetTool().validate({})


class TestValidateAssetGraph:
    def test_valid(self):
        AssetGraphTool().validate({})

    def test_bad_limit(self):
        with pytest.raises(ValueError, match="limit must be between"):
            AssetGraphTool().validate({"limit": -5})


class TestValidateToolCatalog:
    def test_valid(self):
        ToolCatalogTool().validate({})
        ToolCatalogTool().validate({"mode": "expert", "layer": "discovery"})

    def test_bad_mode(self):
        with pytest.raises(ValueError, match="mode must be agent or expert"):
            ToolCatalogTool().validate({"mode": "god"})

    def test_bad_layer(self):
        with pytest.raises(ValueError, match="invalid layer"):
            ToolCatalogTool().validate({"layer": "nonsense"})


class TestValidateReportGenerate:
    def test_valid(self):
        ReportGenerateTool().validate({"assessment_id": "a1"})
        ReportGenerateTool().validate({"assessment_id": "a1", "format": "sarif"})

    def test_missing_assessment_id(self):
        with pytest.raises(ValueError, match="assessment_id is required"):
            ReportGenerateTool().validate({})

    def test_bad_format(self):
        with pytest.raises(ValueError, match="format must be"):
            ReportGenerateTool().validate({"assessment_id": "a1", "format": "xml"})


class TestValidateFindingTransition:
    def test_valid(self):
        FindingTransitionTool().validate({"finding_id": "f1", "new_state": "validated"})

    def test_missing_finding_id(self):
        with pytest.raises(ValueError, match="finding_id is required"):
            FindingTransitionTool().validate({"new_state": "validated"})

    def test_invalid_state(self):
        with pytest.raises(ValueError, match="new_state must be one of"):
            FindingTransitionTool().validate({"finding_id": "f1", "new_state": "weird"})


class TestValidateAssessmentDiff:
    def test_valid(self):
        AssessmentDiffTool().validate({"assessment_id_a": "a", "assessment_id_b": "b"})

    def test_missing_a(self):
        with pytest.raises(ValueError, match="assessment_id_a is required"):
            AssessmentDiffTool().validate({"assessment_id_b": "b"})

    def test_missing_b(self):
        with pytest.raises(ValueError, match="assessment_id_b is required"):
            AssessmentDiffTool().validate({"assessment_id_a": "a"})


class TestValidateCoverageSummary:
    def test_valid(self):
        CoverageSummaryTool().validate({"assessment_id": "a1"})

    def test_missing(self):
        with pytest.raises(ValueError, match="assessment_id is required"):
            CoverageSummaryTool().validate({})


# ── assessment_run execute() ─────────────────────────────────────────────


class TestAssessmentRunExecute:
    @pytest.mark.asyncio
    async def test_short_assessment_completed(
        self,
        patch_db,
        patch_vault,
        patch_context,
        patch_playbook,
    ):
        patch_db(None)  # no db -> skip persistence
        patch_vault(write=lambda *a, **k: None)
        patch_context(aid=None, jid=None)  # force _new_id fallback
        patch_playbook()

        tool = AssessmentRunTool()
        res = await tool.execute(
            {
                "workflow": "web_assessment",
                "targets": ["example.test"],
                "execution": {"max_duration": 60},  # <= 300 -> short (inline) path
            }
        )
        payload = _payload(res)
        assert payload["status"] == "completed"
        assert payload["assessment_id"].startswith("assessment_")
        assert payload["summary"]["assets_discovered"] == 0
        assert payload["findings"] == []
        assert "Use job_control" not in " ".join(payload["next_actions"])

    @pytest.mark.asyncio
    async def test_short_assessment_with_context_overrides_id(
        self,
        patch_db,
        patch_vault,
        patch_context,
        patch_playbook,
    ):
        patch_db(None)
        patch_vault(write=lambda *a, **k: None)
        patch_context(aid="ctx_assessment_111", jid="ctx_job_222")
        patch_playbook()

        tool = AssessmentRunTool()
        res = await tool.execute({"workflow": "web_assessment", "targets": ["example.test"]})
        payload = _payload(res)
        assert payload["assessment_id"] == "ctx_assessment_111"

    @pytest.mark.asyncio
    async def test_long_assessment_accepted(
        self,
        monkeypatch,
        patch_db,
        patch_vault,
        patch_context,
    ):
        patch_db(None)
        patch_vault(write=lambda *a, **k: None)
        patch_context()
        monkeypatch.setattr(
            AssessmentRunTool,
            "_run_assessment_background",
            AsyncMock(),
        )

        tool = AssessmentRunTool()
        res = await tool.execute(
            {
                "workflow": "network_assessment",
                "targets": ["a", "b", "c", "d"],
            }
        )
        payload = _payload(res)
        assert payload["status"] == "accepted"
        assert payload["job_id"].startswith("job_")
        assert payload["next_actions"][0].startswith("Assessment accepted")

    @pytest.mark.asyncio
    async def test_long_assessment_via_max_duration(
        self,
        monkeypatch,
        patch_db,
        patch_vault,
        patch_context,
    ):
        patch_db(None)
        patch_vault(write=lambda *a, **k: None)
        patch_context()
        monkeypatch.setattr(
            AssessmentRunTool,
            "_run_assessment_background",
            AsyncMock(),
        )

        tool = AssessmentRunTool()
        res = await tool.execute(
            {
                "workflow": "web_assessment",
                "targets": ["x"],
                "execution": {"max_duration": 600},  # > 300 -> long
            }
        )
        payload = _payload(res)
        assert payload["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_unknown_workflow_raises(
        self,
        patch_db,
        patch_vault,
        patch_context,
    ):
        patch_db(None)
        patch_vault()
        patch_context()

        tool = AssessmentRunTool()
        with pytest.raises(ValueError, match="Unknown workflow"):
            await tool.execute(
                {
                    "workflow": "not_a_workflow",
                    "targets": ["x"],
                    "execution": {"max_duration": 60},  # force inline path
                }
            )

    @pytest.mark.asyncio
    async def test_validate_error_propagates(
        self,
        patch_db,
        patch_vault,
        patch_context,
    ):
        patch_db(None)
        patch_vault()
        patch_context()

        tool = AssessmentRunTool()
        with pytest.raises(ValueError, match="workflow is required"):
            await tool.execute({"targets": ["x"]})

    @pytest.mark.asyncio
    async def test_db_persistence_branch(
        self,
        patch_db,
        patch_vault,
        patch_context,
        patch_playbook,
    ):
        db = FakeDB()
        patch_db(db)
        patch_vault(write=lambda *a, **k: None)
        patch_context()
        patch_playbook()

        tool = AssessmentRunTool()
        await tool.execute({"workflow": "web_assessment", "targets": ["t1.test"]})
        assert db.upsert_calls, "expected targets to be upserted"
        assert db.conn.committed

    def test_extract_findings_assets_report_step(self):
        tool = AssessmentRunTool()
        res = _exec_result(
            {
                "step_results": {
                    "report": {"report": {"findings": [{"id": "f1", "title": "T"}], "assets": []}},
                },
            }
        )
        findings, _assets = tool._extract_findings_assets(res)
        assert len(findings) == 1
        assert findings[0]["id"] == "f1"
        assert findings[0]["title"] == "T"

    def test_extract_findings_assets_correlate_fallback(self):
        tool = AssessmentRunTool()
        res = _exec_result(
            {
                "step_results": {
                    "correlate": {"correlated_findings": [{"id": "f2", "title": "C"}]},
                },
            }
        )
        findings, _ = tool._extract_findings_assets(res)
        assert len(findings) == 1
        assert findings[0]["id"] == "f2"

    def test_extract_findings_assets_json_decode_fallback(self):
        tool = AssessmentRunTool()
        res = _exec_result("{not json")
        findings, assets = tool._extract_findings_assets(res)
        assert findings == []
        assert assets == []

    def test_extract_findings_assets_last_resort(self):
        tool = AssessmentRunTool()
        res = _exec_result(
            {
                "step_results": {
                    "weird": {"findings": [{"title": "X"}]},
                    "other": {"assets": [{"asset_id": "ax"}]},
                },
            }
        )
        findings, assets = tool._extract_findings_assets(res)
        assert len(findings) == 1
        assert findings[0]["title"] == "X"
        assert len(assets) == 2  # "ax" from step + "unknown" normalized asset
        assert assets[0]["asset_id"] == "ax"

    def test_extract_findings_assets_normalization(self):
        tool = AssessmentRunTool()
        res = _exec_result(
            {
                "step_results": {
                    "report": {
                        "report": {
                            "findings": [
                                {
                                    "title": "Nuclei hit",
                                    "severity": "high",
                                    "confidence": 0.9,
                                    "source_tools": ["nuclei"],
                                    "evidence_refs": ["ev1"],
                                    "description": "d",
                                    "asset_id": "host.test",
                                }
                            ],
                        }
                    },
                },
            }
        )
        findings, assets = tool._extract_findings_assets(res)
        f = findings[0]
        assert f["id"].startswith("finding_")
        assert f["validation_status"] == "observed"
        assert "patch" in f["remediation"].lower()
        assert assets[0]["asset_id"] == "host.test"

    def test_remediation_for_branches(self):
        tool = AssessmentRunTool()
        assert "firewall" in tool._remediation_for({"source_tools": ["nmap"], "title": ""})
        assert "authentication" in tool._remediation_for(
            {"source_tools": ["katana"], "title": "endpoint"},
        )
        assert "parameter" in tool._remediation_for(
            {"source_tools": ["arjun"], "title": "parameter"},
        )
        assert "patch" in tool._remediation_for(
            {"source_tools": ["nuclei"], "title": "vuln"},
        )
        assert "subdomain" in tool._remediation_for(
            {"source_tools": ["subfinder"], "title": "subdomain"},
        )
        assert "Kerberos" in tool._remediation_for(
            {"source_tools": ["enum4linux"], "title": "x"},
        )
        assert "firewall" in tool._remediation_for({"source_tools": [], "title": "open port"})
        assert "vendor-recommended" in tool._remediation_for(
            {"source_tools": [], "title": "something odd"},
        )

    def test_default_next_actions(self):
        tool = AssessmentRunTool()
        actions = tool._default_next_actions("web_assessment")
        assert isinstance(actions, list) and len(actions) == 3
        assert "web_assessment" in actions[2]

    def test_write_assessment_vault_summary_swallows_errors(self, patch_vault):
        patch_vault(write=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        tool = AssessmentRunTool()
        tool._write_assessment_vault_summary(
            assessment_id="a1",
            job_id=None,
            status="completed",
            summary={},
            findings=[],
            next_actions=[],
            targets=["x"],
        )

    def test_load_workflow_playbook_known(self):
        tool = AssessmentRunTool()
        pb = tool._load_workflow_playbook("web_assessment")
        assert pb is not None

    def test_load_workflow_playbook_unknown(self):
        tool = AssessmentRunTool()
        with pytest.raises(ValueError, match="Unknown workflow"):
            tool._load_workflow_playbook("totally_fake_workflow")

    @pytest.mark.asyncio
    async def test_background_run_stores_failed_on_exception(
        self,
        monkeypatch,
        patch_vault,
    ):
        patch_vault(write=lambda *a, **k: None)
        monkeypatch.setattr(
            AssessmentRunTool,
            "_run_assessment_inline",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        tool = AssessmentRunTool()
        await tool._run_assessment_background(
            "a1",
            "j1",
            "web_assessment",
            ["x"],
            None,
            "safe_active",
            4,
            900,
            False,
            "summary",
            False,
        )


# ── batch_run execute() ──────────────────────────────────────────────────


class TestBatchRunExecute:
    @pytest.mark.asyncio
    async def test_happy_path_all_success(self, monkeypatch, patch_registry):
        fake_tool = type(
            "FT",
            (),
            {
                "safe_execute": AsyncMock(return_value={"content": [], "isError": False}),
            },
        )()
        patch_registry(get_tool=fake_tool)

        tool = BatchRunTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute(
            {
                "operations": [
                    {"tool": "nmap", "target_ref": "t1", "args": {"x": 1}},
                    {"tool": "nmap", "target_ref": "t2", "args": {"x": 1}},  # duplicate
                ],
            }
        )
        payload = _payload(res)
        assert payload["batch_id"].startswith("batch_")
        assert payload["total_operations"] == 2
        assert payload["unique_operations"] == 1
        assert payload["duplicates_skipped"] == 1
        assert payload["successful"] == 1
        assert payload["failed"] == 0

    @pytest.mark.asyncio
    async def test_unknown_tool(self, monkeypatch, patch_registry):
        patch_registry(get_tool=None)  # registry.get returns None

        tool = BatchRunTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"operations": [{"tool": "nope"}]})
        payload = _payload(res)
        r = payload["results"][0]
        assert r["error"] == "unknown tool"
        assert r.get("success") is None

    @pytest.mark.asyncio
    async def test_tool_exception(self, monkeypatch, patch_registry):
        fake_tool = type(
            "FT",
            (),
            {
                "safe_execute": AsyncMock(side_effect=RuntimeError("kaboom")),
            },
        )()
        patch_registry(get_tool=fake_tool)

        tool = BatchRunTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute(
            {
                "operations": [{"tool": "nmap"}],
                "continue_on_error": False,
            }
        )
        payload = _payload(res)
        assert payload["failed"] == 1
        assert payload["successful"] == 0
        outer = json.loads(res["content"][0]["text"])
        assert outer["success"] is False


# ── job_control execute() ────────────────────────────────────────────────


class TestJobControlExecute:
    @pytest.mark.asyncio
    async def test_not_found_engine_running(
        self,
        monkeypatch,
        patch_vault,
        patch_engine,
    ):
        patch_vault(query=lambda **k: {"entries": []})
        patch_engine(active_jobs=[{"request_id": "j1", "tool": "nmap", "elapsed_seconds": 2.0}])

        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "status"})
        payload = _payload(res)
        assert payload["status"] == "running"
        assert payload["tool"] == "nmap"

    @pytest.mark.asyncio
    async def test_not_found_not_found(self, monkeypatch, patch_vault, patch_engine):
        patch_vault(query=lambda **k: {"entries": []})
        patch_engine(active_jobs=[])

        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "missing", "action": "status"})
        payload = _payload(res)
        assert payload["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_vault_query_exception(self, monkeypatch, patch_engine):
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.vault_query",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        patch_engine(active_jobs=[])

        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "status"})
        payload = _payload(res)
        assert payload["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_status_access_denied(self, monkeypatch, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: False,
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "status"})
        outer = json.loads(res["content"][0]["text"])
        assert res["isError"] is True or "access denied" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_status_not_completed(self, monkeypatch, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps({"status": "accepted", "assessment_id": "a1"}),
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "status"})
        payload = _payload(res)
        assert payload["status"] == "accepted"
        assert payload["assessment_id"] == "a1"
        assert "result" not in payload

    @pytest.mark.asyncio
    async def test_status_completed_with_result(self, monkeypatch, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(
                {
                    "status": "completed",
                    "assessment_id": "a1",
                    "summary": {},
                }
            ),
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "status"})
        payload = _payload(res)
        assert payload["status"] == "completed"
        assert payload["result"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_status_vault_read_exception(self, monkeypatch, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: (_ for _ in ()).throw(RuntimeError("read fail")),
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "status"})
        payload = _payload(res)
        assert payload["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_wait_completes_first_poll(self, monkeypatch, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps({"status": "completed", "assessment_id": "a1"}),
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "wait", "timeout": 5})
        payload = _payload(res)
        assert payload["status"] == "completed"

    @pytest.mark.asyncio
    async def test_wait_timeout(self, monkeypatch, patch_vault):
        class FakeLoop:
            def __init__(self):
                self.t = 0.0

            def time(self):
                self.t += 100
                return self.t

        loop = FakeLoop()
        monkeypatch.setattr("asyncio.get_event_loop", lambda: loop)
        monkeypatch.setattr("asyncio.sleep", AsyncMock())
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps({"status": "accepted"}),
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "wait", "timeout": 1})
        payload = _payload(res)
        assert payload["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_wait_access_denied(self, monkeypatch, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "j1"}]},
            can_access=lambda aid, caller_id=None: False,
        )
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "wait", "timeout": 1})
        outer = json.loads(res["content"][0]["text"])
        assert "access denied" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_cancel_killed(self, monkeypatch, patch_vault, patch_engine):
        patch_vault(query=lambda **k: {"entries": [{"name": "j1"}]})
        patch_engine(kill_result=True)

        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "cancel"})
        payload = _payload(res)
        assert payload["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_not_killed(self, monkeypatch, patch_vault, patch_engine):
        patch_vault(query=lambda **k: {"entries": [{"name": "j1"}]})
        patch_engine(kill_result=False)

        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "cancel"})
        payload = _payload(res)
        assert payload["status"] == "not_found_or_already_done"

    @pytest.mark.asyncio
    async def test_unknown_action(self, monkeypatch, patch_vault):
        patch_vault(query=lambda **k: {"entries": [{"name": "j1"}]})
        tool = JobControlTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"job_id": "j1", "action": "weird"})
        outer = json.loads(res["content"][0]["text"])
        assert res["isError"] is True or "unknown action" in json.dumps(outer).lower()


# ── findings_query execute() ─────────────────────────────────────────────


class TestFindingsQueryExecute:
    @pytest.mark.asyncio
    async def test_db_unavailable(self, patch_db):
        patch_db(None)
        tool = FindingsQueryTool()
        tool._skip_central_persist = True
        res = await tool.execute({"severity": "high"})
        outer = json.loads(res["content"][0]["text"])
        assert res["isError"] is True
        assert "database unavailable" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_happy_path(self, patch_db):
        db = FakeDB(query_findings={"findings": [{"id": "f1"}], "count": 1})
        patch_db(db)
        tool = FindingsQueryTool()
        tool._skip_central_persist = True
        res = await tool.execute({"target": "t", "limit": 10, "offset": 0})
        payload = _payload(res)
        assert payload["count"] == 1
        assert payload["limit"] == 10
        assert payload["offset"] == 0
        assert payload["findings"][0]["evidence_refs"] == []
        assert payload["findings"][0]["source_tools"] == []

    @pytest.mark.asyncio
    async def test_enrichment_adds_missing_keys(self, patch_db):
        db = FakeDB(query_findings={"findings": [{"id": "f1", "evidence_refs": None}], "count": 1})
        patch_db(db)
        tool = FindingsQueryTool()
        tool._skip_central_persist = True
        res = await tool.execute({})
        payload = _payload(res)
        assert payload["findings"][0]["evidence_refs"] == []
        assert payload["findings"][0]["source_tools"] == []


# ── evidence_get execute() ───────────────────────────────────────────────


class TestEvidenceGetExecute:
    @pytest.mark.asyncio
    async def test_db_path_with_file(self, patch_db, tmp_path):
        content_file = tmp_path / "ev.txt"
        content_file.write_text("raw evidence here")
        db = FakeDB(
            get_evidence={
                "content_path": str(content_file),
                "artifact_type": "text",
                "content_size": 100,
                "captured_at": "now",
                "tool": "nmap",
                "target": "t",
                "assessment_id": "a",
                "job_id": "j",
            }
        )
        patch_db(db)
        tool = EvidenceGetTool()
        tool._skip_central_persist = True
        res = await tool.execute({"evidence_id": "e1"})
        payload = _payload(res)
        assert payload["evidence_id"] == "e1"
        assert payload["content"] == "raw evidence here"
        assert payload["source_tool"] == "nmap"
        assert payload["truncated"] is False

    @pytest.mark.asyncio
    async def test_db_path_content_over_100kb_truncated(self, patch_db, tmp_path):
        content_file = tmp_path / "big.txt"
        content_file.write_text("x" * 100001)
        db = FakeDB(
            get_evidence={
                "content_path": str(content_file),
                "content_size": 100001,
            }
        )
        patch_db(db)
        tool = EvidenceGetTool()
        tool._skip_central_persist = True
        res = await tool.execute({"evidence_id": "e2"})
        payload = _payload(res)
        assert payload["truncated"] is True
        assert len(payload["content"]) == 100000

    @pytest.mark.asyncio
    async def test_db_path_file_missing(self, patch_db):
        db = FakeDB(get_evidence={"content_path": "/nonexistent/ev.txt"})
        patch_db(db)
        tool = EvidenceGetTool()
        tool._skip_central_persist = True
        res = await tool.execute({"evidence_id": "e3"})
        payload = _payload(res)
        assert payload["content"] == ""
        assert payload["truncated"] is False

    @pytest.mark.asyncio
    async def test_db_get_evidence_none(self, patch_db):
        db = FakeDB(get_evidence=None)
        patch_db(db)
        tool = EvidenceGetTool()
        tool._skip_central_persist = True
        res = await tool.execute({"evidence_id": "e4"})
        outer = json.loads(res["content"][0]["text"])
        assert "evidence not found" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_vault_fallback_success(self, patch_db, patch_vault):
        db = FakeDB(get_evidence=None)
        patch_db(db)
        patch_vault(read=lambda cat, name: "vault content")
        tool = EvidenceGetTool()
        tool._skip_central_persist = True
        res = await tool.execute({"evidence_id": "e5", "category": "c", "name": "n"})
        payload = _payload(res)
        assert payload["content"] == "vault content"
        assert payload["source_tool"] == "vault"

    @pytest.mark.asyncio
    async def test_vault_fallback_exception_then_not_found(self, patch_db, patch_vault):
        db = FakeDB(get_evidence=None)
        patch_db(db)
        patch_vault(read=lambda cat, name: (_ for _ in ()).throw(RuntimeError("vault down")))
        tool = EvidenceGetTool()
        tool._skip_central_persist = True
        res = await tool.execute({"evidence_id": "e6", "category": "c", "name": "n"})
        outer = json.loads(res["content"][0]["text"])
        assert "evidence not found" in json.dumps(outer).lower()


# ── asset_graph execute() ────────────────────────────────────────────────


class TestAssetGraphExecute:
    @pytest.mark.asyncio
    async def test_db_unavailable(self, patch_db):
        patch_db(None)
        tool = AssetGraphTool()
        tool._skip_central_persist = True
        res = await tool.execute({})
        json.loads(res["content"][0]["text"])
        assert res["isError"] is True

    @pytest.mark.asyncio
    async def test_happy_path_with_filters(self, patch_db):
        db = FakeDB(
            get_asset_graph={
                "assets": [
                    {"asset_id": "a1", "name": "n1", "type": "host"},
                    {"asset_id": "a2", "name": "n2", "type": "host"},
                ],
                "relationships": [
                    {"relationship": "resolves_to", "source": "a1", "target": "a2"},
                    {"relationship": "contains", "source": "a1", "target": "a3"},
                ],
            }
        )
        patch_db(db)
        tool = AssetGraphTool()
        tool._skip_central_persist = True
        res = await tool.execute(
            {
                "target": "example.test",
                "asset_id": "a1",
                "relationship_type": "resolves_to",
                "limit": 5,
            }
        )
        payload = _payload(res)
        assert payload["asset_count"] == 1
        assert payload["relationship_count"] == 1
        assert payload["assets"][0]["asset_id"] == "a1"
        assert payload["relationships"][0]["relationship"] == "resolves_to"


# ── tool_catalog execute() ───────────────────────────────────────────────


class TestToolCatalogExecute:
    @pytest.mark.asyncio
    async def test_agent_mode_filters_and_search(self, monkeypatch, patch_registry):
        tools = [
            FakeCatalogTool("subfinder", "subdomain discovery", 30),
            FakeCatalogTool("nmap", "network mapper", 60),
            FakeCatalogTool("generic_command", "run any command", 300),
        ]
        patch_registry(list_all=tools)

        tool = ToolCatalogTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"mode": "agent", "layer": "discovery", "search": "sub"})
        payload = _payload(res)
        names = [t["name"] for t in payload["tools"]]
        assert "subfinder" in names
        assert "nmap" not in names  # wrong layer
        assert "generic_command" not in names  # not agent mode
        assert payload["mode"] == "agent"
        assert payload["layer"] == "discovery"
        assert payload["total"] == 1

    @pytest.mark.asyncio
    async def test_expert_mode_includes_escape_hatch(self, monkeypatch, patch_registry):
        tools = [FakeCatalogTool("generic_command", "run any command", 300)]
        patch_registry(list_all=tools)
        tool = ToolCatalogTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"mode": "expert"})
        payload = _payload(res)
        assert payload["total"] == 1
        assert payload["tools"][0]["name"] == "generic_command"

    @pytest.mark.asyncio
    async def test_catalog_entry_shape(self, monkeypatch, patch_registry):
        tools = [FakeCatalogTool("nmap", "network mapper", 60)]
        patch_registry(list_all=tools)
        tool = ToolCatalogTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute({"mode": "agent", "layer": "operations"})
        payload = _payload(res)
        entry = payload["tools"][0]
        assert entry["name"] == "nmap"
        assert entry["layer"] == "operations"
        assert "input_schema" in entry
        assert entry["default_timeout"] == 60


# ── report_generate execute() ────────────────────────────────────────────


class TestReportGenerateExecute:
    @pytest.fixture()
    def vault_data(self):
        return {
            "findings": [
                {
                    "id": "f1",
                    "title": "Exposed admin panel",
                    "severity": "critical",
                    "confidence": 0.9,
                    "validation_status": "validated",
                    "asset_id": "app.test",
                    "source_tools": ["nuclei"],
                    "evidence_refs": ["ev1"],
                    "description": "admin panel",
                },
            ],
            "summary": {
                "assets_discovered": 1,
                "services_discovered": 2,
                "findings": {"critical": 1, "high": 0, "medium": 0, "low": 0},
            },
            "next_actions": ["review"],
            "artifacts": [],
            "recommended_next_playbooks": [],
        }

    @pytest.mark.asyncio
    async def test_not_found(self, patch_vault):
        patch_vault(query=lambda **k: {"entries": []})
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "missing", "format": "json"})
        outer = json.loads(res["content"][0]["text"])
        assert "assessment not found" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_access_denied(self, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: False,
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "json"})
        outer = json.loads(res["content"][0]["text"])
        assert "access denied" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_json(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "json"})
        report = _payload(res)
        assert report["assessment_id"] == "a1"
        assert report["format"] == "json"
        assert len(report["findings"]) == 1
        assert report["findings"][0]["remediation"]

    @pytest.mark.asyncio
    async def test_markdown(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "markdown"})
        payload = _payload(res)
        assert "# Assessment Report" in payload
        assert "Exposed admin panel" in payload

    @pytest.mark.asyncio
    async def test_html(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "html"})
        payload = _payload(res)
        assert "<html" in payload.lower()
        assert "Exposed admin panel" in payload

    @pytest.mark.asyncio
    async def test_sarif(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "sarif"})
        sarif = _payload(res)
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"][0]["results"]) == 1

    @pytest.mark.asyncio
    async def test_pdf(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "pdf"})
        payload = _payload(res)
        assert "KALI-MCP ASSESSMENT REPORT" in payload

    @pytest.mark.asyncio
    async def test_csv(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "csv"})
        payload = _payload(res)
        assert "finding_id" in payload or "id" in payload
        assert "Exposed admin panel" in payload

    @pytest.mark.asyncio
    async def test_stix(self, patch_vault, vault_data):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: json.dumps(vault_data),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "stix"})
        stix = _payload(res)
        assert stix["type"] == "bundle"
        assert stix["assessment_id"] == "a1"

    @pytest.mark.asyncio
    async def test_vault_query_exception(self, patch_vault):
        patch_vault(query=lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "json"})
        outer = json.loads(res["content"][0]["text"])
        assert "assessment not found" in json.dumps(outer).lower()

    @pytest.mark.asyncio
    async def test_vault_read_exception(self, patch_vault):
        patch_vault(
            query=lambda **k: {"entries": [{"name": "a1"}]},
            can_access=lambda aid, caller_id=None: True,
            read=lambda cat, name: (_ for _ in ()).throw(RuntimeError("read fail")),
        )
        tool = ReportGenerateTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1", "format": "json"})
        payload = _payload(res)
        assert payload["format"] == "json"

    def test_base_report_directly(self):
        tool = ReportGenerateTool()
        base = tool._base_report(
            "a1",
            [{"title": "T", "severity": "high", "source_tools": ["nmap"]}],
            {"assets_discovered": 1},
            {"next_actions": ["act"], "artifacts": ["art"], "recommended_next_playbooks": ["pb"]},
            include_raw=True,
        )
        assert base["assessment_id"] == "a1"
        assert base["include_raw"] is True
        assert base["findings"][0]["remediation"]
        assert base["next_actions"] == ["act"]

    def test_remediation_for_branches(self):
        tool = ReportGenerateTool()
        assert "authentication" in tool._remediation_for({"title": "admin panel"})
        assert "TLS" in tool._remediation_for({"title": "tls cert"})
        assert "firewall" in tool._remediation_for({"title": "ssh access"})
        assert "parameterized" in tool._remediation_for({"title": "sql injection"})
        assert "output encoding" in tool._remediation_for({"title": "xss flaw"})
        assert "Monitor" in tool._remediation_for({"title": "odd thing", "severity": "low"})
        r = tool._remediation_for({"title": "critical x", "severity": "critical"})
        assert "least-privilege" in r

    def test_sarif_report_shape(self):
        tool = ReportGenerateTool()
        base = tool._base_report("a1", [], {}, {}, False)
        sarif = tool._sarif_report(
            "a1", [{"id": "f1", "title": "T", "severity": "critical"}], {}, base
        )
        assert sarif["version"] == "2.1.0"
        assert sarif["runs"][0]["results"][0]["level"] == "error"
        assert sarif["runs"][0]["results"][0]["ruleId"] == "f1"

    def test_pdf_report_shape(self):
        tool = ReportGenerateTool()
        base = tool._base_report("a1", [], {}, {}, False)
        pdf = tool._pdf_report("a1", [{"id": "f1", "title": "T"}], {}, base)
        assert "KALI-MCP ASSESSMENT REPORT" in pdf
        assert "f1" in pdf

    def test_csv_report_shape(self):
        tool = ReportGenerateTool()
        base = tool._base_report("a1", [], {}, {}, False)
        csv_out = tool._csv_report("a1", [{"id": "f1", "title": "T"}], base)
        assert "finding_id" in csv_out
        assert "T" in csv_out

    def test_stix_report_shape(self):
        tool = ReportGenerateTool()
        base = tool._base_report("a1", [], {}, {}, False)
        stix = tool._stix_report("a1", [{"id": "f1", "title": "T"}], {}, base)
        assert stix["type"] == "bundle"
        types = [o["type"] for o in stix["objects"]]
        assert "identity" in types and "indicator" in types

    def test_markdown_report_shape(self):
        tool = ReportGenerateTool()
        base = tool._base_report("a1", [], {}, {}, False)
        md = tool._markdown_report("a1", [{"id": "f1", "title": "T"}], {}, base)
        assert "# Assessment Report" in md

    def test_html_report_shape(self):
        tool = ReportGenerateTool()
        base = tool._base_report("a1", [], {}, {}, False)
        html = tool._html_report("a1", [{"id": "f1", "title": "T"}], {}, base)
        assert "<html" in html.lower()
        assert "f1" in html


# ── finding_transition execute() ─────────────────────────────────────────


class TestFindingTransitionExecute:
    @pytest.mark.asyncio
    async def test_db_none_previous_observed(self, patch_db):
        patch_db(None)
        tool = FindingTransitionTool()
        tool._skip_central_persist = True
        res = await tool.execute({"finding_id": "f1", "new_state": "validated"})
        payload = _payload(res)
        assert payload["success"] is False
        assert payload["previous_state"] == "observed"

    @pytest.mark.asyncio
    async def test_db_path_updates_state(self, patch_db):
        conn = FakeConn(
            rows_by_sql={
                "SELECT validation_status FROM findings WHERE id = ?": [("suspected",)],
            }
        )
        db = FakeDB(conn=conn)
        patch_db(db)
        tool = FindingTransitionTool()
        tool._skip_central_persist = True
        res = await tool.execute(
            {
                "finding_id": "f1",
                "new_state": "validated",
                "source": "analyst",
                "reason": "ok",
            }
        )
        payload = _payload(res)
        assert payload["success"] is True
        assert payload["previous_state"] == "suspected"
        assert payload["new_state"] == "validated"
        assert db.conn.committed

    @pytest.mark.asyncio
    async def test_invalid_transition(self, patch_db):
        patch_db(None)
        tool = FindingTransitionTool()
        tool._skip_central_persist = True
        res = await tool.execute({"finding_id": "f1", "new_state": "remediated"})
        payload = _payload(res)
        assert payload["success"] is False
        assert "Invalid transition" in payload["error"]

    @pytest.mark.asyncio
    async def test_db_exception_swallowed(self, patch_db):
        class ThrowingConn:
            def execute(self, sql, params=()):
                raise RuntimeError("db down")

            def commit(self):
                pass

        db = FakeDB(conn=ThrowingConn())
        patch_db(db)
        tool = FindingTransitionTool()
        tool._skip_central_persist = True
        res = await tool.execute({"finding_id": "f1", "new_state": "suspected"})
        payload = _payload(res)
        assert payload["success"] is True  # observed -> suspected allowed


# ── assessment_diff execute() ────────────────────────────────────────────


class TestAssessmentDiffExecute:
    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch, patch_db):
        patch_db(None)
        fake_diff = type(
            "FD",
            (),
            {
                "diff": lambda self, a, b: self,
                "to_dict": lambda self: {"new_findings": []},
            },
        )()
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.AssessmentDiffer",
            lambda db_manager=None: fake_diff,
        )
        tool = AssessmentDiffTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id_a": "a", "assessment_id_b": "b"})
        payload = _payload(res)
        assert payload["new_findings"] == []


# ── coverage_summary execute() ───────────────────────────────────────────


class TestCoverageSummaryExecute:
    @pytest.mark.asyncio
    async def test_db_none(self, patch_db, monkeypatch):
        patch_db(None)
        fake_tracker = type(
            "FT",
            (),
            {
                "get_coverage_summary": lambda self, aid: {"percent_covered": 0},
                "get_coverage_gaps": lambda self, aid: [],
            },
        )()
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.CoverageTracker",
            lambda: fake_tracker,
        )
        tool = CoverageSummaryTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1"})
        payload = _payload(res)
        assert payload["assessment_id"] == "a1"
        assert payload["summary"]["percent_covered"] == 0

    @pytest.mark.asyncio
    async def test_db_path_records_scans(self, patch_db, monkeypatch):
        conn = FakeConn(
            rows_by_sql={
                "SELECT id, tool, target_id FROM scans WHERE assessment_id = ?": [(1, "nmap", 10)],
                "SELECT id FROM findings WHERE scan_id = ?": [(1,), (2,)],
                "SELECT target FROM targets WHERE id = ?": [("127.0.0.1",)],
            }
        )
        db = FakeDB(conn=conn)
        patch_db(db)
        recorded = []
        fake_tracker = type(
            "FT",
            (),
            {
                "record_coverage": lambda self, **kwargs: recorded.append(kwargs),
                "get_coverage_summary": lambda self, aid: {"percent_covered": 50},
                "get_coverage_gaps": lambda self, aid: [],
            },
        )()
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.CoverageTracker",
            lambda: fake_tracker,
        )
        tool = CoverageSummaryTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1"})
        payload = _payload(res)
        assert payload["summary"]["percent_covered"] == 50
        assert recorded, "expected coverage records"
        assert recorded[0]["tool"] == "nmap"

    @pytest.mark.asyncio
    async def test_db_exception_swallowed(self, patch_db, monkeypatch):
        class ThrowingConn:
            def execute(self, sql, params=()):
                raise RuntimeError("down")

            def commit(self):
                pass

        db = FakeDB(conn=ThrowingConn())
        patch_db(db)
        fake_tracker = type(
            "FT",
            (),
            {
                "get_coverage_summary": lambda self, aid: {},
                "get_coverage_gaps": lambda self, aid: [],
            },
        )()
        monkeypatch.setattr(
            "kali_mcp.tools.agent_interface.CoverageTracker",
            lambda: fake_tracker,
        )
        tool = CoverageSummaryTool()
        tool._skip_central_persist = True
        res = await tool.execute({"assessment_id": "a1"})
        payload = _payload(res)
        assert "assessment_id" in payload


# ── safe_execute error wrapping ──────────────────────────────────────────


class TestSafeExecuteErrorWrapping:
    @pytest.mark.asyncio
    async def test_execute_exception_caught(
        self, monkeypatch, patch_db, patch_vault, patch_context
    ):
        patch_db(None)
        patch_vault(write=lambda *a, **k: None)
        patch_context()
        monkeypatch.setattr(
            AssessmentRunTool,
            "_run_assessment_inline",
            AsyncMock(side_effect=RuntimeError("unexpected")),
        )
        tool = AssessmentRunTool()
        tool._skip_central_persist = True
        res = await tool.safe_execute(
            {
                "workflow": "web_assessment",
                "targets": ["x"],
                "execution": {"max_duration": 60},  # short path -> _run_assessment_inline
            }
        )
        outer = json.loads(res["content"][0]["text"])
        assert res["isError"] is True
        assert "Internal error" in outer["error"]


# ── module-level collections ─────────────────────────────────────────────


class TestModuleCollections:
    def test_tool_layers_non_empty(self):
        assert isinstance(TOOL_LAYERS, dict) and len(TOOL_LAYERS) > 0
        assert TOOL_LAYERS["nmap"] == "operations"

    def test_agent_mode_subset(self):
        assert isinstance(AGENT_MODE_TOOLS, set)
        assert "assessment_run" in AGENT_MODE_TOOLS
        assert "generic_command" not in AGENT_MODE_TOOLS

    def test_expert_mode_everything(self):
        assert EXPERT_MODE_TOOLS == set(TOOL_LAYERS.keys())
