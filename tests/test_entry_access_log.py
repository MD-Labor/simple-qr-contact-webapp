"""The permissive access log on the fetch handler.

The log must run through waitUntil, not inline: the response should not wait on
the JWKS fetch a cold cache needs.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import auth
import entry


class FakeExecutionContext:
    def __init__(self):
        self.pending = []

    def waitUntil(self, awaitable):
        self.pending.append(awaitable)


@pytest.fixture
def worker(monkeypatch):
    async def fake_auth(request, env):
        return auth.AuthContext(
            is_authenticated=True, email="jay.huie@maryland.gov", roles=["user"]
        )

    monkeypatch.setattr(entry, "get_auth_context", fake_auth)
    handler = entry.Default()
    handler.ctx = FakeExecutionContext()
    handler.env = SimpleNamespace()
    return handler


def test_the_log_is_handed_to_wait_until_and_written_as_json(worker, capsys):
    request = SimpleNamespace(url="https://apps.labor.maryland.dev/api/")

    async def run():
        response = await worker.fetch(request)
        # The response is back; the log has been scheduled but not yet written.
        assert capsys.readouterr().out == ""
        assert len(worker.ctx.pending) == 1
        await worker.ctx.pending[0]
        return response

    response = asyncio.run(run())
    assert response.status == 200
    assert json.loads(capsys.readouterr().out) == {
        "message": "MD Labor Apps Access",
        "path": "/api",
        "authenticated": True,
        "by": "jay.huie@maryland.gov",
    }
