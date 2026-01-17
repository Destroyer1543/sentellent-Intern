# app/db/models/pending_intent.py
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.db.session import Base

class PendingIntent(Base):
    __tablename__ = "pending_intents"

    user_id = Column(String, primary_key=True, index=True)
    intent_json = Column(Text, nullable=False)  # JSON string
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
