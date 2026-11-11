"""Tests for the ``open_paths`` exemption in ``TokenAuthMiddleware``.

Contract: the Playbook Studio static UI (``/studio`` and anything under
``/studio/*``) is served WITHOUT auth so a normal browser can load it, while
everything else — every ``/api/*`` route, the MCP endpoint, monitor endpoints
— still requires the bearer token.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from kmcp.server import TokenAuthMiddleware


def _scope(path: str, method: str = "GET") -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
    }


async def _run(mw: TokenAuthMiddleware, path: str, method: str = "GET") -> dict[str, Any]:
    """Run a request through the middleware; return summary of what happened."""
    scope = _scope(path, method)
    sent: list[dict[str, Any]] = []

    async def fake_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def fake_send(message):
        sent.append(message)

    await mw(scope, fake_receive, fake_send)
    status = next(
        (m["status"] for m in sent if m["type"] == "http.response.start"),
        None,
    )
    return {"forwarded": not sent, "status": status, "scope": scope}


TOKEN = "secret-token"


@pytest.fixture
def mw():
    return TokenAuthMiddleware(app=AsyncMock(), token=TOKEN, open_paths=("/studio",))


class TestOpenPathPassthrough:
    @pytest.mark.asyncio
    async def test_exact_studio_page_passes_without_token(self, mw) -> None:
        result = await _run(mw, "/studio")
        assert result["forwarded"]

    @pytest.mark.asyncio
    async def test_studio_asset_passes_without_token(self, mw) -> None:
        for path in ("/studio/", "/studio/app.js", "/studio/style.css"):
            result = await _run(mw, path)
            assert result["forwarded"], f"{path} should be open"

    @pytest.mark.asyncio
    async def test_head_requests_open_too(self, mw) -> None:
        result = await _run(mw, "/studio", method="HEAD")
        assert result["forwarded"]


class TestStillProtected:
    @pytest.mark.asyncio
    async def test_api_routes_require_token(self, mw) -> None:
        result = await _run(mw, "/api/playbooks")
        assert result["status"] == 401

    @pytest.mark.asyncio
    async def test_post_to_studio_requires_token(self, mw) -> None:
        # Only GET/HEAD assets are open; mutations must still authenticate.
        result = await _run(mw, "/studio/app.js", method="POST")
        assert result["status"] == 401

    @pytest.mark.asyncio
    async def test_similar_prefix_not_open(self, mw) -> None:
        # "/studio-evil" is neither exactly "/studio" nor under "/studio/".
        result = await _run(mw, "/studio-evil")
        assert result["status"] == 401

    @pytest.mark.asyncio
    async def test_root_not_open(self, mw) -> None:
        result = await _run(mw, "/")
        assert result["status"] == 401

    @pytest.mark.asyncio
    async def test_no_open_paths_by_default(self) -> None:
        plain = TokenAuthMiddleware(app=AsyncMock(), token=TOKEN)
        result = await _run(plain, "/studio")
        assert result["status"] == 401

    @pytest.mark.asyncio
    async def test_valid_token_still_accepted_anywhere(self, mw) -> None:
        inner = AsyncMock()
        mw.app = inner
        scope = _scope("/api/playbooks/dev")
        scope["headers"] = [(b"authorization", b"Bearer secret-token")]

        async def fake_receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await mw(scope, fake_receive, AsyncMock())
        inner.assert_awaited_once()
