"""DB session dependency."""
from backend.app.config import settings
from backend.app.models.database import get_engine, get_session_factory, init_db
from sqlalchemy import text, inspect

engine = get_engine(settings.database_url)
SessionLocal = get_session_factory(engine)
init_db(engine)

# Lightweight column migration for existing DBs
_inspector = inspect(engine)
_existing_cols = {c["name"] for c in _inspector.get_columns("belege")}
with engine.begin() as conn:
    if "materialkosten" not in _existing_cols:
        conn.execute(text("ALTER TABLE belege ADD COLUMN materialkosten FLOAT"))
    if "ocr_daten" not in _existing_cols:
        conn.execute(text("ALTER TABLE belege ADD COLUMN ocr_daten JSON"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
