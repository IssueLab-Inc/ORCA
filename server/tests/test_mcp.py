import asyncio

from sightline import mcp_server


def test_tools_are_registered():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == {
        "list_models", "open_model", "describe_element", "verify_move",
        "propose_solutions", "apply_solution", "export_model",
    }
