import sys
import types
from pathlib import Path

# The Worker imports these as top-level modules (pywrangler flattens src/ into
# the bundle), so tests resolve them the same way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# entry.py only runs on Workers: the real 'workers' package imports 'js', which
# exists only inside Pyodide. Stub the two runtime modules here, before any test
# imports entry, so collection order cannot decide whether that import works.
# The stubs are deliberately thin - anything entry.py needs that is missing
# still fails loudly rather than silently passing - but they record enough for
# a test to inspect the status, headers and body of a response.


class FakeResponse:
    def __init__(self, body=None, headers=None, status=200):
        self.body = body
        self.headers = headers or {}
        self.status = status

    @classmethod
    def json(cls, payload, status=200):
        return cls(payload, status=status)


class FakeBuffer:
    """Stands in for the JS typed array to_js() returns."""

    def __init__(self, value):
        self.buffer = value


class FakeProxy:
    """Stands in for the PyProxy create_proxy() returns."""

    def __init__(self, obj):
        self.obj = obj
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


async def unpatched_fetch(url, **kwargs):
    raise AssertionError(f"test made a real fetch to {url}; monkeypatch it")


for _name, _attrs in (
    ("pyodide", {}),
    ("pyodide.ffi", {"to_js": FakeBuffer, "create_proxy": FakeProxy}),
    (
        "workers",
        {
            "Response": FakeResponse,
            "WorkerEntrypoint": type("WorkerEntrypoint", (), {}),
            "fetch": unpatched_fetch,
        },
    ),
):
    _module = types.ModuleType(_name)
    for _attr, _value in _attrs.items():
        setattr(_module, _attr, _value)
    sys.modules.setdefault(_name, _module)
sys.modules["pyodide"].ffi = sys.modules["pyodide.ffi"]
