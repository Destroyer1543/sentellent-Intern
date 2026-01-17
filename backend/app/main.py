# main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

import json
import base64
import os

from app.agent.graph import agent  # compiled langgraph agent

# Google OAuth
from app.google.oauth import build_flow, creds_to_dict
from app.db.google_tokens import save_google_token, load_google_token
from app.db.session import SessionLocal  # DB session factory

# ✅ DB hydration
from app.db.memories import load_memories
from app.db.pending_actions import get_pending_action

# ✅ Pending intent DB
from app.db.pending_intent import (
    get_pending_intent,
    save_pending_intent,
    clear_pending_intent,
)

from fastapi.middleware.cors import CORSMiddleware

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

app = FastAPI(title="Sentellent Contextual Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# State helpers (OAuth)
# ------------------------

def encode_state(data: dict) -> str:
    raw = json.dumps(data).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")

def decode_state(state: str) -> dict:
    raw = base64.urlsafe_b64decode(state.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))

# ------------------------
# Request Models
# ------------------------

class ChatRequest(BaseModel):
    user_id: str
    message: str

class ConfirmRequest(BaseModel):
    user_id: str
    confirmation: str  # "yes" / "no"
    instruction: str | None = None

# ------------------------
# Health
# ------------------------

@app.get("/health")
def health():
    return {"status": "ok"}

def _build_initial_state(db, user_id: str, message: str) -> dict:
    memories = load_memories(db, user_id=user_id)  # ✅ dict
    pending_action = get_pending_action(db, user_id=user_id)  # ✅ hydrate from DB
    pending_intent = get_pending_intent(db, user_id=user_id)  # ✅ hydrate from DB

    return {
        "user_id": user_id,
        "input": message,

        "memories": memories,
        "pending_action": pending_action,
        "pending_intent": pending_intent,

        "plan": [],
        "tool_results": [],
        "last_tool_results": [],
        "needs_more": False,
        "iterations": 0,
        "response": "",

        # dynamic lane defaults
        "fallback_needed": False,
        "code_attempts": 0,
        "generated_code": None,
        "code_error": None,
        "code_result": None,

        # flags used by graph/codegen lane
        "time_extraction_needed": False,
        "time_extraction_context": None,
        "code_task": None,

        # ✅ write-back signals (planner sets these)
        "pending_intent_op": None,     # "save" | "clear" | None
        "pending_intent_out": None,    # dict when saving
    }

def _apply_pending_intent_writeback(db, result: dict):
    op = result.get("pending_intent_op")
    user_id = result.get("user_id")

    if not user_id:
        return

    if op == "save":
        payload = result.get("pending_intent_out") or {}
        if isinstance(payload, dict) and payload:
            save_pending_intent(db, user_id=user_id, intent=payload)

    elif op == "clear":
        clear_pending_intent(db, user_id=user_id)

# ------------------------
# Chat
# ------------------------

@app.post("/chat")
def chat(req: ChatRequest):
    db = SessionLocal()
    try:
        state = _build_initial_state(db, req.user_id, req.message)
        result = agent.invoke(state)

        # ✅ persist pending_intent changes
        _apply_pending_intent_writeback(db, result)

        return {
            "reply": result.get("response", "") or "OK",
            "pending_action": result.get("pending_action"),
            "pending_intent": result.get("pending_intent"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

# ------------------------
# Google OAuth
# ------------------------

@app.get("/auth/google/start")
def google_start(user_id: str, request: Request):
    redirect_uri = str(request.url_for("google_callback"))
    flow = build_flow(redirect_uri=redirect_uri)

    state = encode_state({"user_id": user_id})

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    return {"auth_url": auth_url}

@app.get("/auth/google/callback", name="google_callback")
def google_callback(code: str, request: Request, state: str | None = None):
    if not state:
        raise HTTPException(
            status_code=400,
            detail="Missing OAuth state. Restart via /auth/google/start?user_id=...",
        )

    try:
        data = decode_state(state)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state. Restart auth.")

    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id in OAuth state. Restart auth.")

    redirect_uri = str(request.url_for("google_callback"))
    flow = build_flow(redirect_uri=redirect_uri)

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {str(e)}")

    creds = flow.credentials

    db = SessionLocal()
    try:
        save_google_token(db, user_id=user_id, token_dict=creds_to_dict(creds))
    finally:
        db.close()

    return RedirectResponse(url=f"{FRONTEND_URL}/chat?connected=1")

# ✅ NEW: Google connection status
@app.get("/auth/google/status")
def google_status(user_id: str):
    db = SessionLocal()
    try:
        token = load_google_token(db, user_id=user_id)
        if not token:
            return {"connected": False}

        # Basic sanity: consider connected if we have either access token or refresh token
        access = token.get("token")
        refresh = token.get("refresh_token")
        return {"connected": bool(access or refresh)}
    finally:
        db.close()

# ------------------------
# Confirmation endpoint
# ------------------------

@app.post("/confirm")
def confirm_action(req: ConfirmRequest):
    db = SessionLocal()
    try:
        msg = f"CONFIRMATION: {req.confirmation}"
        if req.instruction:
            msg += f". {req.instruction}"

        state = _build_initial_state(db, req.user_id, msg)
        result = agent.invoke(state)

        # ✅ persist pending_intent changes
        _apply_pending_intent_writeback(db, result)

        return {
            "reply": result.get("response", "") or "OK",
            "pending_action": result.get("pending_action"),
            "pending_intent": result.get("pending_intent"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
