"""Belege (Documents) API – Upload, OCR, Extraction Pipeline."""
import os, shutil, uuid, asyncio, logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from backend.app.deps import get_db
from backend.app.config import settings
from backend.app.models.database import Beleg, Steuerjahr
from backend.app.models.schemas import BelegResponse, BelegUpdate
from backend.app.services import ocr_service, extraction_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/belege", tags=["Belege"])

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"}


# ── Pipeline ──────────────────────────────

def _run_pipeline(beleg_id: int, db_url: str):
    """Background: OCR → Extraction → Auto-Kontierung."""
    from backend.app.models.database import get_engine, get_session_factory, Beleg

    engine = get_engine(db_url)
    Session = get_session_factory(engine)
    db = Session()

    try:
        beleg = db.query(Beleg).get(beleg_id)
        if not beleg:
            return

        # Phase 1: OCR
        beleg.status = "ocr_laeuft"
        db.commit()
        try:
            ocr_result = ocr_service.process_file(beleg.dateipfad)
            beleg.ocr_text = ocr_result["text"]
            beleg.ocr_daten = ocr_result["data"]
            beleg.ocr_konfidenz = ocr_result["conf"]
            beleg.status = "ocr_fertig"
            db.commit()
        except Exception as e:
            logger.error(f"OCR failed for {beleg.id}: {e}")
            beleg.status = "fehler"
            beleg.pruefnotiz = f"OCR-Fehler: {e}"
            db.commit()
            return

        if not ocr_result["text"] or len(ocr_result["text"].strip()) < 20:
            beleg.status = "fehler"
            beleg.pruefnotiz = "OCR lieferte keinen verwertbaren Text"
            db.commit()
            return

        # Phase 2: Extraction (async in sync context)
        beleg.status = "extraktion_laeuft"
        db.commit()
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                extraction_service.extract_beleg(
                    ocr_result["text"],
                    ocr_result["data"],
                    ocr_conf=ocr_result["conf"],
                    image_path=beleg.dateipfad,
                )
            )
            loop.close()

            data = result.get("extrahierte_daten", {})
            beleg.extrahierte_daten = data
            beleg.quellreferenzen = result.get("quellreferenzen", [])
            beleg.extraktion_methode = result.get("methode")
            beleg.extraktion_konfidenz = result.get("konfidenz", "niedrig")

            # Map extracted fields to DB columns
            _map_fields(beleg, data)

            beleg.status = "extrahiert"
            db.commit()

        except Exception as e:
            logger.error(f"Extraction failed for {beleg.id}: {e}")
            beleg.status = "fehler"
            beleg.pruefnotiz = f"Extraktion-Fehler: {e}"
            db.commit()

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        db.close()


def _map_fields(beleg: Beleg, data: dict):
    """Map extracted dict fields to Beleg columns."""
    field_map = {
        "beleg_typ": "beleg_typ",
        "aussteller": "aussteller",
        "beschreibung": "beschreibung",
        "rechnungsnummer": "rechnungsnummer",
        "datum_beleg": "datum_beleg",
        "steuer_kategorie": "steuer_kategorie",
        "skr03_konto": "skr03_konto",
        "skr03_bezeichnung": "skr03_bezeichnung",
        "bu_schluessel": "bu_schluessel",
    }
    for src, dst in field_map.items():
        val = data.get(src)
        if val and val != "null":
            setattr(beleg, dst, str(val))

    # Numeric fields
    for field in ["betrag_brutto", "betrag_netto", "mwst_satz", "mwst_betrag", "arbeitskosten_35a", "materialkosten"]:
        val = data.get(field)
        if val and val != "null":
            try:
                num = float(str(val).replace(",", "."))
                if field == "arbeitskosten_35a":
                    beleg.paragraph_35a_anteil = num
                else:
                    setattr(beleg, field, num)
            except (ValueError, TypeError):
                pass

    # Default Gegenkonto
    if not beleg.gegenkonto:
        beleg.gegenkonto = "1200"


# ── Endpoints ─────────────────────────────

@router.get("/steuerjahr/{sj_id}", response_model=list[BelegResponse])
def list_belege(sj_id: int, status: str = None, db: Session = Depends(get_db)):
    q = db.query(Beleg).filter(Beleg.steuerjahr_id == sj_id)
    if status:
        q = q.filter(Beleg.status == status)
    return [BelegResponse.model_validate(b) for b in q.order_by(Beleg.erstellt_am.desc()).all()]


@router.post("/upload/{sj_id}", response_model=list[BelegResponse])
async def upload_belege(
    sj_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    sj = db.query(Steuerjahr).get(sj_id)
    if not sj:
        raise HTTPException(404, "Steuerjahr nicht gefunden")

    results = []
    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED:
            continue

        # Save file
        uid = uuid.uuid4().hex[:12]
        safe_name = f"{uid}_{file.filename}"
        dest = UPLOAD_DIR / str(sj.mandant_id) / str(sj.jahr)
        dest.mkdir(parents=True, exist_ok=True)
        file_path = dest / safe_name

        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Create DB record
        beleg = Beleg(
            steuerjahr_id=sj_id,
            dateiname=file.filename,
            dateipfad=str(file_path),
            dateityp=ext.lstrip("."),
            dateigroesse=os.path.getsize(file_path),
            status="hochgeladen",
        )
        db.add(beleg)
        db.commit()
        db.refresh(beleg)

        # Start background pipeline
        background_tasks.add_task(_run_pipeline, beleg.id, settings.database_url)
        results.append(BelegResponse.model_validate(beleg))

    if not results:
        raise HTTPException(400, "Keine gültigen Dateien")
    return results


@router.get("/{beleg_id}", response_model=BelegResponse)
def get_beleg(beleg_id: int, db: Session = Depends(get_db)):
    b = db.query(Beleg).get(beleg_id)
    if not b:
        raise HTTPException(404, "Beleg nicht gefunden")
    return BelegResponse.model_validate(b)


@router.put("/{beleg_id}", response_model=BelegResponse)
def update_beleg(beleg_id: int, data: BelegUpdate, db: Session = Depends(get_db)):
    b = db.query(Beleg).get(beleg_id)
    if not b:
        raise HTTPException(404, "Beleg nicht gefunden")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(b, k, v)
    if data.manuell_geprueft:
        b.status = "geprueft"
    db.commit()
    db.refresh(b)
    return BelegResponse.model_validate(b)


@router.post("/{beleg_id}/reprocess")
async def reprocess_beleg(beleg_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    b = db.query(Beleg).get(beleg_id)
    if not b:
        raise HTTPException(404, "Beleg nicht gefunden")
    b.status = "hochgeladen"
    b.extrahierte_daten = None
    b.quellreferenzen = None
    db.commit()
    background_tasks.add_task(_run_pipeline, b.id, settings.database_url)
    return {"ok": True, "status": "reprocessing"}


@router.delete("/{beleg_id}")
def delete_beleg(beleg_id: int, db: Session = Depends(get_db)):
    b = db.query(Beleg).get(beleg_id)
    if not b:
        raise HTTPException(404, "Beleg nicht gefunden")
    if os.path.exists(b.dateipfad):
        os.remove(b.dateipfad)
    db.delete(b)
    db.commit()
    return {"ok": True}
