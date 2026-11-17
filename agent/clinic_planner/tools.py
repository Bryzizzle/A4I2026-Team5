"""The two tools we wrote ourselves.

plan_saturdays    (planner)   v_van_need rows -> four spaced Saturdays, via saturdays.py
check_plan_rules  (reviewer)  deterministic objections to the plan the planner just wrote

They talk through session.state, not through the model:

  plan_saturdays    WRITES  plan_data, picked_tract_ids, plan_round
                    READS   excluded_geo_ids
  check_plan_rules  READS   plan_data
                    WRITES  plan_approved, review_findings, excluded_geo_ids, rejection_log

So a rejection is guaranteed to change the next plan, whatever the model says.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from google.adk.tools import ToolContext

from .saturdays import haversine_km, pick_saturdays

N_SATURDAYS = 4
MIN_SPACING_KM = 3.0
SKIP_IF_SAFETY_NET_WITHIN_KM = 1.0
TIE_MARGIN = 2.0          # need_score points; PLACES is modeled, so smaller gaps are ties
POP_TIEBREAK_RATIO = 2.0  # a tied tract this many times larger should win the van-day
CANDIDATES = 60

_COLUMNS = ("geo_id, need_score, need_rank, latitude, longitude, km_to_safety_net, total_pop, "
            "pct_uninsured, pct_no_vehicle, pct_limited_english, components_missing, reason")


def _fetch_candidates() -> list[dict[str, Any]]:
    """Top tracts by need_score from v_van_need (planner-safe view: no demographics)."""
    from google.cloud import bigquery  # imported lazily so offline tests need no credentials

    # A4I_PROJECT first: on Agent Runtime the platform sets GOOGLE_CLOUD_PROJECT itself.
    project = os.environ.get("A4I_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
    dataset = os.environ.get("A4I_DATASET", "a4i_health")
    sql = (f"SELECT {_COLUMNS} FROM `{project}.{dataset}.v_van_need` "
           f"WHERE need_score IS NOT NULL ORDER BY need_score DESC LIMIT {CANDIDATES}")
    client = bigquery.Client(project=project)
    return [dict(r) for r in client.query(sql, location="US").result()]


# Tests replace this to run without BigQuery.
fetch_candidates = _fetch_candidates


def _slim(row: dict[str, Any]) -> dict[str, Any]:
    keep = ("geo_id", "need_score", "need_rank", "total_pop", "pct_uninsured", "pct_no_vehicle",
            "pct_limited_english", "km_to_safety_net", "components_missing", "reason", "saturday")
    out = {}
    for k in keep:
        v = row.get(k)
        out[k] = round(v, 2) if isinstance(v, float) else v
    return out


def plan_saturdays(tool_context: ToolContext,
                   exclude_geo_ids: Optional[list[str]] = None) -> dict[str, Any]:
    """Pick four Saturdays for the mobile clinic from the highest-need census tracts.

    Rules: highest need_score first; skip tracts under 1 km from an existing safety-net site;
    keep picks at least 3 km apart. Tracts the reviewer rejected are excluded automatically.

    Args:
      exclude_geo_ids: Optional extra tract ids to leave out of this plan.

    Returns:
      The four picks with reasons, the higher-scoring tracts passed over and why, near-ties
      with the last pick, and the rules used.
    """
    state = tool_context.state
    excluded = set(state.get("excluded_geo_ids") or []) | set(exclude_geo_ids or [])

    rows = [r for r in fetch_candidates() if r["geo_id"] not in excluded]
    plan = pick_saturdays(rows, n=N_SATURDAYS, min_spacing_km=MIN_SPACING_KM,
                          skip_if_safety_net_within_km=SKIP_IF_SAFETY_NET_WITHIN_KM,
                          tie_margin=TIE_MARGIN)

    by_id = {r["geo_id"]: r for r in rows}
    near_ties = [_slim(by_id[t["geo_id"]]) for t in plan["near_ties_with_last_pick"]]
    picked = [_slim(p) for p in plan["picked"]]

    state["plan_round"] = int(state.get("plan_round") or 0) + 1
    state["picked_tract_ids"] = ",".join(p["geo_id"] for p in picked)
    # Full rows (with coordinates) for the reviewer's tool. Never shown to the model.
    state["plan_data"] = {
        "round": state["plan_round"],
        "picked": [dict(p) for p in plan["picked"]],
        "skipped": plan["skipped"],
        "near_ties": [dict(by_id[t["geo_id"]]) for t in plan["near_ties_with_last_pick"]],
        "candidates": rows,
        "excluded": sorted(excluded),
    }

    return {
        "round": state["plan_round"],
        "picked": picked,
        "passed_over": plan["skipped"],
        "near_ties_with_last_pick": near_ties,
        "excluded_by_reviewer": sorted(excluded),
        "short_of_four": plan["short_of_n"],
        "rules": plan["rules"],
        "scale_note": ("Tract level. Uninsured and disease values are MODELED (CDC PLACES). "
                       "No-vehicle is a survey estimate (SVI). Distances are straight lines to "
                       "federally recognized sites inside the county: an upper bound."),
    }


def _review(plan_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure rule check, separated so it can be unit-tested without ADK."""
    picked = plan_data.get("picked") or []
    candidates = plan_data.get("candidates") or []
    picked_ids = {p["geo_id"] for p in picked}
    findings: list[dict[str, Any]] = []

    def complete(r):
        return not (r.get("components_missing") or 0)

    def far_from_net(r):
        km = r.get("km_to_safety_net")
        return km is None or km >= SKIP_IF_SAFETY_NET_WITHIN_KM

    # Rule 1: a pick scored on incomplete inputs must not displace a complete-data neighbour
    # that is effectively tied with it.
    for p in picked:
        if complete(p):
            continue
        for c in candidates:
            if (c["geo_id"] in picked_ids or not complete(c) or not far_from_net(c)
                    or c["need_score"] < p["need_score"] - TIE_MARGIN):
                continue
            d = haversine_km(p["latitude"], p["longitude"], c["latitude"], c["longitude"])
            if d < MIN_SPACING_KM:
                findings.append({
                    "rule": "incomplete_data_displaced_complete_neighbour",
                    "reject": p["geo_id"],
                    "prefer": c["geo_id"],
                    "detail": (f"Saturday {p['saturday']} (tract {p['geo_id']}, score "
                               f"{p['need_score']:.1f}) was scored with "
                               f"{int(p['components_missing'])} input(s) missing. Tract "
                               f"{c['geo_id']} is {d:.1f} km away, has complete data and scores "
                               f"{c['need_score']:.1f}: within {TIE_MARGIN:g} points, which is a "
                               f"tie for modeled estimates. Prefer the tract we can fully defend."),
                })
                break

    # Rule 2: if the last pick is effectively tied with a much larger tract, the van-day
    # should go where it can reach more people.
    if picked:
        last = picked[-1]
        others = [p for p in picked if p is not last]
        for c in plan_data.get("near_ties") or []:
            if not complete(c) or not far_from_net(c):
                continue
            if (c.get("total_pop") or 0) < POP_TIEBREAK_RATIO * (last.get("total_pop") or 0):
                continue
            if any(haversine_km(c["latitude"], c["longitude"], o["latitude"], o["longitude"])
                   < MIN_SPACING_KM for o in others):
                continue
            findings.append({
                "rule": "tie_broken_by_population_reached",
                "reject": last["geo_id"],
                "prefer": c["geo_id"],
                "detail": (f"Saturday {last['saturday']} (tract {last['geo_id']}, "
                           f"{int(last['total_pop']):,} people, score {last['need_score']:.1f}) is "
                           f"tied with tract {c['geo_id']} ({int(c['total_pop']):,} people, score "
                           f"{c['need_score']:.1f}). One van-day reaches more people there."),
            })
            break

    return findings


def check_plan_rules(tool_context: ToolContext) -> dict[str, Any]:
    """Check the plan the planner just produced against the review rules.

    Reads the plan from session state (not from the conversation), so the planner cannot
    argue its way past it. Rejected tracts are excluded from the next planning round.

    Returns:
      approved (bool), the findings with the tract to reject and the one to prefer, and the
      planning round reviewed.
    """
    state = tool_context.state
    plan_data = state.get("plan_data") or {}
    findings = _review(plan_data)

    if findings:
        excluded = list(state.get("excluded_geo_ids") or [])
        for f in findings:
            if f["reject"] not in excluded:
                excluded.append(f["reject"])
        state["excluded_geo_ids"] = excluded
        log = list(state.get("rejection_log") or [])
        log.extend({"round": plan_data.get("round"), **f} for f in findings)
        state["rejection_log"] = log

    state["plan_approved"] = not findings
    state["review_findings"] = findings
    return {"round": plan_data.get("round"), "approved": not findings, "findings": findings}
