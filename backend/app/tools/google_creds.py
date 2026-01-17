from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

import json
from google.oauth2.credentials import Credentials

def creds_from_token_dict(token_dict, scopes):
    if isinstance(token_dict, str):
        token_dict = json.loads(token_dict)

    return Credentials(
        token=token_dict.get("token"),
        refresh_token=token_dict.get("refresh_token"),
        token_uri=token_dict.get("token_uri"),
        client_id=token_dict.get("client_id"),
        client_secret=token_dict.get("client_secret"),
        scopes=scopes,
    )

def creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
