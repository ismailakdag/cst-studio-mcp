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


async def run_server() -> None:
    server, client = create_server()
    if client.config.connect_on_startup:
        try:
            # Some vendor Python builds print during import/connection. stdout
            # is reserved for JSON-RPC, so route such diagnostics to stderr.
            with contextlib.redirect_stdout(sys.stderr):
                conn = client.connect()
            logger.info("cst-studio-mcp %s start: %s", __version__, conn.get("status"))
        except Exception:
            logger.exception("CST startup connection failed; continuing in offline mode")
    else:
        logger.info(
            "cst-studio-mcp %s start: CST connection mode is %s",
            __version__,
            client.config.connect_mode,
        )

    try:
        logger.info("status: %s", client.status())
    except Exception:
        logger.exception("Could not read initial CST status; continuing MCP startup")

    # Keep a private handle to protocol stdout. During the entire server run,
    # ordinary print() calls are redirected to stderr and cannot corrupt the
    # newline-delimited JSON-RPC stream consumed by MCP clients.
    protocol_stdout = io.TextIOWrapper(
        os.fdopen(os.dup(sys.stdout.fileno()), "wb"),
        encoding="utf-8",
        errors="replace",
        newline="\n",
        write_through=True,
    )
    try:
        import anyio

        async_stdout = anyio.wrap_file(protocol_stdout)
        with contextlib.redirect_stdout(sys.stderr):
            async with stdio_server(stdout=async_stdout) as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
    finally:
        protocol_stdout.close()


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
