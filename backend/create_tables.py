from app.db.session import Base, engine
from app.db.models import Memory, GoogleToken, PendingAction  # noqa: F401

Base.metadata.create_all(bind=engine)
print("Tables created/verified.")
