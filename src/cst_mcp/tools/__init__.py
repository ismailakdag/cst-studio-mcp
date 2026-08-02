"""Register every CST MCP tool module (full surface + workflows)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cst_mcp.tools import (
    antenna_templates,
    arrays,
    boolean,
    boundaries,
    diagnostics,
    geometry,
    import_export,
    matching,
    materials,
    mesh,
    optimization,
    parameters,
    pcb,
    ports,
    project,
    results,
    simulation,
    solvers,
    transforms,
    vba,
    workflows,
)
from cst_mcp.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from mcp.server import Server

    from cst_mcp.cst_client import CSTClient

# Full ported modules + our high-level workflows
_MODULES = (
    project,
    geometry,
    boolean,
    transforms,
    materials,
    ports,
    boundaries,
    mesh,
    solvers,
    simulation,
    results,
    import_export,
    parameters,
    optimization,
    diagnostics,
    antenna_templates,
    arrays,
    pcb,
    matching,
    vba,
    workflows,
)


def register_all_tools(server: Server, client: CSTClient) -> ToolRegistry:
    reg = ToolRegistry()
    for mod in _MODULES:
        reg.add_module(mod.TOOLS, mod.handle)
    reg.bind(server, client)
    return reg
