import json
from sqlalchemy.orm import Session
from app.db.models.google_token import GoogleToken  # or your correct import

def save_google_token(db: Session, user_id: str, token_dict: dict):
    row = db.query(GoogleToken).filter(GoogleToken.user_id == user_id).first()
    payload = json.dumps(token_dict)  # store as string
    if row:
        row.token_json = payload
    else:
        row = GoogleToken(user_id=user_id, token_json=payload)
        db.add(row)
    db.commit()

def load_google_token(db: Session, user_id: str) -> dict | None:
    row = db.query(GoogleToken).filter(GoogleToken.user_id == user_id).first()
    if not row:
        return None

    token = row.token_json  # this is a string in DB
    if token is None:
        return None

    # ✅ If it's already dict, return it. If string JSON, parse it.
    if isinstance(token, dict):
        return token
    if isinstance(token, str):
        try:
            return json.loads(token)
        except Exception:
            return None

    return None
