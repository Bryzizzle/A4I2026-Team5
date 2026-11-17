"""Clinic Plan Console: the backend-for-frontend between the browser and Agent Runtime.

    GET  /                 the console (static/index.html)
    POST /api/run          run the agents live; streams every agent event as Server-Sent Events
    GET  /api/replay       stream the last completed run (or the bundled sample) at real pacing
    GET  /api/health       config check

Why a server in between: Agent Runtime needs Google credentials a browser must not hold. The agent
and the MCP Toolbox stay private; only this console is public. It also allows one live run at a
time, so a public URL cannot run up Gemini cost.

SSE messages (all JSON in `data:`), by `event:` name:
    session   {"session_id", "mode": "live"|"replay"}
    agent     one normalized agent event (see normalize_event)
    final     {"state": final session.state, trimmed}
    error     {"message"}
    done      {}

Local run (Cloud Shell, after deploy_agent_runtime.sh):
    pip install -r frontend/requirements.txt
    uvicorn frontend.app:app --host 0.0.0.0 --port 8080      # then Web Preview on 8080
Record the bundled replay:
    python3 -m frontend.app record "Plan next month's four Saturdays."
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
SAMPLE_RUN = os.path.join(HERE, "sample_run.json")
LAST_RUN = os.environ.get("LAST_RUN_PATH", "/tmp/clinic_last_run.json")
DEFAULT_MESSAGE = "Plan next month's four Saturdays for the Fulton County mobile clinic."
HEARTBEAT_SECONDS = 15
USER_ID = "console"

# Keys the console shows in its state panel. Everything else is dropped from the final state.
STATE_KEYS = ("evidence_need", "evidence_coverage", "evidence_respiratory", "plan", "review",
              "audit", "flyer", "clinic_plan", "plan_round", "plan_approved",
              "picked_tract_ids", "rejection_log", "review_findings", "excluded_geo_ids",
              "plan_history", "plan_data")


# ---------------------------------------------------------------- event normalization

def _get(d: dict, *names: str) -> Any:
    """Agent Runtime returns snake_case; tolerate camelCase too."""
    for n in names:
        if n in d:
            return d[n]
    return None


def trim_state(state: dict[str, Any]) -> dict[str, Any]:
    """Drop the 60 candidate rows from plan_data: the browser never needs them."""
    out = {}
    for k, v in (state or {}).items():
        if k == "plan_data" and isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if kk != "candidates"}
        out[k] = v
    return out


def _short(value: Any, limit: int = 600) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def normalize_event(raw: dict[str, Any], t: float) -> list[dict[str, Any]]:
    """One Agent Runtime event -> zero or more small UI messages.

    kinds: text, tool_call, tool_result, state, escalate
    """
    author = raw.get("author") or "?"
    out: list[dict[str, Any]] = []
    content = raw.get("content") or {}
    for part in content.get("parts") or []:
        fc = _get(part, "function_call", "functionCall")
        fr = _get(part, "function_response", "functionResponse")
        if fc:
            out.append({"t": t, "author": author, "kind": "tool_call",
                        "tool": fc.get("name"), "args": fc.get("args") or {}})
        elif fr:
            resp = fr.get("response") or {}
            msg = {"t": t, "author": author, "kind": "tool_result", "tool": fr.get("name"),
                   "summary": _short(resp)}
            if isinstance(resp, dict) and "approved" in resp:
                msg["approved"] = resp["approved"]
            out.append(msg)
        elif part.get("text") and not part.get("thought"):
            out.append({"t": t, "author": author, "kind": "text", "text": part["text"]})

    actions = raw.get("actions") or {}
    delta = _get(actions, "state_delta", "stateDelta") or {}
    if delta:
        out.append({"t": t, "author": author, "kind": "state",
                    "state_delta": trim_state(delta)})
    if actions.get("escalate"):
        out.append({"t": t, "author": author, "kind": "escalate"})
    return out


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------- Agent Runtime access

_remote = None


def agent_runtime_id() -> str:
    rid = os.environ.get("AGENT_RUNTIME_ID")
    if not rid:
        path = os.path.join(HERE, "..", "agent", ".agent_runtime_id")
        if os.path.exists(path):
            rid = open(path).read().strip()
    if not rid:
        raise RuntimeError("Set AGENT_RUNTIME_ID (projects/…/reasoningEngines/…) or deploy "
                           "with agent/deploy_agent_runtime.sh first.")
    return rid


def get_remote():
    """The deployed agent. Tests replace this with a fake."""
    global _remote
    if _remote is None:
        import vertexai
        name = agent_runtime_id()
        parts = name.split("/")            # projects/P/locations/L/reasoningEngines/ID
        client = vertexai.Client(project=parts[1], location=parts[3])
        _remote = client.agent_engines.get(name=name)
    return _remote


async def live_events(message: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Run the agents once; yield (sse_event_name, payload). Also returns the recording."""
    remote = get_remote()
    session = await remote.async_create_session(user_id=USER_ID)
    session_id = session["id"] if isinstance(session, dict) else session.id
    yield "session", {"session_id": session_id, "mode": "live", "message": message}

    start = time.monotonic()
    async for raw in remote.async_stream_query(user_id=USER_ID, session_id=session_id,
                                               message=message):
        for msg in normalize_event(raw if isinstance(raw, dict) else dict(raw),
                                   round(time.monotonic() - start, 2)):
            yield "agent", msg

    final = await remote.async_get_session(user_id=USER_ID, session_id=session_id)
    state = final.get("state", {}) if isinstance(final, dict) else getattr(final, "state", {})
    yield "final", {"state": trim_state({k: v for k, v in (state or {}).items()
                                         if k in STATE_KEYS})}


async def with_heartbeat(source: AsyncIterator[str]) -> AsyncIterator[str]:
    """Interleave SSE comments so proxies keep a quiet connection open between model calls."""
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    async def pump():
        try:
            async for item in source:
                await queue.put(item)
        finally:
            await queue.put(sentinel)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is sentinel:
                break
            yield item
    finally:
        task.cancel()


# ---------------------------------------------------------------- app

app = FastAPI(title="Clinic Plan Console")
_run_lock = asyncio.Lock()


class RunRequest(BaseModel):
    message: Optional[str] = None


@app.get("/api/health")
async def health() -> dict[str, Any]:
    try:
        rid = agent_runtime_id()
    except RuntimeError as e:
        rid = f"not configured: {e}"
    return {"agent_runtime": rid, "busy": _run_lock.locked(),
            "replay_available": os.path.exists(LAST_RUN) or os.path.exists(SAMPLE_RUN)}


@app.post("/api/run")
async def run(req: RunRequest) -> StreamingResponse:
    if _run_lock.locked():
        raise HTTPException(409, "A live run is already in progress. Try Replay, or wait.")
    message = (req.message or "").strip() or DEFAULT_MESSAGE

    async def stream() -> AsyncIterator[str]:
        recording: list[dict[str, Any]] = []
        async with _run_lock:
            try:
                async for name, payload in live_events(message):
                    recording.append({"event": name, "data": payload})
                    yield sse(name, payload)
                with open(LAST_RUN, "w") as f:
                    json.dump(recording, f, default=str)
            except Exception as e:  # surface to the UI instead of a dropped connection
                yield sse("error", {"message": f"{type(e).__name__}: {e}"})
        yield sse("done", {})

    return StreamingResponse(with_heartbeat(stream()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def load_recording() -> list[dict[str, Any]]:
    for path in (LAST_RUN, SAMPLE_RUN):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise HTTPException(404, "No recorded run yet. Run live once, or bundle sample_run.json.")


@app.get("/api/replay")
async def replay(speed: float = 1.0) -> StreamingResponse:
    recording = load_recording()
    speed = min(max(speed, 0.1), 50.0)

    async def stream() -> AsyncIterator[str]:
        last_t = 0.0
        for item in recording:
            data = dict(item["data"])
            if item["event"] == "session":
                data["mode"] = "replay"
            t = data.get("t")
            if isinstance(t, (int, float)) and t > last_t:
                await asyncio.sleep((t - last_t) / speed)
                last_t = t
            yield sse(item["event"], data)
        yield sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------- CLI: record a sample run

async def _record(message: str) -> None:
    recording = []
    async for name, payload in live_events(message):
        recording.append({"event": name, "data": payload})
        if name == "agent":
            print(f"{payload['t']:>7.1f}s  {payload['author']:<18} {payload['kind']}")
    with open(SAMPLE_RUN, "w") as f:
        json.dump(recording, f, default=str, indent=1)
    print(f"wrote {SAMPLE_RUN} ({len(recording)} messages)")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "record":
        asyncio.run(_record(" ".join(sys.argv[2:]) or DEFAULT_MESSAGE))
    else:
        print(__doc__)
