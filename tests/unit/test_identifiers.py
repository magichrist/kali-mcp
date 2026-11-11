"""Unit tests for the assessment/job identifier module (kmcp/identifiers.py)."""

from __future__ import annotations

import re

from kmcp import identifiers


class TestGenerateAssessmentId:
    def test_format_is_opaque_uuid_based(self):
        aid = identifiers.generate_assessment_id()
        assert aid.startswith("assessment_")
        suffix = aid[len("assessment_") :]
        assert re.fullmatch(r"[0-9a-f]{12}", suffix)

    def test_unique_per_call(self):
        ids = {identifiers.generate_assessment_id() for _ in range(100)}
        assert len(ids) == 100


class TestGenerateJobId:
    def test_format_is_opaque_uuid_based(self):
        jid = identifiers.generate_job_id()
        assert jid.startswith("job_")
        suffix = jid[len("job_") :]
        assert re.fullmatch(r"[0-9a-f]{12}", suffix)

    def test_unique_per_call(self):
        ids = {identifiers.generate_job_id() for _ in range(100)}
        assert len(ids) == 100


class TestAssessmentContext:
    def test_set_and_get_context(self):
        tokens = identifiers.set_assessment_context("assessment_abc", "job_xyz")
        try:
            assert isinstance(tokens, dict)
            aid, jid = identifiers.get_assessment_context()
            assert aid == "assessment_abc"
            assert jid == "job_xyz"
        finally:
            identifiers.reset_assessment_context(tokens)

    def test_context_defaults_to_none(self):
        assert identifiers.get_assessment_context() == (None, None)

    def test_reset_restores_defaults(self):
        identifiers.set_assessment_context("assessment_1", "job_1")
        tokens = identifiers.set_assessment_context("assessment_2", "job_2")
        identifiers.reset_assessment_context(tokens)
        assert identifiers.get_assessment_context() == ("assessment_1", "job_1")

    def test_partial_context(self):
        # Set both, then override only assessment; job is preserved.
        tokens = identifiers.set_assessment_context("assessment_first", "job_first")
        try:
            assert identifiers.get_assessment_context() == (
                "assessment_first",
                "job_first",
            )
            tokens2 = identifiers.set_assessment_context(assessment_id="assessment_only")
            assert identifiers.get_assessment_context() == (
                "assessment_only",
                "job_first",
            )
        finally:
            identifiers.reset_assessment_context(tokens2)
            identifiers.reset_assessment_context(tokens)

    def test_reset_missing_keys_is_safe(self):
        identifiers.reset_assessment_context({})
