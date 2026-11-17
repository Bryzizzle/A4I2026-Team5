"""Offline tests for the console backend: a fake Agent Runtime, no cloud calls.

    python -m unittest frontend.test_app -v      (from the repo root)
"""

import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from frontend import app as console

# Event shapes as Agent Runtime streams them (snake_case dicts).
FAKE_EVENTS = [
    {"author": "need_scout", "content": {"parts": [{"function_call": {
        "name": "top_need_tracts", "args": {"limit": 15}}}]}},
    {"author": "need_scout", "content": {"parts": [{"text": "Top tracts..."}]},
     "actions": {"state_delta": {"evidence_need": "Top tracts..."}}},
    {"author": "planner", "content": {"parts": [{"function_response": {
        "name": "plan_saturdays", "response": {"round": 1}}}]},
     "actions": {"state_delta": {"plan_round": 1, "plan_data": {
         "round": 1, "picked": [], "candidates": [{"geo_id": "x"}] * 60}}}},
    {"author": "reviewer", "content": {"parts": [{"function_response": {
        "name": "check_plan_rules", "response": {"approved": False, "findings": []}}}]},
     "actions": {"state_delta": {"plan_approved": False}}},
    {"author": "approval_gate", "actions": {"escalate": True}},
    {"author": "reporter", "content": {"parts": [{"thought": True, "text": "hidden"},
                                                 {"text": "Clinic Plan"}]}},
]
FINAL_STATE = {"plan_round": 2, "plan_approved": True, "rejection_log": [{"reject": "006801"}],
               "plan_data": {"picked": [], "candidates": [1, 2, 3]}, "_internal": "dropped"}


class FakeRemote:
    async def async_create_session(self, user_id):
        return {"id": "sess-1"}

    async def async_stream_query(self, user_id, session_id, message):
        for e in FAKE_EVENTS:
            yield e

    async def async_get_session(self, user_id, session_id):
        return {"state": FINAL_STATE}


def parse_sse(text):
    out = []
    for chunk in text.split("\n\n"):
        if not chunk.strip() or chunk.startswith(":"):
            continue
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        console.LAST_RUN = os.path.join(self.tmp.name, "last.json")
        console.SAMPLE_RUN = os.path.join(self.tmp.name, "sample.json")
        console.get_remote = lambda: FakeRemote()
        self.client = TestClient(console.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalize_kinds(self):
        msgs = [m for e in FAKE_EVENTS for m in console.normalize_event(e, 0.0)]
        kinds = [(m["author"], m["kind"]) for m in msgs]
        self.assertIn(("need_scout", "tool_call"), kinds)
        self.assertIn(("planner", "tool_result"), kinds)
        self.assertIn(("approval_gate", "escalate"), kinds)
        texts = [m["text"] for m in msgs if m["kind"] == "text"]
        self.assertNotIn("hidden", texts)            # model thoughts are not shown
        review = [m for m in msgs if m.get("tool") == "check_plan_rules"][0]
        self.assertFalse(review["approved"])
        plan_delta = [m for m in msgs if m["kind"] == "state" and m["author"] == "planner"][0]
        self.assertNotIn("candidates", plan_delta["state_delta"]["plan_data"])

    def test_live_run_streams_and_records(self):
        r = self.client.post("/api/run", json={})
        self.assertEqual(r.status_code, 200)
        events = parse_sse(r.text)
        names = [n for n, _ in events]
        self.assertEqual(names[0], "session")
        self.assertEqual(names[-2:], ["final", "done"])
        final = dict(events)["final"]["state"]
        self.assertEqual(final["plan_round"], 2)
        self.assertNotIn("_internal", final)
        self.assertNotIn("candidates", final["plan_data"])
        self.assertTrue(os.path.exists(console.LAST_RUN))

    def test_replay_uses_last_run(self):
        self.client.post("/api/run", json={})
        events = parse_sse(self.client.get("/api/replay?speed=50").text)
        self.assertEqual(events[0][1]["mode"], "replay")
        self.assertEqual(events[-1][0], "done")

    def test_replay_without_recording_is_404(self):
        self.assertEqual(self.client.get("/api/replay").status_code, 404)

    def test_error_is_reported_not_dropped(self):
        class Broken(FakeRemote):
            async def async_stream_query(self, user_id, session_id, message):
                raise RuntimeError("model not found")
                yield  # pragma: no cover
        console.get_remote = lambda: Broken()
        events = parse_sse(self.client.post("/api/run", json={}).text)
        self.assertIn("error", [n for n, _ in events])
        self.assertEqual(events[-1][0], "done")

    def test_index_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
