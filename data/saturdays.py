"""Turn a ranked tract list into four Saturdays, and record why the runners-up lost.

Pure Python, no cloud dependencies, so the agent lane can wrap it as an ADK function tool
and anyone can test it locally.

Input: rows from v_van_need (dicts with at least geo_id, need_score, latitude, longitude;
km_to_safety_net and near_existing_safety_net are used if present), in any order.

Rules, in order:
  1. Skip tracts that were not scored (need_score is None).
  2. Skip tracts within `skip_if_safety_net_within_km` of an existing safety-net site.
     A van parked next to an FQHC duplicates care that is already there.
  3. Skip tracts within `min_spacing_km` of a tract already picked. Two Saturdays three
     blocks apart serve the same people twice and the next neighborhood not at all.
  4. Take the highest need_score that survives, until `n` are picked.

Every skipped tract gets a reason. That list is what the explanation agent uses to answer
"why them and not us?".
"""

from __future__ import annotations

import math
from typing import Any, Iterable


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def pick_saturdays(
    candidates: Iterable[dict[str, Any]],
    n: int = 4,
    min_spacing_km: float = 3.0,
    skip_if_safety_net_within_km: float | None = 1.0,
    tie_margin: float = 2.0,
) -> dict[str, Any]:
    rows = [c for c in candidates if c.get("need_score") is not None]
    rows.sort(key=lambda c: c["need_score"], reverse=True)

    picked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for c in rows:
        if len(picked) >= n:
            break

        km_sn = c.get("km_to_safety_net")
        if (skip_if_safety_net_within_km is not None and km_sn is not None
                and km_sn < skip_if_safety_net_within_km):
            skipped.append({
                "geo_id": c["geo_id"], "need_score": c["need_score"],
                "reason": f"already {km_sn:.1f} km from a federally recognized safety-net site",
            })
            continue

        clash = None
        for p in picked:
            d = haversine_km(c["latitude"], c["longitude"], p["latitude"], p["longitude"])
            if d < min_spacing_km:
                clash = (p, d)
                break
        if clash:
            p, d = clash
            skipped.append({
                "geo_id": c["geo_id"], "need_score": c["need_score"],
                "reason": f"{d:.1f} km from Saturday {p['saturday']} (tract {p['geo_id']}); "
                          f"likely the same people",
                "conflicts_with": p["geo_id"],
            })
            continue

        picked.append({**c, "saturday": len(picked) + 1})

    # Honest uncertainty: is the last pick meaningfully ahead of the best tract we left out?
    left_out = [c for c in rows if c["geo_id"] not in {p["geo_id"] for p in picked}
                and c["geo_id"] not in {s["geo_id"] for s in skipped}]
    near_ties = []
    if picked and left_out:
        cutoff = picked[-1]["need_score"]
        near_ties = [
            {"geo_id": c["geo_id"], "need_score": c["need_score"]}
            for c in left_out if cutoff - c["need_score"] <= tie_margin
        ]

    return {
        "picked": picked,
        "skipped": skipped,
        "near_ties_with_last_pick": near_ties,
        "rules": {
            "n": n,
            "min_spacing_km": min_spacing_km,
            "skip_if_safety_net_within_km": skip_if_safety_net_within_km,
            "tie_margin_points": tie_margin,
        },
        "short_of_n": max(0, n - len(picked)),
    }
