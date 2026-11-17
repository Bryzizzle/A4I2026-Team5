"""Clinic Plan: a multi-agent system that decides where one mobile clinic parks on four Saturdays.

    clinic_plan (SequentialAgent)
    ├── evidence (ParallelAgent)                     three independent lookups, one hop
    │   ├── need_scout         -> evidence_need          [MCP Toolbox: planner_tools]
    │   ├── coverage_scout     -> evidence_coverage      [MCP Toolbox: planner_tools]
    │   └── respiratory_scout  -> evidence_respiratory   [MCP Toolbox: planner_tools]
    ├── plan_review (LoopAgent, max 3 rounds)        the system rejects its own answers here
    │   ├── planner            -> plan                   [our tool: plan_saturdays]
    │   ├── reviewer           -> review                 [our tool: check_plan_rules]
    │   └── approval_gate      ends the loop when state.plan_approved is true
    ├── auditor                -> audit                  [MCP Toolbox: auditor_tools ONLY]
    ├── explainer              -> flyer                  (no tools; English + Spanish)
    └── reporter               -> clinic_plan            the four-part Clinic Plan

State keys written by one agent and read by another: evidence_* (scouts -> planner, reporter),
plan (planner -> reviewer, explainer, reporter), plan_data / excluded_geo_ids (plan_saturdays <->
check_plan_rules), picked_tract_ids (planner -> auditor), audit (auditor -> reporter),
flyer (explainer -> reporter).

Deliberately isolated: the auditor, explainer and reporter run with include_contents="none", so
they see only the state keys named in their instructions, never the planner's conversation.
The planner, reviewer and scouts are never given the auditor's toolset.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools.toolbox_toolset import ToolboxToolset

from . import prompts
from .tools import check_plan_rules, plan_saturdays

MODEL = os.environ.get("A4I_MODEL", "gemini-3.6-flash")

# On Agent Runtime, GOOGLE_CLOUD_LOCATION is the deployment region (e.g. us-central1), while
# Gemini 3.x is served from "global". A4I_MODEL_LOCATION lets the model use its own endpoint.
if os.environ.get("A4I_MODEL_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ["A4I_MODEL_LOCATION"]
TOOLBOX_URL = os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000")


def _toolset(name: str) -> ToolboxToolset:
    """One MCP Toolbox toolset. On Cloud Run the Toolbox service is private, so authenticate
    with the agent's service identity (an ID token for the Toolbox URL)."""
    kwargs = {}
    if TOOLBOX_URL.startswith("https://"):
        from toolbox_adk import CredentialStrategy
        kwargs["credentials"] = CredentialStrategy.workload_identity(target_audience=TOOLBOX_URL)
    return ToolboxToolset(TOOLBOX_URL, toolset_name=name, **kwargs)


def _reset_run_state(callback_context: CallbackContext) -> Optional[object]:
    """Each request plans from scratch: clear the previous request's rejections."""
    s = callback_context.state
    s["excluded_geo_ids"] = []
    s["rejection_log"] = []
    s["plan_history"] = []
    s["plan_round"] = 0
    s["plan_approved"] = False
    return None


class ApprovalGate(BaseAgent):
    """Ends the plan/review loop once the reviewer's rule check has approved the plan."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if ctx.session.state.get("plan_approved"):
            yield Event(invocation_id=ctx.invocation_id, author=self.name,
                        actions=EventActions(escalate=True))


def _scout(name: str, instruction: str, output_key: str) -> LlmAgent:
    return LlmAgent(
        name=name,
        model=MODEL,
        instruction=instruction,
        tools=[_toolset("planner_tools")],
        output_key=output_key,          # distinct per branch: parallel branches share state
        include_contents="none",
    )


evidence = ParallelAgent(
    name="evidence",
    description="Gathers need, coverage and regional respiratory evidence concurrently.",
    sub_agents=[
        _scout("need_scout", prompts.NEED_SCOUT, "evidence_need"),
        _scout("coverage_scout", prompts.COVERAGE_SCOUT, "evidence_coverage"),
        _scout("respiratory_scout", prompts.RESPIRATORY_SCOUT, "evidence_respiratory"),
    ],
)

planner = LlmAgent(
    name="planner",
    model=MODEL,
    description="Picks four Saturday stops from planner-safe data and explains each.",
    instruction=prompts.PLANNER,
    tools=[plan_saturdays, _toolset("planner_tools")],
    output_key="plan",
    include_contents="none",
)

reviewer = LlmAgent(
    name="reviewer",
    model=MODEL,
    description="Tries to reject the plan using deterministic rules.",
    instruction=prompts.REVIEWER,
    tools=[check_plan_rules],
    output_key="review",
    include_contents="none",
)

plan_review = LoopAgent(
    name="plan_review",
    description="Plan, review, revise: up to three rounds.",
    sub_agents=[planner, reviewer, ApprovalGate(name="approval_gate")],
    max_iterations=3,
)

auditor = LlmAgent(
    name="auditor",
    model=MODEL,
    description="Audits the final plan against demographics the planner never saw.",
    instruction=prompts.AUDITOR,
    tools=[_toolset("auditor_tools")],
    output_key="audit",
    include_contents="none",
)

explainer = LlmAgent(
    name="explainer",
    model=MODEL,
    description="Writes plain-language English and Spanish material for the neighborhoods.",
    instruction=prompts.EXPLAINER,
    output_key="flyer",
    include_contents="none",
)

reporter = LlmAgent(
    name="reporter",
    model=MODEL,
    description="Assembles the four-part Clinic Plan and shows where the agents disagreed.",
    instruction=prompts.REPORTER,
    output_key="clinic_plan",
    include_contents="none",
)

root_agent = SequentialAgent(
    name="clinic_plan",
    description="Decides where one mobile clinic parks on four Saturdays, audits who the plan "
                "lands on, and explains it to the neighborhoods.",
    sub_agents=[evidence, plan_review, auditor, explainer, reporter],
    before_agent_callback=_reset_run_state,
)
