# app/agent/security_check.py
import ast
from app.agent.state import AgentState

# Allow only what you explicitly need in sandbox code:
ALLOWED_IMPORT_ROOTS = {
    "json",
    "datetime",
    "pytz",
    "dateparser",
}

BANNED_CALLS = {
    "open", "eval", "exec", "compile", "__import__",
    "input",
}

BANNED_ATTR_PREFIXES = {
    # prevent stuff like builtins.open via __builtins__ tricks
    "__",
}

def security_check(state: AgentState) -> AgentState:
    code = (state.get("generated_code") or "").strip()
    if not code:
        state["code_error"] = "No code generated."
        return state

    try:
        tree = ast.parse(code)
    except Exception as e:
        state["code_error"] = f"Code parse failed: {e}"
        return state

    for node in ast.walk(tree):
        # Imports must be allowlisted
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".")[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    state["code_error"] = f"Security violation: import {root} is not allowed."
                    return state

        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                state["code_error"] = f"Security violation: from {root} import ... is not allowed."
                return state

        # Dangerous calls blocked
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
                state["code_error"] = f"Security violation: call to {node.func.id} is not allowed."
                return state

        # Block suspicious dunder attribute access (common escape hatch)
        if isinstance(node, ast.Attribute):
            if any(node.attr.startswith(pfx) for pfx in BANNED_ATTR_PREFIXES):
                state["code_error"] = "Security violation: dunder attribute access is not allowed."
                return state

    return state
