from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.db.session import Base

class GoogleToken(Base):
    __tablename__ = "google_tokens"

    user_id = Column(String, primary_key=True, index=True)
    token_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
