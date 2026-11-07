"""
arcpy_bridge.py
Listener HTTP lokal yang mengeksekusi geoprocessing di dalam ArcGIS Pro Python.
Jalankan dengan: "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" arcpy_bridge.py
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import arcpy  # hanya tersedia di Pro Python

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("arcpy_bridge")

HOST = os.getenv("ARCGIS_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("ARCGIS_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("ARCGIS_BRIDGE_TOKEN", "")  # simple bearer-token auth


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
ToolFn = Callable[[dict[str, Any]], Any]
TOOLS: dict[str, ToolFn] = {}


def tool(name: str):
    def deco(fn: ToolFn) -> ToolFn:
        TOOLS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
@tool("buffer")
def do_buffer(args: dict[str, Any]) -> dict[str, str]:
    """
    Buffer fitur.
    args: input, output, distance, {dissolve_type?}
    """
    required = ("input", "output", "distance")
    _require(args, required)

    arcpy.env.overwriteOutput = True
    result = arcpy.analysis.Buffer(
        in_features=args["input"],
        out_feature_class=args["output"],
        buffer_distance_or_field=args["distance"],
        dissolve_option=args.get("dissolve_type", "NONE"),
    )
    log.info("Buffer → %s", result[0])
    return {"output": str(result[0])}


@tool("clip")
def do_clip(args: dict[str, Any]) -> dict[str, str]:
    _require(args, ("input", "clip_features", "output"))
    arcpy.env.overwriteOutput = True
    result = arcpy.analysis.Clip(args["input"], args["clip_features"], args["output"])
    return {"output": str(result[0])}


@tool("buffer")
def _noop():  # placeholder removed below
    ...


@tool("select_by_attribute")
def do_select(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, ("input", "where"))
    lyr = args["input"]
    arcpy.management.SelectLayerByAttribute(lyr, "NEW_SELECTION", args["where"])
    count = int(arcpy.management.GetCount(lyr)[0])
    return {"selected_count": count}


@tool("describe")
def do_describe(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, ("input",))
    d = arcpy.Describe(args["input"])
    return {
        "name": d.name,
        "dataType": d.dataType,
        "shapeType": getattr(d, "shapeType", None),
        "spatialReference": getattr(d.spatialReference, "name", None),
        "extent": [d.extent.XMin, d.extent.YMin, d.extent.XMax, d.extent.YMax]
        if hasattr(d, "extent") else None,
    }


@tool("geoprocess")
def do_run_toolbox(args: dict[str, Any]) -> Any:
    """
    Generic executor - dispatch ke Toolbox apapun.
    args: tool_name (e.g. "analysis.Buffer"), params (list)
    """
    _require(args, ("tool_name", "params"))
    fn = arcpy  # start at root
    for part in args["tool_name"].split("."):
        fn = getattr(fn, part)
    return fn(*args["params"])


def _require(args: dict[str, Any], keys: tuple[str, ...]) -> None:
    missing = [k for k in keys if k not in args]
    if missing:
        raise ValueError(f"Missing required args: {missing}")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ArcPyBridge/1.0"

    def _check_auth(self) -> bool:
        if not TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {TOKEN}"

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "tools": sorted(TOOLS)})
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized"})
            return
        if self.path != "/run":
            self._send_json(404, {"error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"bad_request: {exc}"})
            return

        name = payload.get("tool")
        args = payload.get("args", {})
        fn = TOOLS.get(name)
        if fn is None:
            self._send_json(404, {"error": f"unknown_tool: {name}"})
            return

        try:
            log.info("Executing tool=%s args=%s", name, list(args.keys()))
            result = fn(args)
            self._send_json(200, {"ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001
            log.error("Tool %s failed: %s", name, exc)
            self._send_json(500, {
                "ok": False,
                "error": str(exc),
                "trace": traceback.format_exc(limit=5),
            })

    def log_message(self, fmt: str, *a) -> None:  # silence default logging
        log.debug(fmt, *a)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("Starting ArcPy bridge on http://%s:%d", HOST, PORT)
    log.info("Registered tools: %s", sorted(TOOLS))
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")


if __name__ == "__main__":
    main()
