"""A recorded run of the Clinic Plan agents: every ADK event plus the final session.state.

Checks read a Trace, never a live agent, so a run can be recorded once (slow, costs model calls)
and scored many times (fast, free), and the checks themselves can be unit-tested on fixtures.

On disk a trace is JSON:
    {"case_id": ..., "prompt": ..., "repeat": 0, "started_at": ..., "seconds": ...,
     "events": [<ADK Event as JSON, camelCase>], "state": {<final session.state>}, "error": null}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _get(d: dict, *names: str, default=None):
    """Read a key that may be camelCase (REST/by_alias) or snake_case (model_dump)."""
    for n in names:
        if isinstance(d, dict) and n in d:
            return d[n]
    return default


def parse_rows(response: Any) -> list[dict]:
    """Toolbox results arrive as a list, a JSON string, or {"result": <either>}. Return rows."""
    r = response
    for _ in range(3):
        if isinstance(r, str):
            try:
                r = json.loads(r)
            except ValueError:
                return []
        elif isinstance(r, dict) and len(r) <= 2 and ("result" in r or "output" in r):
            r = r.get("result", r.get("output"))
        else:
            break
    if isinstance(r, list):
        return [x for x in r if isinstance(x, dict)]
    if isinstance(r, dict):
        return [r]
    return []


@dataclass
class Call:
    author: str
    name: str
    args: dict


@dataclass
class Response:
    author: str
    name: str
    response: Any

    @property
    def rows(self) -> list[dict]:
        return parse_rows(self.response)


@dataclass
class Trace:
    case_id: str
    prompt: str
    events: list[dict]
    state: dict
    repeat: int = 0
    seconds: Optional[float] = None
    error: Optional[str] = None
    path: Optional[str] = None
    calls: list[Call] = field(default_factory=list)
    responses: list[Response] = field(default_factory=list)
    texts: dict[str, list[str]] = field(default_factory=dict)
    spans: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self):
        for ev in self.events:
            author = ev.get("author", "?")
            ts = ev.get("timestamp")
            if isinstance(ts, (int, float)):
                a, b = self.spans.get(author, (ts, ts))
                self.spans[author] = (min(a, ts), max(b, ts))
            content = ev.get("content") or {}
            for part in content.get("parts") or []:
                if part.get("thought"):
                    continue
                fc = _get(part, "functionCall", "function_call")
                fr = _get(part, "functionResponse", "function_response")
                if fc:
                    self.calls.append(Call(author, fc.get("name", ""), fc.get("args") or {}))
                elif fr:
                    self.responses.append(Response(author, fr.get("name", ""), fr.get("response")))
                elif part.get("text"):
                    self.texts.setdefault(author, []).append(part["text"])

    # ---- loading ----------------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Trace":
        d = json.loads(Path(path).read_text())
        return cls(case_id=d["case_id"], prompt=d.get("prompt", ""), events=d.get("events", []),
                   state=d.get("state", {}), repeat=d.get("repeat", 0), seconds=d.get("seconds"),
                   error=d.get("error"), path=str(path))

    def to_json(self) -> dict:
        return {"case_id": self.case_id, "prompt": self.prompt, "repeat": self.repeat,
                "seconds": self.seconds, "error": self.error, "events": self.events,
                "state": self.state}

    # ---- convenience ------------------------------------------------------------------------
    def text(self, author: str) -> str:
        """The agent's final text output: its output_key in state if known, else its last text."""
        t = self.texts.get(author) or []
        return t[-1] if t else ""

    def all_text(self, author: str) -> str:
        return "\n\n".join(self.texts.get(author) or [])

    def calls_by(self, author: str) -> list[Call]:
        return [c for c in self.calls if c.author == author]

    def calls_named(self, name: str) -> list[Call]:
        return [c for c in self.calls if c.name == name]

    def last_response(self, name: str) -> Optional[Response]:
        rs = [r for r in self.responses if r.name == name]
        return rs[-1] if rs else None

    def responses_named(self, name: str) -> list[Response]:
        return [r for r in self.responses if r.name == name]

    @property
    def picked_ids(self) -> list[str]:
        raw = self.state.get("picked_tract_ids") or ""
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    @property
    def plan_history(self) -> list[dict]:
        """One entry per planning round. Falls back to plan_saturdays responses on branches
        that predate state.plan_history."""
        h = self.state.get("plan_history")
        if isinstance(h, list) and h:
            return h
        out = []
        for r in self.responses_named("plan_saturdays"):
            resp = r.response if isinstance(r.response, dict) else {}
            if resp.get("picked") is not None:
                out.append({"round": resp.get("round"), "picked": resp.get("picked") or [],
                            "passed_over": resp.get("passed_over") or [],
                            "excluded": resp.get("excluded_by_reviewer") or []})
        return out

    @property
    def known_tract_ids(self) -> set[str]:
        """Every tract the planner could legitimately name: candidates, skips, ties, exclusions."""
        ids: set[str] = set()
        pd = self.state.get("plan_data") or {}
        for key in ("picked", "candidates", "near_ties"):
            ids |= {r.get("geo_id") for r in pd.get(key) or [] if isinstance(r, dict)}
        ids |= {r.get("geo_id") for r in pd.get("skipped") or [] if isinstance(r, dict)}
        ids |= set(pd.get("excluded") or [])
        for h in self.plan_history:
            ids |= {p.get("geo_id") for p in h.get("picked") or []}
            ids |= {p.get("geo_id") for p in h.get("passed_over") or []}
            ids |= set(h.get("excluded") or [])
        for r in self.responses_named("plan_saturdays"):
            resp = r.response if isinstance(r.response, dict) else {}
            for key in ("picked", "passed_over", "near_ties_with_last_pick"):
                ids |= {p.get("geo_id") for p in resp.get(key) or [] if isinstance(p, dict)}
        for r in self.responses_named("top_need_tracts") + self.responses_named("tract_detail"):
            ids |= {row.get("geo_id") for row in r.rows}
        ids.discard(None)
        return {str(i) for i in ids}


def short_id(geo_id: str) -> str:
    """Fulton tracts are 13121xxxxxx; agents often write only the last six digits."""
    g = str(geo_id)
    return g[5:] if len(g) == 11 else g


def mentions_tract(text: str, geo_id: str) -> bool:
    return bool(re.search(rf"(?<!\d)(?:{re.escape(str(geo_id))}|{re.escape(short_id(geo_id))})(?!\d)",
                          text or ""))
