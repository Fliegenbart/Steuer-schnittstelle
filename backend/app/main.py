"""BelegSync – KI-gestützte Belegverarbeitung für Steuerberater.

Middleware-Lösung: Dokumente → OCR → Source Grounding → DATEV Unternehmen Online
"""
import os, logging
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from backend.app.deps import get_db, engine
from backend.app.config import settings
from backend.app.models.database import Mandant, Beleg
from backend.app.models.schemas import DashboardStats
from backend.app.routers import mandanten, steuerjahre, belege, datev_sync
from backend.app.routers.demo import router as demo_router, seed_demo_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="BelegSync",
    description="KI-gestützte Belegverarbeitung mit Source Grounding für DATEV",
    version="1.0.0",
)

# Routers
app.include_router(mandanten.router)
app.include_router(steuerjahre.router)
app.include_router(belege.router)
app.include_router(datev_sync.router)
app.include_router(demo_router)


@app.on_event("startup")
def auto_seed_demo():
    """Wenn DB leer → automatisch Demo-Daten laden."""
    from backend.app.models.database import get_session_factory
    SessionLocal = get_session_factory(engine)
    db = SessionLocal()
    try:
        count = db.query(func.count(Mandant.id)).scalar()
        if count == 0:
            logger.info("Leere DB erkannt – lade Demo-Daten...")
            seed_demo_data(db)
            logger.info("Demo-Daten erfolgreich geladen.")
        else:
            logger.info(f"DB enthält {count} Mandant(en) – überspringe Demo-Seed.")
    except Exception as e:
        logger.error(f"Auto-Seed fehlgeschlagen: {e}")
    finally:
        db.close()

# Upload files (accessible for PDF/image viewer)
UPLOAD_PATH = Path(settings.upload_dir).resolve()
UPLOAD_PATH.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_PATH)), name="uploads")

# Static files
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "belegsync", "version": "1.0.0"}


@app.get("/api/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)):
    mandanten_aktiv = db.query(func.count(Mandant.id)).filter(Mandant.aktiv == True).scalar()
    belege_gesamt = db.query(func.count(Beleg.id)).scalar()

    status_counts = dict(
        db.query(Beleg.status, func.count(Beleg.id)).group_by(Beleg.status).all()
    )

    belege_offen = sum(v for k, v in status_counts.items()
                       if k in ("hochgeladen", "ocr_laeuft", "ocr_fertig", "extraktion_laeuft"))
    belege_geprueft = status_counts.get("geprueft", 0)
    belege_synced = status_counts.get("an_datev", 0)
    belege_fehler = status_counts.get("fehler", 0)
    belege_extrahiert = status_counts.get("extrahiert", 0) + belege_geprueft + belege_synced

    summe = db.query(func.coalesce(func.sum(Beleg.betrag_brutto), 0)).scalar()

    return DashboardStats(
        mandanten_aktiv=mandanten_aktiv,
        belege_gesamt=belege_gesamt,
        belege_offen=belege_offen,
        belege_geprueft=belege_geprueft,
        belege_synced=belege_synced,
        belege_fehler=belege_fehler,
        summe_brutto=round(float(summe), 2),
        extraktion_rate=round(belege_extrahiert / max(belege_gesamt, 1) * 100, 1),
        datev_sync_rate=round(belege_synced / max(belege_gesamt, 1) * 100, 1),
    )


@app.get("/")
def root():
    return FileResponse(str(FRONTEND / "index.html"))
