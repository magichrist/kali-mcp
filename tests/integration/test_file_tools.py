"""Integration tests for the file_read and file_write tools."""

from __future__ import annotations

import json


def parse_response(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


class TestFileRead:
    async def test_reads_existing_file(self):
        from tools.file_read import FileReadTool

        result = await FileReadTool().safe_execute({"path": "/etc/hosts"})
        data = parse_response(result)
        assert data["success"] is True
        assert len(data.get("stdout", "")) > 0

    async def test_missing_file_is_error(self):
        from tools.file_read import FileReadTool

        result = await FileReadTool().safe_execute({"path": "/nonexistent/file"})
        assert result["isError"] is True

    async def test_missing_path_is_error(self):
        from tools.file_read import FileReadTool

        assert (await FileReadTool().safe_execute({}))["isError"] is True

    async def test_max_bytes_truncates(self):
        from tools.file_read import FileReadTool

        result = await FileReadTool().safe_execute({"path": "/etc/hosts", "max_bytes": 5})
        data = parse_response(result)
        inner = json.loads(data["stdout"])
        assert inner["bytes_read"] <= 5


class TestFileWrite:
    async def test_write_and_verify_content(self, tmp_path):
        from tools.file_write import FileWriteTool

        path = str(tmp_path / "test_write.txt")
        result = await FileWriteTool().safe_execute({"path": path, "content": "hello world"})
        assert parse_response(result)["success"] is True
        assert (tmp_path / "test_write.txt").read_text() == "hello world"

    async def test_missing_path_is_error(self, tmp_path):
        from tools.file_write import FileWriteTool

        result = await FileWriteTool().safe_execute({"content": "x"})
        assert result["isError"] is True

    async def test_missing_content_is_error(self, tmp_path):
        from tools.file_write import FileWriteTool

        path = str(tmp_path / "f.txt")
        assert (await FileWriteTool().safe_execute({"path": path}))["isError"] is True
