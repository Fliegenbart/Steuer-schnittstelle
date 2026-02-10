"""DB session dependency."""
from backend.app.config import settings
from backend.app.models.database import get_engine, get_session_factory, init_db

engine = get_engine(settings.database_url)
SessionLocal = get_session_factory(engine)
init_db(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
