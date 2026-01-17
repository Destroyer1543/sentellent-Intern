from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.db.session import Base

class PendingAction(Base):
    __tablename__ = "pending_actions"

    user_id = Column(String, primary_key=True, index=True)
    action_json = Column(Text, nullable=False)  # JSON string
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
