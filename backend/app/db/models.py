from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid

Base = declarative_base()

class Memory(Base):
    __tablename__ = "memories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    key = Column(String, index=True)
    value = Column(Text)
    source = Column(String)  # chat | email | calendar
    updated_at = Column(DateTime, default=datetime.utcnow)
