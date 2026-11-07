"""
MCP server exposing ArcGIS geoprocessing tools.
Install: pip install "mcp[cli]" httpx
Run:     python server.py
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BRIDGE_URL = os.getenv("ARCGIS_BRIDGE_URL", "http://127.0.0.1:8765")
TOKEN = os.getenv("ARCGIS_BRIDGE_TOKEN", "")

mcp = FastMCP("arcgis-pro")
_client = httpx.AsyncClient(
    base_url=BRIDGE_URL,
    timeout=httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0),
    headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {},
)


async def _call(tool: str, **args: Any) -> Any:
    """Proxy call to the arcpy bridge with graceful error handling."""
    try:
        r = await _client.post("/run", json={"tool": tool, "args": args})
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot reach ArcGIS bridge at {BRIDGE_URL}. "
            "Is arcpy_bridge.py running inside ArcGIS Pro Python?"
        ) from exc

    if r.status_code != 200:
        raise RuntimeError(f"Bridge error {r.status_code}: {r.text}")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Geoprocessing failed: {data.get('error')}")
    return data["result"]


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def arcgis_buffer(
    input: str, output: str, distance: str, dissolve_type: str = "NONE"
) -> dict:
    """Buffer a feature class.

    Args:
        input: Path to input feature class.
        output: Path to output feature class (will be overwritten).
        distance: Distance like "100 Meters".
        dissolve_type: NONE | ALL | LIST.
    """
    return await _call(
        "buffer",
        input=input, output=output, distance=distance, dissolve_type=dissolve_type,
    )


@mcp.tool()
async def arcgis_clip(input: str, clip_features: str, output: str) -> dict:
    """Clip a feature class by a polygon layer."""
    return await _call("clip", input=input, clip_features=clip_features, output=output)


@mcp.tool()
async def arcgis_select_by_attribute(input: str, where: str) -> dict:
    """Run a SQL WHERE selection on a layer; returns selected count."""
    return await _call("select_by_attribute", input=input, where=where)


@mcp.tool()
async def arcgis_describe(input: str) -> dict:
    """Describe a dataset (type, shapeType, SR, extent)."""
    return await _call("describe", input=input)


@mcp.tool()
async def arcgis_run_tool(tool_name: str, params: list) -> Any:
    """Escape hatch: run any arcpy tool by dotted name.

    Example: tool_name="analysis.Buffer", params=[in_fc, out_fc, "500 Meters"]
    """
    return await _call("geoprocess", tool_name=tool_name, params=params)


if __name__ == "__main__":
    mcp.run()  # stdio transport
