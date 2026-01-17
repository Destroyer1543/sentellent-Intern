import os
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
from app.google.oauth import build_flow, creds_to_dict, new_state, decode_state
from app.db.google_tokens import save_google_token

router = APIRouter(prefix="/auth/google", tags=["auth"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

@router.get("/start")
def google_start(user_id: str, request: Request):
    redirect_uri = str(request.url_for("google_callback"))
    flow = build_flow(redirect_uri=redirect_uri)

    state = new_state(user_id)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,   # ✅ THIS IS THE FIX
    )

    return {"auth_url": auth_url}

@router.get("/callback", name="google_callback")
def google_callback(code: str, state: str, request: Request):
    # ✅ decode user_id from state (no user_id query param needed)
    parsed = decode_state(state)
    user_id = parsed.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False, "error": "Missing user_id in state"}, status_code=400)

    redirect_uri = str(request.url_for("google_callback"))
    flow = build_flow(redirect_uri=redirect_uri)
    flow.fetch_token(code=code)

    creds = flow.credentials
    save_google_token(user_id=user_id, token_dict=creds_to_dict(creds))

    # ✅ redirect back to frontend (OAuth-only login UX)
    return RedirectResponse(url=f"{FRONTEND_URL}/chat?connected=1")
