"""Steuerjahre (Tax Years) API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.app.deps import get_db
from backend.app.models.database import Steuerjahr, Beleg, Mandant
from backend.app.models.schemas import SteuerjahrCreate, SteuerjahrResponse
from backend.app.services.extraction_service import detect_missing

router = APIRouter(prefix="/api/steuerjahre", tags=["Steuerjahre"])


def _enrich(sj: Steuerjahr, db: Session) -> SteuerjahrResponse:
    belege = db.query(Beleg).filter(Beleg.steuerjahr_id == sj.id).all()
    r = SteuerjahrResponse.model_validate(sj)
    r.anzahl_belege = len(belege)
    r.belege_geprueft = sum(1 for b in belege if b.manuell_geprueft)
    r.belege_synced = sum(1 for b in belege if b.datev_sync_status == "synced")
    r.summe_brutto = sum(b.betrag_brutto or 0 for b in belege)
    beleg_typen = [b.beleg_typ for b in belege if b.beleg_typ]
    r.vollstaendigkeit = detect_missing(beleg_typen)
    return r


@router.get("/mandant/{mandant_id}", response_model=list[SteuerjahrResponse])
def list_steuerjahre(mandant_id: int, db: Session = Depends(get_db)):
    sjs = db.query(Steuerjahr).filter(Steuerjahr.mandant_id == mandant_id).order_by(Steuerjahr.jahr.desc()).all()
    return [_enrich(sj, db) for sj in sjs]


@router.post("", response_model=SteuerjahrResponse, status_code=201)
def create_steuerjahr(data: SteuerjahrCreate, db: Session = Depends(get_db)):
    mandant = db.query(Mandant).get(data.mandant_id)
    if not mandant:
        raise HTTPException(404, "Mandant nicht gefunden")
    existing = db.query(Steuerjahr).filter(
        Steuerjahr.mandant_id == data.mandant_id, Steuerjahr.jahr == data.jahr
    ).first()
    if existing:
        raise HTTPException(409, f"Steuerjahr {data.jahr} existiert bereits")
    sj = Steuerjahr(**data.model_dump())
    db.add(sj)
    db.commit()
    db.refresh(sj)
    return _enrich(sj, db)


@router.get("/{sj_id}", response_model=SteuerjahrResponse)
def get_steuerjahr(sj_id: int, db: Session = Depends(get_db)):
    sj = db.query(Steuerjahr).get(sj_id)
    if not sj:
        raise HTTPException(404, "Steuerjahr nicht gefunden")
    return _enrich(sj, db)


@router.delete("/{sj_id}")
def delete_steuerjahr(sj_id: int, db: Session = Depends(get_db)):
    sj = db.query(Steuerjahr).get(sj_id)
    if not sj:
        raise HTTPException(404, "Steuerjahr nicht gefunden")
    db.delete(sj)
    db.commit()
    return {"ok": True}
