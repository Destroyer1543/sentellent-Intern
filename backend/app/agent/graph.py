# app/agent/graph.py
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.agent.state import AgentState
from app.agent.planner import planner
from app.agent.checker import check_need_more
from app.agent.responder import build_response
from app.agent.tools_executor import execute_tools

from app.agent.dynamic_codegen import dynamic_codegen
from app.agent.security_check import security_check
from app.agent.sandbox_runner import sandbox_run

from app.db.session import SessionLocal

# -------------------------
# Nodes
# -------------------------

def _planner_node(state: AgentState) -> AgentState:
    # hard stop safety against infinite loops
    if int(state.get("iterations", 0)) >= 5:
        state["needs_more"] = False
        state["fallback_needed"] = False
        if not (state.get("response") or "").strip():
            state["response"] = "I got stuck. Please try rephrasing or provide an exact date/time."
        return state

    out = planner(state)
    out.setdefault("fallback_needed", False)
    out.setdefault("code_attempts", 0)
    out.setdefault("generated_code", None)
    out.setdefault("code_error", None)
    out.setdefault("code_result", None)
    out.setdefault("last_tool_results", [])
    out.setdefault("iterations", int(state.get("iterations", 0)))
    return out

def _route_after_planner(state: AgentState):
    # If planner asked a question, respond (do NOT execute / fallback)
    if state.get("needs_more") and (state.get("response") or "").strip():
        return "respond"

    # If scheduling intent needs datetime extraction, go codegen
    if state.get("time_extraction_needed"):
        return "codegen"

    plan = state.get("plan") or []

    # If planner wrote a response and no plan, respond
    if len(plan) == 0 and (state.get("response") or "").strip():
        return "respond"

    # ✅ If no plan and no response, do NOT codegen (no task).
    # Ask user to rephrase / give specifics.
    if len(plan) == 0:
        state["response"] = (
            "I couldn’t figure out a safe action to take. "
            "Try being explicit, e.g.:\n"
            "- `Show my events tomorrow`\n"
            "- `Schedule 'Sentellent sync' on 2026-01-20 22:00 for 30 minutes`\n"
            "- `Send email to x@y.com subject ... body ...`"
        )
        return "respond"

    return "execute"


def _execute_node(state: AgentState) -> AgentState:
    db: Session = SessionLocal()
    try:
        state["iterations"] = int(state.get("iterations", 0)) + 1
        return execute_tools(state, db)
    finally:
        db.close()

def _checker_node(state: AgentState) -> AgentState:
    out = check_need_more(state)

    # Evaluate only latest tool batch
    results = out.get("last_tool_results") or []
    if results:
        all_failed = all(r.get("ok") is False for r in results)
        unknown_tool = any((r.get("error") or "").lower().startswith("unknown tool") for r in results)
        if all_failed or unknown_tool:
            out["fallback_needed"] = True

    return out

def _route_after_check(state: AgentState):
    if state.get("needs_more"):
        return "planner"
    if state.get("fallback_needed"):
        return "codegen"
    return "respond"

def _codegen_node(state: AgentState) -> AgentState:
    return dynamic_codegen(state)

def _security_node(state: AgentState) -> AgentState:
    return security_check(state)

def _sandbox_node(state: AgentState) -> AgentState:
    db: Session = SessionLocal()
    try:
        return sandbox_run(state, db)
    finally:
        db.close()

def _route_after_sandbox(state: AgentState):
    task = state.get("code_task")

    # ---- Targeted datetime extraction lane ----
    if task == "extract_datetime":
        if state.get("code_error") is not None:
            if int(state.get("code_attempts", 0)) < 5:
                return "codegen"

            state["time_extraction_needed"] = False
            state["code_task"] = None
            state["response"] = (
                "I tried multiple times but couldn’t extract the date/time. "
                "Please provide an exact format like:\n"
                "`Schedule 'Sentellent sync' on 2026-01-20 22:00 for 30 minutes`"
            )
            return "respond"

        payload = state.get("code_result") or {}
        ctx = state.get("time_extraction_context") or {}
        start_iso = payload.get("start_iso")
        end_iso = payload.get("end_iso")

        if start_iso and end_iso:
            state["plan"] = [{
                "tool": "calendar_prepare_event",
                "args": {
                    "summary": ctx.get("summary", "Event"),
                    "start_iso": start_iso,
                    "end_iso": end_iso,
                },
            }]

            state["time_extraction_needed"] = False
            state["code_task"] = None
            state["generated_code"] = None
            state["code_result"] = None
            state["code_error"] = None

            return "execute"

        state["time_extraction_needed"] = False
        state["code_task"] = None
        state["response"] = (
            "I couldn’t reliably extract the date/time. "
            "Try: `Schedule 'Sentellent sync' on 2026-01-20 22:00 for 30 minutes`"
        )
        return "respond"

    # ---- Normal sandbox flow ----
    if state.get("code_error") is None:
        return "respond"

    if int(state.get("code_attempts", 0)) < 5:
        return "codegen"

    return "respond"

def _responder_node(state: AgentState) -> AgentState:
    return build_response(state)

# -------------------------
# Graph wiring
# -------------------------

graph = StateGraph(AgentState)

graph.add_node("planner", _planner_node)
graph.add_node("execute", _execute_node)
graph.add_node("check", _checker_node)

graph.add_node("codegen", _codegen_node)
graph.add_node("security", _security_node)
graph.add_node("sandbox", _sandbox_node)

graph.add_node("respond", _responder_node)

graph.set_entry_point("planner")

graph.add_conditional_edges(
    "planner",
    _route_after_planner,
    {"execute": "execute", "codegen": "codegen", "respond": "respond"},
)

graph.add_edge("execute", "check")

graph.add_conditional_edges(
    "check",
    _route_after_check,
    {"planner": "planner", "codegen": "codegen", "respond": "respond"},
)

graph.add_edge("codegen", "security")
graph.add_edge("security", "sandbox")

graph.add_conditional_edges(
    "sandbox",
    _route_after_sandbox,
    {"execute": "execute", "codegen": "codegen", "respond": "respond"},
)

graph.add_edge("respond", END)

agent = graph.compile()
