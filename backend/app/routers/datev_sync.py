"""DATEV Sync API – Maesn integration + CSV export fallback."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from backend.app.deps import get_db
from backend.app.models.database import Beleg, Steuerjahr, Mandant, DATEVSyncLog
from backend.app.models.schemas import DATEVSyncRequest
from backend.app.datev import maesn_client

router = APIRouter(prefix="/api/datev", tags=["DATEV"])


@router.get("/status")
async def datev_status():
    """Check Maesn/DATEV connection status."""
    conn = await maesn_client.test_connection()
    return {
        "maesn_configured": maesn_client.is_configured(),
        "connection": conn,
        "sandbox": maesn_client.MAESN_SANDBOX,
    }


@router.get("/companies")
async def datev_companies():
    """List DATEV Mandanten available via Maesn."""
    if not maesn_client.is_configured():
        return {"companies": [], "hint": "Maesn API Key in .env konfigurieren"}
    companies = await maesn_client.list_companies()
    return {"companies": companies}


@router.post("/sync")
async def sync_to_datev(req: DATEVSyncRequest, db: Session = Depends(get_db)):
    """Sync Belege to DATEV via Maesn."""
    sj = db.query(Steuerjahr).get(req.steuerjahr_id)
    if not sj:
        raise HTTPException(404, "Steuerjahr nicht gefunden")

    mandant = db.query(Mandant).get(sj.mandant_id)
    if not mandant or not mandant.maesn_company_id:
        raise HTTPException(400, "Mandant hat keine Maesn Company ID. Bitte zuerst DATEV-Verknüpfung einrichten.")

    # Get belege to sync
    q = db.query(Beleg).filter(
        Beleg.steuerjahr_id == req.steuerjahr_id,
        Beleg.status.in_(["extrahiert", "geprueft"]),
        Beleg.datev_sync_status.is_(None) | (Beleg.datev_sync_status != "synced"),
    )
    if req.nur_gepruefte:
        q = q.filter(Beleg.manuell_geprueft == True)

    belege = q.all()
    if not belege:
        return {"message": "Keine Belege zum Sync vorhanden", "total": 0}

    # Sync via Maesn
    result = await maesn_client.sync_batch_to_datev(belege, mandant.maesn_company_id)

    # Update Beleg status and log
    for detail in result.get("details", []):
        beleg = db.query(Beleg).get(detail["beleg_id"])
        if not beleg:
            continue
        if detail.get("success"):
            beleg.datev_sync_status = "synced"
            beleg.datev_sync_at = datetime.utcnow()
            beleg.datev_sync_id = detail.get("datev_document_id")
            beleg.datev_buchungsvorschlag_id = detail.get("datev_booking_id")
            beleg.status = "an_datev"
        else:
            beleg.datev_sync_status = "error"
            beleg.pruefnotiz = (beleg.pruefnotiz or "") + f"\nDATEV-Fehler: {detail.get('error', 'unbekannt')}"

        # Audit log
        log = DATEVSyncLog(
            beleg_id=beleg.id,
            mandant_id=mandant.id,
            aktion="sync_beleg",
            status="success" if detail.get("success") else "error",
            response_data=detail,
            fehler_nachricht=detail.get("error"),
        )
        db.add(log)

    db.commit()
    return result


@router.get("/export/csv/{sj_id}")
def export_csv(sj_id: int, nur_gepruefte: bool = False, db: Session = Depends(get_db)):
    """DATEV Buchungsstapel CSV export (fallback for non-Maesn users)."""
    sj = db.query(Steuerjahr).get(sj_id)
    if not sj:
        raise HTTPException(404, "Steuerjahr nicht gefunden")

    mandant = db.query(Mandant).get(sj.mandant_id)
    q = db.query(Beleg).filter(
        Beleg.steuerjahr_id == sj_id,
        Beleg.status.in_(["extrahiert", "geprueft", "an_datev"]),
    )
    if nur_gepruefte:
        q = q.filter(Beleg.manuell_geprueft == True)

    belege = q.all()
    if not belege:
        raise HTTPException(404, "Keine Belege vorhanden")

    csv = maesn_client.generate_datev_csv(belege, mandant.name, sj.jahr)
    filename = f"EXTF_Buchungsstapel_{mandant.name}_{sj.jahr}.csv"
    return PlainTextResponse(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/log/{mandant_id}")
def sync_log(mandant_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Audit log for DATEV sync operations."""
    logs = db.query(DATEVSyncLog).filter(
        DATEVSyncLog.mandant_id == mandant_id
    ).order_by(DATEVSyncLog.erstellt_am.desc()).limit(limit).all()
    return [{"id": l.id, "beleg_id": l.beleg_id, "aktion": l.aktion,
             "status": l.status, "fehler": l.fehler_nachricht,
             "zeitpunkt": l.erstellt_am.isoformat()} for l in logs]
