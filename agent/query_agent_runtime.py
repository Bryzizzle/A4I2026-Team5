"""Talk to the Clinic Plan agents deployed on Agent Runtime.

    python3 agent/query_agent_runtime.py "Plan next month's four Saturdays."

Prints each agent's turn as it streams (author, tool calls, text), then the session state keys
that show the architecture working: plan_round, rejection_log, picked_tract_ids, plan_approved.

Reads the resource name from agent/.agent_runtime_id (written by deploy_agent_runtime.sh), or
from the AGENT_RUNTIME_ID environment variable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def resource_name() -> str:
    rid = os.environ.get("AGENT_RUNTIME_ID")
    if not rid:
        path = os.path.join(HERE, ".agent_runtime_id")
        if not os.path.exists(path):
            sys.exit("No Agent Runtime id. Run: bash agent/deploy_agent_runtime.sh")
        rid = open(path).read().strip()
    return rid


async def main(message: str) -> None:
    import vertexai

    name = resource_name()
    parts = name.split("/")            # projects/P/locations/L/reasoningEngines/ID
    client = vertexai.Client(project=parts[1], location=parts[3])
    remote = client.agent_engines.get(name=name)

    user_id = "demo"
    session = await remote.async_create_session(user_id=user_id)
    session_id = session["id"] if isinstance(session, dict) else session.id
    print(f"session {session_id}\n")

    last_author = None
    async for event in remote.async_stream_query(user_id=user_id, session_id=session_id,
                                                 message=message):
        author = event.get("author", "?")
        if author != last_author:
            print(f"\n===== {author}")
            last_author = author
        for part in (event.get("content") or {}).get("parts") or []:
            if part.get("function_call"):
                fc = part["function_call"]
                print(f"  -> calls {fc.get('name')}({json.dumps(fc.get('args') or {})})")
            elif part.get("function_response"):
                print(f"  <- {part['function_response'].get('name')} returned")
            elif part.get("text"):
                print(part["text"])

    final = await remote.async_get_session(user_id=user_id, session_id=session_id)
    state = final.get("state", {}) if isinstance(final, dict) else getattr(final, "state", {})
    print("\n===== session.state (the keys agents passed to each other)")
    for key in ("plan_round", "plan_approved", "picked_tract_ids", "rejection_log"):
        print(f"{key}: {json.dumps(state.get(key), indent=2, default=str)}")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "Plan next month's four Saturdays."))
