"""Read v_van_need from BigQuery, pick four Saturdays, print the plan.

Run in Cloud Shell from the repo root, after `bash data/run_sql.sh`:

    python3 data/plan_saturdays.py            # the plan (planner-safe: no demographics)
    python3 data/plan_saturdays.py --audit    # plus the AUDITOR-ONLY equity audit of the 4 picks

Uses the `bq` CLI, so it needs no Python packages beyond the standard library.
The planning logic lives in saturdays.py; this file only fetches rows and prints.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from saturdays import pick_saturdays  # noqa: E402

NUMERIC = ("need_score", "need_rank", "latitude", "longitude", "km_to_safety_net",
           "total_pop", "pct_uninsured", "pct_no_vehicle", "components_missing")


def bq(sql: str, project: str, params: list[str] | None = None) -> list[dict]:
    cmd = ["bq", f"--project_id={project}", "--location=US", "query",
           "--use_legacy_sql=false", "--format=json", "--max_rows=10000"]
    for p in params or []:
        cmd.append(f"--parameter={p}")
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"bq failed:\n{out.stdout}\n{out.stderr}")
    # bq may print a "Waiting on job..." line before the JSON.
    text = out.stdout[out.stdout.find("["):] if "[" in out.stdout else "[]"
    return json.loads(text)


def to_num(row: dict) -> dict:
    for k in NUMERIC:
        v = row.get(k)
        row[k] = None if v in (None, "") else float(v)
    return row


def default_project() -> str:
    try:
        p = subprocess.run(["gcloud", "config", "get-value", "project"],
                           capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        p = ""
    return "" if p == "(unset)" else p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=os.environ.get("PROJECT") or default_project())
    ap.add_argument("--dataset", default=os.environ.get("DATASET", "a4i_health"))
    ap.add_argument("--n", type=int, default=4, help="Saturdays to fill")
    ap.add_argument("--spacing-km", type=float, default=3.0)
    ap.add_argument("--skip-if-safety-net-within-km", type=float, default=1.0)
    ap.add_argument("--candidates", type=int, default=60, help="top-N tracts to consider")
    ap.add_argument("--audit", action="store_true",
                    help="also run the AUDITOR-ONLY demographic audit of the picks")
    args = ap.parse_args()
    if not args.project:
        sys.exit("No project. Run: gcloud config set project YOUR_PROJECT_ID")

    table = f"`{args.project}.{args.dataset}.v_van_need`"
    rows = bq(f"""
        SELECT geo_id, need_score, need_rank, latitude, longitude, km_to_safety_net,
               total_pop, pct_uninsured, pct_no_vehicle, components_missing, reason,
               (SELECT STRING_AGG(FORMAT('%s %.2f', d.driver, d.pctile), ', ')
                FROM UNNEST(top_drivers) d) AS drivers
        FROM {table}
        WHERE need_score IS NOT NULL
        ORDER BY need_score DESC
        LIMIT {int(args.candidates)}
    """, args.project)
    rows = [to_num(r) for r in rows]

    plan = pick_saturdays(rows, n=args.n, min_spacing_km=args.spacing_km,
                          skip_if_safety_net_within_km=args.skip_if_safety_net_within_km)

    print(f"\n=== The plan: {len(plan['picked'])} Saturdays "
          f"(from the top {len(rows)} tracts by need_score)\n")
    for p in plan["picked"]:
        flag = "  [scored with a missing input]" if (p["components_missing"] or 0) > 0 else ""
        print(f"Saturday {p['saturday']}: tract {p['geo_id']}  need_score {p['need_score']:.1f}"
              f"  (rank {int(p['need_rank'])}){flag}")
        print(f"  why:     {p['reason']}")
        print(f"  drivers: {p['drivers']}\n")

    if plan["skipped"]:
        print("=== Higher-scoring tracts we passed over, and why")
        for s in plan["skipped"]:
            print(f"  {s['geo_id']}  need_score {s['need_score']:.1f}: {s['reason']}")
        print()

    if plan["near_ties_with_last_pick"]:
        print(f"=== Within {plan['rules']['tie_margin_points']} points of the last pick "
              "(PLACES is modeled; treat these as ties, not losers)")
        for t in plan["near_ties_with_last_pick"]:
            print(f"  {t['geo_id']}  need_score {t['need_score']:.1f}")
        print()

    if plan["short_of_n"]:
        print(f"WARNING: only {len(plan['picked'])} of {args.n} Saturdays filled. "
              "Raise --candidates or relax the rules.\n")

    print("Rules:", json.dumps(plan["rules"]))
    picked_ids = [p["geo_id"] for p in plan["picked"]]
    print("Picked tract ids:", json.dumps(picked_ids))

    if args.audit and picked_ids:
        with open(os.path.join(HERE, "sql", "queries", "audit_plan.sql")) as f:
            sql = (f.read().replace("{{PROJECT}}", args.project)
                           .replace("{{DATASET}}", args.dataset))
        audit = bq(sql, args.project,
                   [f"tract_ids:ARRAY<STRING>:{json.dumps(picked_ids)}"])
        print("\n=== Equity audit of these picks (AUDITOR ONLY; "
              f"{len(picked_ids)} tracts is a tiny sample, report next to the top-decile audit)")
        print(f"  {'group':<50} {'county':>8} {'plan':>8} {'ratio':>6}")
        for a in audit:
            print(f"  {a['grp']:<50} {a['county_share']:>8} {a['plan_share']:>8} "
                  f"{a['ratio_vs_county']:>6}")


if __name__ == "__main__":
    main()
