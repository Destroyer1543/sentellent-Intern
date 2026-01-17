import json
from sqlalchemy.orm import Session
from app.db.models import PendingAction

def save_pending_action(db: Session, user_id: str, action: dict):
    row = db.query(PendingAction).filter(PendingAction.user_id == user_id).first()
    payload = json.dumps(action)
    if row:
        row.action_json = payload
    else:
        row = PendingAction(user_id=user_id, action_json=payload)
        db.add(row)
    db.commit()

def get_pending_action(db: Session, user_id: str) -> dict | None:
    row = db.query(PendingAction).filter(PendingAction.user_id == user_id).first()
    if not row:
        return None
    return json.loads(row.action_json)

def clear_pending_action(db: Session, user_id: str):
    row = db.query(PendingAction).filter(PendingAction.user_id == user_id).first()
    if row:
        db.delete(row)
        db.commit()
