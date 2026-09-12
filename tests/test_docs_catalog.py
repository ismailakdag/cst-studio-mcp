"""The generated client guide must expose the same tools as the live server."""
import importlib.util
from pathlib import Path

from mcp.server import Server

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import register_all_tools


def test_documented_tools_match_registered_tools():
    path = Path(__file__).resolve().parents[1] / "scripts/build_docs.py"
    spec = importlib.util.spec_from_file_location("docs_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = module.collect_tools()
    registry = register_all_tools(Server("catalog-test"), CSTClient(CSTConfig(connect_mode="disabled")))
    assert {item["name"] for item in catalog} == set(registry.tool_names)
    assert len(catalog) == len(registry)
