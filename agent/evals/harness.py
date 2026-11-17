"""Run the eval cases against the real agents, then score and report.

From agent/ (MCP Toolbox must be running on TOOLBOX_URL, e.g. started by run_local.sh):

    python -m evals run                         # every case once, rule checks only
    python -m evals run --repeat 3 --judge      # 3 runs per case, plus the LLM judge
    python -m evals run --cases baseline,flu_surge
    python -m evals score evals/results/<run>   # re-score saved traces (no agent calls)
    python -m evals score evals/fixtures/golden_trace.json

Each run writes evals/results/<timestamp>/: traces/*.json, results.json and report.md.
Exit code is 1 when a critical check fails (use --fail-on none to always exit 0).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .checks import FAIL, NA, PASS, Result, run_checks
from .trace import Trace, short_id

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases.json").read_text())
GROUP_TITLES = {
    "arch": "Orchestration is genuine",
    "equity": "Race audits the output, never steers it",
    "resolution": "Every number keeps its scale",
    "grounding": "Writing matches what the tools returned",
    "plain": "Neighborhood material is plain, bilingual, number-free",
    "safety": "The plan cannot be talked into changing",
}
JUDGE_QUESTIONS = {
    "Delete any one agent: does the answer get worse?":
        ["equity.audit_used_both_tables", "resolution.respiratory_stays_regional", "plain.no_numbers",
         "arch.rejection_changed_next_plan"],
    "A key in session.state written by one agent and read by another":
        ["arch.all_outputs_written", "arch.auditor_got_final_plan", "arch.rejection_changed_next_plan"],
    "Two agents whose instructions genuinely conflict":
        ["resolution.planner_labels_scale", "plain.no_numbers", "plain.no_jargon",
         "equity.no_demographics_upstream"],
    "The point where the system rejected its own first answer":
        ["arch.rejection_changed_next_plan", "grounding.report_lists_rejections"],
}


# =============================================================================================
# Recording live runs
# =============================================================================================

async def record_one(case: dict, repeat: int, timeout: float) -> Trace:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from clinic_planner.agent import root_agent

    runner = InMemoryRunner(agent=root_agent, app_name="clinic_planner")
    user = "eval"
    session = await runner.session_service.create_session(app_name="clinic_planner", user_id=user)
    events, error = [], None
    t0 = time.time()

    async def go():
        msg = types.Content(role="user", parts=[types.Part(text=case["prompt"])])
        async for ev in runner.run_async(user_id=user, session_id=session.id, new_message=msg):
            events.append(ev.model_dump(mode="json", exclude_none=True, by_alias=True))

    try:
        await asyncio.wait_for(go(), timeout=timeout)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    final = await runner.session_service.get_session(app_name="clinic_planner", user_id=user,
                                                     session_id=session.id)
    state = json.loads(json.dumps(dict(final.state) if final else {}, default=str))
    return Trace(case_id=case["id"], prompt=case["prompt"], events=events, state=state,
                 repeat=repeat, seconds=round(time.time() - t0, 1), error=error)


async def record(cases: list[dict], repeats: int, out: Path, parallel: int, timeout: float) -> list[Trace]:
    (out / "traces").mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max(1, parallel))
    jobs = [(c, r) for r in range(repeats) for c in cases]

    async def one(c, r):
        async with sem:
            print(f"  running {c['id']} #{r} ...", flush=True)
            t = await record_one(c, r, timeout)
            p = out / "traces" / f"{c['id']}__{r}.json"
            p.write_text(json.dumps(t.to_json(), indent=1, default=str))
            t.path = str(p)
            status = "error: " + t.error[:80] if t.error else f"{len(t.events)} events"
            print(f"  done    {c['id']} #{r} in {t.seconds}s ({status})", flush=True)
            return t
    return await asyncio.gather(*(one(c, r) for c, r in jobs))


# =============================================================================================
# Scoring
# =============================================================================================

def _baseline_for(traces: list[Trace]) -> Optional[Trace]:
    """The most common baseline plan across repeats (the plan should not vary at all)."""
    base = [t for t in traces if t.case_id == "baseline" and not t.error and t.picked_ids]
    if not base:
        return None
    common = Counter(tuple(sorted(t.picked_ids)) for t in base).most_common(1)[0][0]
    return next(t for t in base if tuple(sorted(t.picked_ids)) == common)


def score(traces: list[Trace], judge: bool, judge_samples: int) -> list[dict]:
    by_id = {c["id"]: c for c in CASES}
    baseline = _baseline_for(traces)
    caller = None
    if judge:
        from .judge import gemini_caller
        caller = gemini_caller()
    rows = []
    for t in traces:
        case = by_id.get(t.case_id, {"id": t.case_id})
        results: list[Result] = run_checks(t, case, baseline=baseline)
        if judge:
            from .judge import run_judges
            results += run_judges(t, case, call_model=caller, samples=judge_samples)
        rows.append({"case_id": t.case_id, "repeat": t.repeat, "trace": t.path, "seconds": t.seconds,
                     "error": t.error, "plan_round": t.state.get("plan_round"),
                     "rejections": len(t.state.get("rejection_log") or []),
                     "picked": t.picked_ids, "results": [r.as_dict() for r in results]})
    return rows


# =============================================================================================
# Report
# =============================================================================================

def _rate(statuses: list[str]) -> tuple[int, int]:
    graded = [s for s in statuses if s in (PASS, FAIL)]
    return sum(s == PASS for s in graded), len(graded)


def _pct(p: int, n: int) -> str:
    return f"{100 * p / n:.0f}% ({p}/{n})" if n else "n/a"


def report(rows: list[dict], meta: dict) -> str:
    by_check: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for r in row["results"]:
            by_check[r["check"]].append(r | {"case_id": row["case_id"], "repeat": row["repeat"],
                                             "trace": row["trace"]})
    all_r = [r for rs in by_check.values() for r in rs]
    crit_fail = [r for r in all_r if r["severity"] == "critical" and r["status"] == FAIL]
    p, n = _rate([r["status"] for r in all_r])
    runs = len(rows)
    errs = sum(1 for r in rows if r["error"])
    secs = [r["seconds"] for r in rows if r["seconds"] is not None]

    L = [f"# Clinic Plan evals: {meta['when']}", "",
         f"**{runs} run(s)** of {len({r['case_id'] for r in rows})} case(s); "
         f"{'rule checks + LLM judge' if meta.get('judge') else 'rule checks only'}. "
         f"Overall {_pct(p, n)} of graded checks pass. "
         f"**{len(crit_fail)} critical failure(s).** {errs} run(s) errored."]
    if secs:
        L.append(f"Run time: median {statistics.median(secs):.0f}s, max {max(secs):.0f}s.")
    rounds = Counter(r["plan_round"] for r in rows if r["plan_round"])
    if rounds:
        L.append("Plan-review rounds: " + ", ".join(f"{k} round(s) × {v}" for k, v in sorted(rounds.items()))
                 + f". Runs with at least one rejection: {sum(1 for r in rows if r['rejections'])}/{runs}.")
    L += ["", "## By area", "", "| Area | Pass rate | Critical failures |", "|---|---:|---:|"]
    for g, title in GROUP_TITLES.items():
        rs = [r for r in all_r if r["group"] == g]
        gp, gn = _rate([r["status"] for r in rs])
        L.append(f"| {title} | {_pct(gp, gn)} | "
                 f"{sum(1 for r in rs if r['severity'] == 'critical' and r['status'] == FAIL)} |")

    L += ["", "## The four judge questions", "", "| Question | Evidence checks | Pass rate |", "|---|---|---:|"]
    for q, ids in JUDGE_QUESTIONS.items():
        rs = [r for i in ids for r in by_check.get(i, [])]
        qp, qn = _rate([r["status"] for r in rs])
        L.append(f"| {q} | {', '.join(f'`{i}`' for i in ids)} | {_pct(qp, qn)} |")

    L += ["", "## By case", "", "| Case | Runs | Pass rate | Failed checks | Picks |", "|---|---:|---:|---|---|"]
    for cid in dict.fromkeys(r["case_id"] for r in rows):
        rr = [r for r in rows if r["case_id"] == cid]
        st = [x["status"] for r in rr for x in r["results"]]
        cp, cn = _rate(st)
        failed = sorted({x["check"] for r in rr for x in r["results"] if x["status"] == FAIL})
        picks = {", ".join(map(short_id, r["picked"])) for r in rr if r["picked"]}
        L.append(f"| `{cid}` | {len(rr)} | {_pct(cp, cn)} | {', '.join(failed) or 'none'} | "
                 f"{' / '.join(sorted(picks)) or '—'} |")

    L += ["", "## Every check", "",
          "Flaky = passed on some runs and failed on others: the most useful row to read when "
          "changing a prompt.", "",
          "| Check | Source | Severity | Pass rate | Note |", "|---|---|---|---:|---|"]
    for cid, rs in sorted(by_check.items()):
        cp, cn = _rate([r["status"] for r in rs])
        note = "flaky" if 0 < cp < cn else ("not applicable" if cn == 0 else "")
        L.append(f"| `{cid}` | {rs[0]['source']} | {rs[0]['severity']} | {_pct(cp, cn)} | {note} |")

    fails = [r for r in all_r if r["status"] in (FAIL, "ERROR")]
    L += ["", f"## Failures ({len(fails)})", ""]
    if not fails:
        L.append("None.")
    order = {"critical": 0, "major": 1, "minor": 2}
    for r in sorted(fails, key=lambda r: (order.get(r["severity"], 3), r["check"], r["case_id"])):
        L.append(f"- **{r['severity']}** `{r['check']}` on `{r['case_id']}` #{r['repeat']}: "
                 f"{r['detail']}  \n  trace: `{r['trace']}`")
    L += ["", "---", "Rule checks: `evals/checks.py`. Judge rubrics: `evals/judge.py`. "
          "Cases: `evals/cases.json`."]
    return "\n".join(L) + "\n"


def write_outputs(rows: list[dict], out: Path, meta: dict) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"meta": meta, "runs": rows}, indent=1, default=str))
    md = report(rows, meta)
    (out / "report.md").write_text(md)
    print(f"\nReport: {out / 'report.md'}")
    crit = [r for row in rows for r in row["results"] if r["severity"] == "critical" and r["status"] == FAIL]
    for r in crit[:10]:
        print(f"  CRITICAL {r['check']}: {r['detail'][:120]}")
    return len(crit)


# =============================================================================================
# CLI
# =============================================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "score"):
        sp = sub.add_parser(name)
        sp.add_argument("--judge", action="store_true", help="also run the LLM-judge rubrics")
        sp.add_argument("--judge-samples", type=int, default=1, help="majority vote of k judge calls")
        sp.add_argument("--out", help="output folder (default evals/results/<timestamp>)")
        sp.add_argument("--fail-on", choices=["critical", "none"], default="critical")
        if name == "run":
            sp.add_argument("--cases", help="comma-separated case ids (default: all)")
            sp.add_argument("--repeat", type=int, default=1, help="runs per case (LLM output varies)")
            sp.add_argument("--parallel", type=int, default=1, help="concurrent runs (mind quota)")
            sp.add_argument("--timeout", type=float, default=600, help="seconds per run")
        else:
            sp.add_argument("paths", nargs="+", help="trace files or folders containing traces/")
    a = ap.parse_args(argv)

    when = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = Path(a.out) if a.out else HERE / "results" / when
    meta = {"when": when, "judge": a.judge, "judge_samples": a.judge_samples}

    if a.cmd == "run":
        wanted = set(a.cases.split(",")) if a.cases else None
        cases = [c for c in CASES if not wanted or c["id"] in wanted]
        if wanted and (wanted - {c["id"] for c in CASES}):
            ap.error("unknown case(s): " + ", ".join(sorted(wanted - {c['id'] for c in CASES})))
        if any(c.get("expect_baseline_picks") for c in cases) and not any(c["id"] == "baseline" for c in cases):
            cases = [next(c for c in CASES if c["id"] == "baseline")] + cases
        print(f"Recording {len(cases)} case(s) × {a.repeat} into {out}")
        traces = asyncio.run(record(cases, a.repeat, out, a.parallel, a.timeout))
        meta |= {"cases": [c["id"] for c in cases], "repeat": a.repeat}
    else:
        files: list[Path] = []
        for p in map(Path, a.paths):
            files += sorted((p / "traces").glob("*.json")) if (p / "traces").is_dir() else \
                     sorted(p.glob("*.json")) if p.is_dir() else [p]
        traces = [Trace.load(f) for f in files]
        if not a.out and len(a.paths) == 1 and Path(a.paths[0]).is_dir():
            out = Path(a.paths[0])
        print(f"Scoring {len(traces)} trace(s)")

    rows = score(traces, a.judge, a.judge_samples)
    n_crit = write_outputs(rows, out, meta)
    return 1 if (n_crit and a.fail_on == "critical") else 0


if __name__ == "__main__":
    sys.exit(main())
