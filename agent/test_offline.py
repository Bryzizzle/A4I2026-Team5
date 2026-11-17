"""Offline tests: no Gemini, no BigQuery, no Toolbox server.

    cd agent && python -m unittest test_offline -v

Checks that the agent tree builds, the tool split holds (planner never gets auditor tools),
and the two tools reject and revise the plan the way the real Fulton run needs them to.
"""

import filecmp
import os
import unittest
import warnings

import yaml

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))

from clinic_planner import tools  # noqa: E402


class FakeContext:
    def __init__(self):
        self.state = {}


def row(gid, score, lat, lon, pop, km=3.0, missing=0, no_veh=30.0):
    return {"geo_id": gid, "need_score": score, "need_rank": 0, "latitude": lat,
            "longitude": lon, "km_to_safety_net": km, "total_pop": pop,
            "pct_uninsured": 25.0, "pct_no_vehicle": no_veh, "pct_limited_english": 2.0,
            "components_missing": missing, "reason": f"reason {gid}"}


# Shaped like the real Fulton top tracts: Saturday 2 was scored with a missing input and sits
# 0.9 km from a complete-data neighbour; Saturday 4 is small and tied with a far larger tract.
FULTON_LIKE = [
    row("011430", 78.2, 33.600, -84.500, 4338, km=13.5),
    row("011421", 78.1, 33.614, -84.500, 3933, km=14.6),   # 1.6 km from 011430
    row("006801", 77.2, 33.750, -84.420, 2297, km=1.4, missing=1),
    row("011431", 77.0, 33.6045, -84.500, 1970, km=13.9),  # 0.5 km from 011430
    row("007604", 76.9, 33.700, -84.300, 3191, km=4.4),
    row("006802", 76.2, 33.758, -84.420, 1384, km=1.26, no_veh=67.6),  # 0.9 km from 006801
    row("006602", 76.15, 33.850, -84.350, 1050, km=2.2, no_veh=46.1),
    row("008701", 74.4, 33.950, -84.250, 3333, km=4.4),
    row("007808", 74.3, 34.050, -84.200, 3749, km=1.6, no_veh=55.8),
]


class ToolsTest(unittest.TestCase):
    def setUp(self):
        tools.fetch_candidates = lambda: [dict(r) for r in FULTON_LIKE]

    def test_vendored_picker_matches_data_lane(self):
        self.assertTrue(filecmp.cmp(os.path.join(HERE, "clinic_planner", "saturdays.py"),
                                    os.path.join(HERE, "..", "data", "saturdays.py"),
                                    shallow=False),
                        "agent/clinic_planner/saturdays.py drifted from data/saturdays.py")

    def test_round_one_matches_the_real_run(self):
        ctx = FakeContext()
        out = tools.plan_saturdays(ctx)
        self.assertEqual([p["geo_id"] for p in out["picked"]],
                         ["011430", "006801", "007604", "006602"])
        self.assertEqual(ctx.state["picked_tract_ids"], "011430,006801,007604,006602")
        self.assertEqual(ctx.state["plan_round"], 1)

    def test_reviewer_rejects_then_planner_revises_then_approves(self):
        ctx = FakeContext()
        tools.plan_saturdays(ctx)

        r1 = tools.check_plan_rules(ctx)
        self.assertFalse(r1["approved"])
        rules = {f["rule"]: f for f in r1["findings"]}
        self.assertEqual(rules["incomplete_data_displaced_complete_neighbour"]["reject"], "006801")
        self.assertEqual(rules["incomplete_data_displaced_complete_neighbour"]["prefer"], "006802")
        self.assertEqual(rules["tie_broken_by_population_reached"]["reject"], "006602")
        self.assertFalse(ctx.state["plan_approved"])

        out2 = tools.plan_saturdays(ctx)   # exclusions come from state, not from the model
        ids2 = [p["geo_id"] for p in out2["picked"]]
        self.assertNotIn("006801", ids2)
        self.assertNotIn("006602", ids2)
        self.assertIn("006802", ids2)
        self.assertEqual(ctx.state["plan_round"], 2)

        r2 = tools.check_plan_rules(ctx)
        self.assertTrue(r2["approved"], r2)
        hist = ctx.state["plan_history"]
        self.assertEqual([h["round"] for h in hist], [1, 2])
        self.assertIn("006801", [p["geo_id"] for p in hist[0]["picked"]])
        self.assertNotIn("006801", [p["geo_id"] for p in hist[1]["picked"]])
        self.assertIn("latitude", hist[1]["picked"][0])
        self.assertTrue(ctx.state["plan_approved"])
        self.assertEqual(len(ctx.state["rejection_log"]), 2)

    def test_complete_plan_is_approved_first_time(self):
        tools.fetch_candidates = lambda: [
            row("A", 90, 33.6, -84.5, 3000), row("B", 80, 33.8, -84.5, 3000),
            row("C", 70, 34.0, -84.5, 3000), row("D", 60, 34.2, -84.5, 3000)]
        ctx = FakeContext()
        tools.plan_saturdays(ctx)
        self.assertTrue(tools.check_plan_rules(ctx)["approved"])


class AgentTreeTest(unittest.TestCase):
    def test_tree_and_tool_split(self):
        from clinic_planner.agent import auditor, planner, reviewer, root_agent
        names = [a.name for a in root_agent.sub_agents]
        self.assertEqual(names, ["evidence", "plan_review", "auditor", "explainer", "reporter"])

        def toolset_names(agent):
            return {t._delegate._ToolboxToolset__toolset_name for t in agent.tools
                    if type(t).__name__ == "ToolboxToolset"}

        self.assertEqual(toolset_names(planner), {"planner_tools"})
        self.assertEqual(toolset_names(auditor), {"auditor_tools"})
        self.assertEqual([getattr(t, "__name__", "") for t in reviewer.tools], ["check_plan_rules"])
        for a in (planner, auditor):
            self.assertEqual(a.include_contents, "none")

    def test_output_keys_are_distinct(self):
        from clinic_planner.agent import evidence
        keys = [a.output_key for a in evidence.sub_agents]
        self.assertEqual(len(keys), len(set(keys)))


class PromptPlaceholderTest(unittest.TestCase):
    """A required {key} that no agent or tool writes crashes the run (KeyError in ADK)."""

    WRITTEN = {"evidence_need", "evidence_coverage", "evidence_respiratory", "plan", "review",
               "audit", "flyer", "clinic_plan",                       # output_keys
               "plan_data", "plan_history", "picked_tract_ids", "plan_round",  # plan_saturdays
               "plan_approved", "review_findings", "excluded_geo_ids",
               "rejection_log"}                                       # check_plan_rules

    def test_every_required_placeholder_is_written_somewhere(self):
        import re
        from clinic_planner import prompts
        for name in dir(prompts):
            text = getattr(prompts, name)
            if not name.isupper() or not isinstance(text, str):
                continue
            for key, optional in re.findall(r"\{([a-z_]+)(\??)\}", text):
                self.assertIn(key, self.WRITTEN, f"{name} uses unknown state key {{{key}}}")
            self.assertNotRegex(text, r"\{(?![a-z_]+\??\})", f"{name} has a stray brace")


class ToolboxConfigTest(unittest.TestCase):
    def test_tools_yaml_is_valid_and_split(self):
        with open(os.path.join(HERE, "toolbox", "tools.yaml.tmpl")) as f:
            docs = [d for d in yaml.safe_load_all(f) if d]
        tools_ = {d["name"]: d for d in docs if d["kind"] == "tool"}
        sets = {d["name"]: d["tools"] for d in docs if d["kind"] == "toolset"}
        for t in tools_.values():
            self.assertEqual(t["type"], "bigquery-sql")
            for p in t.get("parameters", []):
                self.assertIn("@" + p["name"], t["statement"])
        self.assertTrue(set(sets["planner_tools"]).isdisjoint(sets["auditor_tools"]))
        for name in sets["planner_tools"]:
            self.assertNotIn("equity_audit", tools_[name]["statement"])
        self.assertEqual(set(sets["planner_tools"]) | set(sets["auditor_tools"]), set(tools_))


if __name__ == "__main__":
    unittest.main()
