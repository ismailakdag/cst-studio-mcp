import json
from types import SimpleNamespace

import pytest

from cst_mcp.tools.connection import handle


@pytest.mark.asyncio
async def test_disabled_connection_never_calls_vendor():
    def forbidden():
        raise AssertionError("Vendor connection must not be attempted")
    client = SimpleNamespace(config=SimpleNamespace(connect_mode="disabled"), connect=forbidden)
    result = await handle("cst_connect", {}, client)
    assert json.loads(result[0].text)["status"] == "error"


@pytest.mark.asyncio
async def test_reconnect_preserves_existing_session():
    def forbidden():
        raise AssertionError("Existing session must not be replaced")
    client = SimpleNamespace(config=SimpleNamespace(connect_mode="manual"), connected=True, connect=forbidden)
    result = await handle("cst_connect", {}, client)
    assert json.loads(result[0].text)["status"] == "connected"


@pytest.mark.asyncio
async def test_failed_connection_is_a_tool_error():
    client = SimpleNamespace(config=SimpleNamespace(connect_mode="manual"), connected=False,
                             connect=lambda **kw: {"status": "offline", "message": "mock loader failure"})
    result = await handle("cst_connect", {}, client)
    assert json.loads(result[0].text)["status"] == "error"


@pytest.mark.asyncio
async def test_connect_forwards_mode_and_rejects_unknown_mode():
    seen = {}

    def fake_connect(mode="any"):
        seen["mode"] = mode
        return {"status": "connected", "mode": mode, "de_pid": 4242, "newly_started": True}

    client = SimpleNamespace(config=SimpleNamespace(connect_mode="manual"), connected=False,
                             connect=fake_connect)
    result = json.loads((await handle("cst_connect", {"mode": "new"}, client))[0].text)
    assert seen["mode"] == "new" and result["de_pid"] == 4242
    result = json.loads((await handle("cst_connect", {"mode": "bogus"}, client))[0].text)
    assert result["status"] == "error"
