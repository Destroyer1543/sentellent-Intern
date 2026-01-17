import os, json, time, base64, hmac, hashlib
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

CLIENT_SECRETS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "credentials", "google_client.json"
)

# REQUIRED: set this in env (docker-compose)
STATE_SECRET = os.getenv("GOOGLE_OAUTH_STATE_SECRET", "dev-change-me")

def build_flow(redirect_uri: str):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow

def creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

def dict_to_creds(token_dict: dict) -> Credentials:
    return Credentials(**token_dict)

def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))

def encode_state(payload: dict) -> str:
    """
    state = base64url(json) + "." + base64url(hmac_sha256(json))
    """
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(STATE_SECRET.encode("utf-8"), data, hashlib.sha256).digest()
    return f"{_b64url_encode(data)}.{_b64url_encode(sig)}"

def decode_state(state: str) -> dict:
    try:
        data_b64, sig_b64 = state.split(".", 1)
        data = _b64url_decode(data_b64)
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(STATE_SECRET.encode("utf-8"), data, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"invalid state: {e}")

def new_state(user_id: str) -> str:
    # include timestamp so you can expire it if you want
    return encode_state({"user_id": user_id, "ts": int(time.time())})
