# app/agent/sandbox_runner.py
import json
import subprocess
import tempfile
import textwrap
import sys
from sqlalchemy.orm import Session

def sandbox_run(state: dict, db: Session) -> dict:
    # ✅ always increment here so retry routing works
    state["code_attempts"] = int(state.get("code_attempts", 0)) + 1

    code = (state.get("generated_code") or "").strip()
    if not code:
        state["code_error"] = "No generated_code to run."
        return state

    state["code_error"] = None
    state["code_result"] = None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(code))
        path = f.name

    try:
        proc = subprocess.run(
            [sys.executable, path],   # ✅ venv python
            capture_output=True,
            text=True,
            timeout=8,                # ✅ hard stop (prevents infinite loading)
        )

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        if proc.returncode != 0:
            state["code_error"] = err or f"Sandbox failed rc={proc.returncode}"
            return state

        try:
            state["code_result"] = json.loads(out) if out else None
        except Exception:
            state["code_error"] = f"Sandbox output not JSON: {out[:200]}"
            return state

        return state

    except subprocess.TimeoutExpired:
        state["code_error"] = "Sandbox timed out."
        return state

    except Exception as e:
        state["code_error"] = f"{type(e).__name__}: {str(e)}"
        return state
