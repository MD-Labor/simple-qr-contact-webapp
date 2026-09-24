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
from conftest import FakeProxy


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
        # A bare task would get Pyodide's implicit proxy, destroyed as soon as
        # waitUntil returns; it has to be an explicit one...
        proxy = worker.ctx.pending[0]
        assert isinstance(proxy, FakeProxy)
        assert not proxy.destroyed
        await proxy.obj
        # ...released once the task settles (done callbacks run a tick later).
        await asyncio.sleep(0)
        assert proxy.destroyed
        return response

    response = asyncio.run(run())
    assert response.status == 200
    assert json.loads(capsys.readouterr().out) == {
        "message": "MD Labor Apps Access",
        "app_access": {
            "is_authenticated": True,
            "by": "jay.huie@maryland.gov",
            "path": "/api",
        },
    }
