"""MCP server entry point for CST Studio Suite."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server

from cst_mcp import __version__
from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import register_all_tools

logger = logging.getLogger(__name__)


def create_server(config: CSTConfig | None = None) -> tuple[Server, CSTClient]:
    config = config or CSTConfig.from_env()
    server = Server(
        "cst-studio-mcp",
        version=__version__,
        instructions=(
            "Control CST Studio Suite through structured tools. Check "
            "cst_connection_status before operations that require a live CST session."
        ),
    )
    client = CSTClient(config)
    register_all_tools(server, client)
    return server, client


@contextlib.contextmanager
def protocol_output():
    """Reserve JSON-RPC stdout, including against native writes to descriptor 1."""
    stdout_fd = sys.stdout.fileno()
    protocol_stdout = io.TextIOWrapper(
        os.fdopen(os.dup(stdout_fd), "wb"),
        encoding="utf-8", errors="replace", newline="\n", write_through=True,
    )
    sys.stdout.flush()
    try:
        os.dup2(sys.stderr.fileno(), stdout_fd)
        with contextlib.redirect_stdout(sys.stderr):
            yield protocol_stdout
    finally:
        sys.stderr.flush()
        os.dup2(protocol_stdout.fileno(), stdout_fd)
        protocol_stdout.close()


async def run_server() -> None:
    # Isolate vendor output before creating the client or probing CST. A slow
    # CST startup is opt-in; the default MCP handshake has no CST side effects.
    with protocol_output() as protocol_stdout:
        server, client = create_server()
        if client.config.connect_on_startup:
            try:
                conn = client.connect()
                logger.info("cst-studio-mcp %s start: %s", __version__, conn.get("status"))
            except Exception:
                logger.exception("CST startup connection failed; continuing in offline mode")
        else:
            logger.info("cst-studio-mcp %s start: %s mode", __version__, client.config.connect_mode)

        import anyio

        async with stdio_server(stdout=anyio.wrap_file(protocol_stdout)) as streams:
            await server.run(*streams, server.create_initialization_options())


def main() -> None:
    level = os.environ.get("CST_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
