"""Mandanten (Clients) API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.app.deps import get_db
from backend.app.models.database import Mandant, Steuerjahr
from backend.app.models.schemas import MandantCreate, MandantUpdate, MandantResponse

router = APIRouter(prefix="/api/mandanten", tags=["Mandanten"])


@router.get("", response_model=list[MandantResponse])
def list_mandanten(aktiv: bool = True, db: Session = Depends(get_db)):
    q = db.query(Mandant)
    if aktiv:
        q = q.filter(Mandant.aktiv == True)
    mandanten = q.order_by(Mandant.name).all()
    result = []
    for m in mandanten:
        r = MandantResponse.model_validate(m)
        r.anzahl_steuerjahre = db.query(func.count(Steuerjahr.id)).filter(Steuerjahr.mandant_id == m.id).scalar()
        result.append(r)
    return result


@router.post("", response_model=MandantResponse, status_code=201)
def create_mandant(data: MandantCreate, db: Session = Depends(get_db)):
    m = Mandant(**data.model_dump(exclude_none=True))
    db.add(m)
    db.commit()
    db.refresh(m)
    r = MandantResponse.model_validate(m)
    r.anzahl_steuerjahre = 0
    return r


@router.get("/{mandant_id}", response_model=MandantResponse)
def get_mandant(mandant_id: int, db: Session = Depends(get_db)):
    m = db.query(Mandant).get(mandant_id)
    if not m:
        raise HTTPException(404, "Mandant nicht gefunden")
    r = MandantResponse.model_validate(m)
    r.anzahl_steuerjahre = len(m.steuerjahre)
    return r


@router.put("/{mandant_id}", response_model=MandantResponse)
def update_mandant(mandant_id: int, data: MandantUpdate, db: Session = Depends(get_db)):
    m = db.query(Mandant).get(mandant_id)
    if not m:
        raise HTTPException(404, "Mandant nicht gefunden")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    r = MandantResponse.model_validate(m)
    r.anzahl_steuerjahre = len(m.steuerjahre)
    return r


@router.delete("/{mandant_id}")
def delete_mandant(mandant_id: int, db: Session = Depends(get_db)):
    m = db.query(Mandant).get(mandant_id)
    if not m:
        raise HTTPException(404, "Mandant nicht gefunden")
    db.delete(m)
    db.commit()
    return {"ok": True}
