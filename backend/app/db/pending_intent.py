# app/db/pending_intents.py
import json
from sqlalchemy.orm import Session
from app.db.models import PendingIntent

def save_pending_intent(db: Session, user_id: str, intent: dict):
    row = db.query(PendingIntent).filter(PendingIntent.user_id == user_id).first()
    payload = json.dumps(intent)
    if row:
        row.intent_json = payload
    else:
        row = PendingIntent(user_id=user_id, intent_json=payload)
        db.add(row)
    db.commit()

def get_pending_intent(db: Session, user_id: str) -> dict | None:
    row = db.query(PendingIntent).filter(PendingIntent.user_id == user_id).first()
    if not row:
        return None
    return json.loads(row.intent_json)

def clear_pending_intent(db: Session, user_id: str):
    row = db.query(PendingIntent).filter(PendingIntent.user_id == user_id).first()
    if row:
        db.delete(row)
        db.commit()
