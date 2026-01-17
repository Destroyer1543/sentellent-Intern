# app/agent/checker.py
from __future__ import annotations

def check_need_more(state: dict) -> dict:
    iters = int(state.get("iterations", 0))
    if iters >= 5:
        state["needs_more"] = False
        return state

    # If planner asked a question, STOP looping and let responder show it.
    if state.get("needs_more") and (state.get("response") or "").strip() and not (state.get("plan") or []):
        state["needs_more"] = False
        state["fallback_needed"] = False
        return state

    # If we have a pending action waiting for confirmation, stop looping.
    if state.get("pending_action"):
        state["needs_more"] = False
        state["fallback_needed"] = False
        return state

    plan = state.get("plan") or []
    last_batch = state.get("last_tool_results") or []
    history = state.get("tool_results") or []

    # If planner gave nothing AND no tools ran yet, we should fallback (not loop-planner forever)
    if not plan and not history and not (state.get("response") or "").strip():
        state["fallback_needed"] = True
        state["needs_more"] = False
        return state

    # If tools just ran and any failed, try planner again once unless graph marks fallback_needed elsewhere
    if last_batch:
        failed = [r for r in last_batch if r.get("ok") is False]
        if failed:
            state["needs_more"] = True
            return state

    state["needs_more"] = False
    return state
