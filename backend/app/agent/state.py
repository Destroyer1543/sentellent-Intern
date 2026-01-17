# app/agent/state.py
from typing import TypedDict, Any, Optional, List, Dict

class AgentState(TypedDict, total=False):
    user_id: str
    input: str

    # planner output
    plan: List[Dict[str, Any]]
    needs_more: bool
    response: str

    # tool executor output
    tool_results: List[Dict[str, Any]]
    last_tool_results: List[Dict[str, Any]]
    pending_action: Optional[Dict[str, Any]]

    # loop bookkeeping
    iterations: int

    # dynamic code fallback
    fallback_needed: bool
    code_attempts: int
    generated_code: Optional[str]
    code_error: Optional[str]
    code_result: Optional[Any]

    # multi-turn slot filling (DB-hydrated)
    memories: Dict[str, Any]              # ✅ dict, not list
    pending_intent: Optional[Dict[str, Any]]

    # write-back signals for main.py
    pending_intent_op: Optional[str]      # "save" | "clear" | None
    pending_intent_out: Optional[Dict[str, Any]]

    # ✅ fields used by graph/codegen lane
    time_extraction_needed: bool
    time_extraction_context: Optional[Dict[str, Any]]
    code_task: Optional[str]
