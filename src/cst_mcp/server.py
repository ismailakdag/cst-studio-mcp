"""MCP server entry point for CST Studio Suite."""

from __future__ import annotations

import asyncio
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
    server = Server("cst-studio-mcp")
    client = CSTClient(config)
    register_all_tools(server, client)
    return server, client


async def run_server() -> None:
    server, client = create_server()
    conn = client.connect()
    logger.info("cst-studio-mcp %s start: %s", __version__, conn.get("status"))
    logger.info("status: %s", client.status())

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


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
