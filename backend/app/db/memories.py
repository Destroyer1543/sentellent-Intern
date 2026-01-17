# app/db/memories.py
from __future__ import annotations

from typing import Dict, Optional
from sqlalchemy.orm import Session
from app.db.models.memory import Memory


def load_memories(db: Session, user_id: str) -> Dict[str, str]:
    rows = db.query(Memory).filter(Memory.user_id == user_id).all()
    out: Dict[str, str] = {}
    for r in rows:
        out[r.key] = r.value
    return out


def get_memory(db: Session, user_id: str, key: str) -> Optional[str]:
    row = (
        db.query(Memory)
        .filter(Memory.user_id == user_id, Memory.key == key)
        .first()
    )
    return row.value if row else None


def upsert_memory(db: Session, user_id: str, key: str, value: str) -> None:
    row = (
        db.query(Memory)
        .filter(Memory.user_id == user_id, Memory.key == key)
        .first()
    )
    if row:
        row.value = value
    else:
        db.add(Memory(user_id=user_id, key=key, value=value))
    db.commit()
