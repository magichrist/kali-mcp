"""Unit tests for the Phase 6 evaluation harness."""

from __future__ import annotations

import json
import tempfile

from kali_mcp.eval import (
    LAB_TARGETS,
    EvalSuite,
    GroundTruthFinding,
)


def test_lab_targets_defined():
    """Ground truth lab targets are defined."""
    assert "juice_shop" in LAB_TARGETS
    assert "dvwa" in LAB_TARGETS
    assert "metasploitable" in LAB_TARGETS


def test_ground_truth_finding():
    """A ground truth finding has expected fields."""
    gt = GroundTruthFinding(
        title="SQL injection",
        severity="high",
        asset="dvwa.lab",
        port=80,
        service="http",
        source_tool="sqlmap",
    )
    assert gt.title == "SQL injection"
    assert gt.severity == "high"
    assert gt.port == 80


def test_assessment_result_compute_metrics():
    """Metrics are computed correctly from calls and findings."""
    from datetime import datetime, timezone

    from kali_mcp.eval.harness import AssessmentResult, CallRecord

    now = datetime.now(timezone.utc).isoformat() + "Z"

    result = AssessmentResult(
        run_id="test_run",
        model_name="test-model",
        interface="v2",
        target="juice_shop",
        start_time=now,
        end_time=now,
        duration_s=5.0,
        calls=[
            CallRecord(
                call_id="c1",
                timestamp=now,
                tool="assessment_run",
                arguments={"workflow": "web_assessment", "targets": ["juice_shop"]},
                duration_s=5.0,
                success=True,
            )
        ],
        findings=[
            {"title": "Outdated AngularJS version", "severity": "medium"},
            {"title": "Open HTTP port 80", "severity": "informational"},
        ],
        completed=True,
    )

    gt = [
        GroundTruthFinding(
            title="Outdated AngularJS version",
            severity="medium",
            asset="juice_shop",
            source_tool="whatweb",
        ),
        GroundTruthFinding(
            title="SQL injection",
            severity="high",
            asset="dvwa.lab",
            source_tool="sqlmap",
        ),
    ]

    result.compute_metrics(gt)

    assert result.mcp_calls == 1
    assert result.invalid_calls == 0
    assert result.scope_violations == 0
    # 1 of 2 expected found (precision=1/2=0.5, recall=1/2=0.5)
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5


def test_eval_suite_write_results(tmp_path):
    """EvalSuite writes individual results and aggregate report."""
    suite = EvalSuite(output_dir=tmp_path)

    from datetime import datetime, timezone

    from kali_mcp.eval.harness import AssessmentResult, CallRecord

    now = datetime.now(timezone.utc).isoformat() + "Z"

    r1 = AssessmentResult(
        run_id="run_v1",
        model_name="small",
        interface="v1",
        target="juice_shop",
        start_time=now,
        end_time=now,
        duration_s=10.0,
        calls=[
            CallRecord(
                call_id="c1", timestamp=now, tool="nmap",
                arguments={"target": "juice_shop"}, duration_s=3.0, success=True
            ),
            CallRecord(
                call_id="c2", timestamp=now, tool="nuclei",
                arguments={"target": "juice_shop"}, duration_s=3.0, success=True
            ),
        ],
        findings=[{"title": "Open HTTP port 80"}],
        completed=True,
    )
    r1.compute_metrics(LAB_TARGETS["juice_shop"].expected_findings)

    r2 = AssessmentResult(
        run_id="run_v2",
        model_name="small",
        interface="v2",
        target="juice_shop",
        start_time=now,
        end_time=now,
        duration_s=3.0,
        calls=[
            CallRecord(
                call_id="c1", timestamp=now, tool="assessment_run",
                arguments={"workflow": "web_assessment", "targets": ["juice_shop"]},
                duration_s=3.0, success=True
            ),
        ],
        findings=[{"title": "Open HTTP port 80"}],
        completed=True,
    )
    r2.compute_metrics(LAB_TARGETS["juice_shop"].expected_findings)

    suite.results = [r1, r2]
    suite._write_aggregate_report([r1, r2])

    report_path = tmp_path / "aggregate_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["total_runs"] == 2
    assert "comparison" in report
    assert report["comparison"]["calls_reduction_percent"] > 0


def test_success_criteria():
    """Success criteria checker works."""
    suite = EvalSuite(output_dir=tempfile.mkdtemp())

    from datetime import datetime, timezone

    from kali_mcp.eval.harness import AssessmentResult, CallRecord

    now = datetime.now(timezone.utc).isoformat() + "Z"

    # v1: many calls, low completion
    r1 = AssessmentResult(
        run_id="v1_run", model_name="small", interface="v1", target="juice_shop",
        start_time=now, end_time=now, duration_s=10.0,
        calls=[CallRecord(call_id=f"c{i}", timestamp=now, tool="nmap",
                          arguments={"target": "x"}, duration_s=1.0, success=True)
               for i in range(10)],
        findings=[], completed=False,
    )
    r1.compute_metrics(LAB_TARGETS["juice_shop"].expected_findings)

    # v2: fewer calls, high completion
    r2 = AssessmentResult(
        run_id="v2_run", model_name="small", interface="v2", target="juice_shop",
        start_time=now, end_time=now, duration_s=3.0,
        calls=[CallRecord(call_id="c1", timestamp=now, tool="assessment_run",
                          arguments={"workflow": "w", "targets": ["x"]},
                          duration_s=3.0, success=True)],
        findings=[], completed=True,
    )
    r2.compute_metrics(LAB_TARGETS["juice_shop"].expected_findings)

    criteria = suite.check_success_criteria([r1, r2])
    assert criteria["mcp_calls_reduction"] is True
    assert criteria["task_completion_no_regression"] is True
    assert criteria["scope_violations_zero"] is True
