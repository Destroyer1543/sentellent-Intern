from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import Memory

def save_memory(user_id: str, key: str, value: str, source="chat"):
    db: Session = SessionLocal()
    mem = Memory(
        user_id=user_id,
        key=key,
        value=value,
        source=source
    )
    db.add(mem)
    db.commit()
