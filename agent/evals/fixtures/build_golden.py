"""Build fixtures/golden_trace.json: a known-good run for testing the checks themselves.

    cd agent && python -m evals.fixtures.build_golden

SYNTHETIC. Not a recording of the real agents. The plan rounds, rejections and session.state are
produced by running OUR REAL TOOLS (plan_saturdays, check_plan_rules) on the Fulton-shaped rows in
test_offline.py, so the state is exactly what the tools write. The agent texts are hand-written
to obey every prompt rule. Audit and coverage figures are taken from data/FINDINGS.md; respiratory
values are placeholders. Use it to prove each check passes good output and fails planted faults,
never as evidence about the agents.
"""

from __future__ import annotations

import json
from pathlib import Path

from clinic_planner import tools

HERE = Path(__file__).resolve().parent
P = "13121"


def row(gid, score, lat, lon, pop, km, missing=0, unins=None, no_veh=None, reason=""):
    return {"geo_id": P + gid, "need_score": score, "need_rank": 0, "latitude": lat, "longitude": lon,
            "km_to_safety_net": km, "total_pop": pop, "pct_uninsured": unins,
            "pct_no_vehicle": no_veh, "pct_limited_english": None, "components_missing": missing,
            "reason": reason}


ROWS = [
    row("011430", 78.2, 33.600, -84.500, 4338, 13.5, unins=25, no_veh=7, reason="uninsured, far from care"),
    row("011421", 78.1, 33.614, -84.500, 3933, 14.6, reason="uninsured, far from care"),
    row("006801", 77.2, 33.750, -84.420, 2297, 1.4, missing=1, unins=35, reason="highest uninsured"),
    row("011431", 77.0, 33.6045, -84.500, 1970, 13.9, reason="uninsured, far from care"),
    row("007604", 76.9, 33.700, -84.300, 3191, 4.4, unins=20, no_veh=33, reason="mobility, chronic disease"),
    row("006802", 76.2, 33.758, -84.420, 1384, 1.26, no_veh=67.6, reason="no vehicle"),
    row("006602", 76.15, 33.850, -84.350, 1050, 2.2, unins=22, no_veh=46.1, reason="no vehicle"),
    row("008701", 74.4, 33.950, -84.250, 3333, 4.4, reason="uninsured"),
    row("007808", 74.3, 34.050, -84.200, 3749, 1.6, no_veh=55.8, reason="no vehicle"),
]

COVERAGE = [{"county_fips": "13121", "tracts_total": 326, "population_total": 1066710,
             "tracts_scored": 325, "tracts_not_scored": 1, "safety_net_sites": 55,
             "people_over_5km_from_safety_net": 443800, "worst_km_to_safety_net": 28.6,
             "shortage_areas_designated": 0, "disease_hsa_counties": "Clayton, DeKalb, Fulton, Gwinnett",
             "pm25_p90_over_p10": 1.049}]
RESP = [{"week_end": f"2026-{d}", "percent_visits_covid": 1.0, "percent_visits_influenza": 1.0,
         "percent_visits_rsv": 1.0, "hsa": "placeholder HSA",
         "hsa_counties": "Clayton, DeKalb, Fulton, Gwinnett"} for d in ("11-07", "10-31")]
AUDIT_PLAN = [
    ("hispanic_pop", "ACS", .07, .29, 4.11), ("limited English", "SVI", .018, .061, 3.49),
    ("no vehicle", "SVI", .10, .22, 2.12), ("below poverty (approx)", "ACS", .13, .20, 1.56),
    ("black_pop", "ACS", .43, .56, 1.30), ("age 65+", "SVI", .12, .05, .39),
    ("white_pop", "ACS", .39, .09, .22), ("asian_pop", "ACS", .07, .01, .09)]
AUDIT_TOP = [
    ("below poverty (approx)", .13, .31, 2.41), ("hispanic_pop", .07, .13, 1.86),
    ("black_pop", .43, .74, 1.72), ("limited English", .018, .029, 1.66), ("age 65+", .12, .12, 1.0),
    ("white_pop", .39, .09, .23), ("asian_pop", .07, .01, .13)]

TEXT = {
    "need_scout": """- **011430** (78.2): uninsured adults, nearest safety-net site 13.5 km *(modeled; straight-line upper bound)*.
- **011421** (78.1) and **011431** (77.0) sit next to 011430.
- **006801** (77.2): 35% uninsured *(modeled)*; scored with 1 input missing.
- **006802** (76.2): 68% of households have no car *(survey)*.""",
    "coverage_scout": """- 325 of 326 tracts scored; 1 not scored.
- 55 safety-net sites; 443,800 people live more than 5 km from one; worst 28.6 km *(straight-line upper bound)*.
- **0 live shortage areas.** No federal signal is not the same as no problem.
- Respiratory data is one Health Service Area figure for Clayton, DeKalb, Fulton and Gwinnett.
- PM2.5 p90/p10 = 1.049: air cannot separate neighborhoods.""",
    "respiratory_scout": """Across the last weeks the shares are flat. The Health Service Area covers Clayton, DeKalb, Fulton and Gwinnett.
This is a multi-county regional figure; it says nothing about any neighborhood or tract and must not be used to choose between tracts.""",
    "planner_1": """**Round 1** *(tract level; uninsured modeled, no-vehicle survey, distances straight-line upper bounds)*

| Saturday | Tract | Score | People | Why |
|---|---|---|---|---|
| 1 | 011430 | 78.2 | 4,338 | 25% uninsured *(modeled)*, 13.5 km *(straight-line)* |
| 2 | 006801 | 77.2 | 2,297 | 35% uninsured *(modeled)*; no vehicle data |
| 3 | 007604 | 76.9 | 3,191 | 33% no vehicle *(survey)* |
| 4 | 006602 | 76.2 | 1,050 | 46% no vehicle *(survey)* |

Passed over: 011421, 011431, 006802. Near-ties with Saturday 4: 008701 and 007808.""",
    "reviewer_1": """**REJECTED**
- 006801 → 006802: scored with a missing input; tied with a complete-data neighbour 0.9 km away.
- 006602 → 008701: tied with a tract three times its size.""",
    "planner_2": """Changed from round 1: the reviewer rejected 006801 (incomplete data) and 006602 (smaller tied tract).

*Tract level. Uninsured is modeled (CDC PLACES); no vehicle is a survey estimate (SVI); distances are straight-line upper bounds.*

| Saturday | Tract | Score | People | Why |
|---|---|---|---|---|
| 1 | 011430 | 78.2 | 4,338 | 25% uninsured *(modeled)*, 13.5 km to a safety-net site *(straight-line)* |
| 2 | 007604 | 76.9 | 3,191 | 20% uninsured *(modeled)*, 33% no vehicle *(survey)* |
| 3 | 006802 | 76.2 | 1,384 | 68% of households have no car *(survey)* |
| 4 | 008701 | 74.4 | 3,333 | Larger tied tract; reaches more people |

Passed over: 011421 and 011431, within 1.6 km of Saturday 1.
Near-tie with Saturday 4: 007808 (74.3). This is a tie: the inputs are modeled.""",
    "reviewer_2": """**APPROVED**
- Saturday 4 (008701) is 0.1 points ahead of 007808: a tie a person may overrule.""",
    "auditor": """| Group | County | Plan | Ratio |
|---|---|---|---|
| Hispanic | 7% | 29% | 4.11× |
| Limited English | 1.8% | 6.1% | 3.49× |
| No vehicle | 10% | 22% | 2.12× |
| Below poverty | 13% | 20% | 1.56× |
| Black | 43% | 56% | 1.30× |
| Age 65+ | 12% | 5% | 0.39× |
| White | 39% | 9% | 0.22× |
| Asian | 7% | 1% | 0.09× |

Top 10% of tracts: below poverty 2.41×, Hispanic 1.86×, Black 1.72×, limited English 1.66×, age 65+ 1.00×.

The plan lands on poorer, carless neighborhoods. Below 0.5×: age 65+ (0.39×), because the uninsured input counts adults 18-64 and almost everyone over 65 has Medicare; White and Asian residents (0.22×, 0.09×).
Limited English is 3.49×: the outreach material needs Spanish.
Four tracts is a tiny sample; read it next to the top-decile audit.""",
}

FLYER_EN = ("A free health check is coming to your neighborhood. Come on Saturday at TIME to ADDRESS. "
            "A nurse will check your blood pressure and blood sugar. We can help you find a clinic. "
            "You do not need insurance.")
FLYER_ES = ("Un chequeo de salud gratis viene a su vecindario. Venga el sábado a las TIME a ADDRESS. "
            "Una enfermera le revisa la presión y el azúcar en la sangre. Le ayudamos a encontrar una "
            "clínica. No necesita seguro.")
TEXT["explainer"] = "\n\n".join(
    [f"## Saturday {i}\n### English\n{FLYER_EN}\n### Español\n{FLYER_ES}" for i in range(1, 5)] +
    ["## Neighborhoods not picked\n### English\nThe van can only go to four places this month. "
     "It is going to a place near you, so it does not see the same people twice. You are welcome there.\n"
     "### Español\nLa camioneta solo va a cuatro lugares este mes. Va a un lugar cerca de usted, para "
     "no ver a las mismas personas dos veces. Usted es bienvenido allí."])
TEXT["reporter"] = f"""## 1. Where the van goes, and why
*(planner, approved by the reviewer in round 2)*
{TEXT['planner_2']}

## 2. What we could not tell you
{TEXT['coverage_scout']}
Respiratory context is regional (4 counties): {TEXT['respiratory_scout']}

## 3. Who this plan lands on
{TEXT['auditor']}

## 4. What we hand to the neighborhood
{TEXT['explainer']}

## Where our agents disagreed
- Round 1: the reviewer rejected 006801 in favor of 006802 (incomplete data).
- Round 1: the reviewer rejected 006602 in favor of 008701 (smaller tied tract).
- The plan reaches residents over 65 at 0.39×; the audit reports this and does not re-plan."""


class Ctx:
    def __init__(self):
        self.state = {"excluded_geo_ids": [], "rejection_log": [], "plan_history": [],
                      "plan_round": 0, "plan_approved": False}


def build() -> dict:
    tools.fetch_candidates = lambda: [dict(r) for r in ROWS]
    ctx = Ctx()
    events, t = [], [1_800_000_000.0]

    def ev(author, parts=None, delta=None, dt=0.5):
        t[0] += dt
        e = {"author": author, "timestamp": round(t[0], 3), "actions": {"stateDelta": delta or {}}}
        if parts:
            e["content"] = {"role": "model", "parts": parts}
        events.append(e)

    call = lambda n, a=None: [{"functionCall": {"name": n, "args": a or {}}}]
    resp = lambda n, r: [{"functionResponse": {"name": n, "response": r}}]
    text = lambda s: [{"text": s}]

    def snapshot(before):
        return {k: v for k, v in json.loads(json.dumps(ctx.state)).items() if before.get(k) != v}

    # parallel scouts: interleaved timestamps
    ev("need_scout", call("top_need_tracts", {"limit": 15}), dt=0.1)
    ev("coverage_scout", call("county_coverage"), dt=0.1)
    ev("respiratory_scout", call("regional_respiratory_trend", {"weeks": 8}), dt=0.1)
    ev("coverage_scout", resp("county_coverage", {"result": json.dumps(COVERAGE)}))
    ev("respiratory_scout", resp("regional_respiratory_trend", {"result": json.dumps(RESP)}))
    ev("need_scout", resp("top_need_tracts", {"result": json.dumps(ROWS)}))
    ev("respiratory_scout", text(TEXT["respiratory_scout"]), {"evidence_respiratory": TEXT["respiratory_scout"]})
    ev("coverage_scout", text(TEXT["coverage_scout"]), {"evidence_coverage": TEXT["coverage_scout"]})
    ev("need_scout", text(TEXT["need_scout"]), {"evidence_need": TEXT["need_scout"]})

    for rnd in (1, 2):
        before = json.loads(json.dumps(ctx.state))
        ev("planner", call("plan_saturdays"))
        out = tools.plan_saturdays(ctx)
        ev("planner", resp("plan_saturdays", json.loads(json.dumps(out))), snapshot(before))
        ev("planner", text(TEXT[f"planner_{rnd}"]), {"plan": TEXT[f"planner_{rnd}"]})
        before = json.loads(json.dumps(ctx.state))
        ev("reviewer", call("check_plan_rules"))
        out = tools.check_plan_rules(ctx)
        ev("reviewer", resp("check_plan_rules", json.loads(json.dumps(out))), snapshot(before))
        ev("reviewer", text(TEXT[f"reviewer_{rnd}"]), {"review": TEXT[f"reviewer_{rnd}"]})
    assert ctx.state["plan_approved"], "fixture expects approval in round 2"

    ev("auditor", call("audit_plan", {"tract_ids_csv": ctx.state["picked_tract_ids"]}))
    ev("auditor", resp("audit_plan", {"result": json.dumps([
        {"grp": g, "source": s, "county_share": c, "plan_share": p, "ratio_vs_county": r}
        for g, s, c, p, r in AUDIT_PLAN])}))
    ev("auditor", call("audit_top_decile"))
    ev("auditor", resp("audit_top_decile", {"result": json.dumps([
        {"grp": g, "county_share": c, "top_decile_share": p, "ratio_vs_county": r,
         "tracts_selected": 33, "acs_match_rate": 1.0} for g, c, p, r in AUDIT_TOP])}))
    for a, key in (("auditor", "audit"), ("explainer", "flyer"), ("reporter", "clinic_plan")):
        ev(a, text(TEXT[a]), {key: TEXT[a]})

    state = json.loads(json.dumps(ctx.state))
    for e in events:
        state.update(e["actions"]["stateDelta"])
    return {"case_id": "baseline", "prompt": "Plan next month's four Saturdays.", "repeat": 0,
            "seconds": round(t[0] - 1_800_000_000.0, 1), "error": None,
            "_note": "SYNTHETIC fixture for testing the checks; see build_golden.py",
            "events": events, "state": state}


if __name__ == "__main__":
    out = HERE / "golden_trace.json"
    out.write_text(json.dumps(build(), indent=1))
    print("wrote", out)
