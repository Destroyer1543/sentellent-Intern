from sqlalchemy import Column, String, Text, DateTime, func
from app.db.session import Base

class Memory(Base):
    __tablename__ = "memories"

    user_id = Column(String, primary_key=True, index=True)
    key = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
