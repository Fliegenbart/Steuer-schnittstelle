"""Maesn DATEV Integration – REST API bridge to DATEV Unternehmen Online.

Maesn abstracts DATEV's native Data Services (BDS, RDS 1.0, BBS) into a clean
REST API. This service handles:
- Uploading Belegbilder (receipt images) to DUO
- Creating Buchungsvorschläge (booking proposals) with structured data
- Syncing document status between SteuerPilot and DATEV

Docs: https://docs.maesn.com
"""
import os, logging, json
from datetime import datetime
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

MAESN_API_URL = os.getenv("MAESN_API_URL", "https://api.maesn.com/v1")
MAESN_API_KEY = os.getenv("MAESN_API_KEY", "")
MAESN_SANDBOX = os.getenv("MAESN_SANDBOX", "true").lower() == "true"


def _headers():
    return {
        "Authorization": f"Bearer {MAESN_API_KEY}",
        "Content-Type": "application/json",
        "X-Sandbox": str(MAESN_SANDBOX).lower(),
    }


def is_configured() -> bool:
    return bool(MAESN_API_KEY)


async def test_connection() -> dict:
    """Test Maesn API connection."""
    if not is_configured():
        return {"connected": False, "error": "MAESN_API_KEY nicht konfiguriert"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{MAESN_API_URL}/health", headers=_headers())
            return {"connected": resp.status_code == 200, "status": resp.status_code}
    except Exception as e:
        return {"connected": False, "error": str(e)}


async def list_companies() -> list:
    """List available DATEV Mandanten via Maesn."""
    if not is_configured():
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{MAESN_API_URL}/companies", headers=_headers())
            resp.raise_for_status()
            return resp.json().get("companies", [])
    except Exception as e:
        logger.error(f"Maesn list companies error: {e}")
        return []


async def upload_beleg_to_datev(
    beleg_dateipfad: str,
    beleg_dateiname: str,
    company_id: str,
    buchungsdaten: Optional[dict] = None,
) -> dict:
    """Upload a Beleg (image + structured data) to DATEV via Maesn.

    This uses Maesn's unified endpoint which combines:
    - Belegbilderservice (uploading the image)
    - Rechnungsdatenservice 1.0 (structured data → Buchungsvorschlag)

    The structured data becomes a Buchungsvorschlag in DUO that the
    Steuerberater can review and book with one click.
    """
    if not is_configured():
        return {"success": False, "error": "Maesn nicht konfiguriert"}

    try:
        # Build the Maesn document payload
        payload = {
            "company_id": company_id,
            "document": {
                "filename": beleg_dateiname,
                "category": _map_beleg_typ(buchungsdaten.get("beleg_typ") if buchungsdaten else None),
            }
        }

        # Add structured booking data if available (→ Buchungsvorschlag)
        if buchungsdaten:
            payload["booking_proposal"] = {
                "amount": buchungsdaten.get("betrag_brutto"),
                "amount_net": buchungsdaten.get("betrag_netto"),
                "tax_rate": buchungsdaten.get("mwst_satz"),
                "tax_amount": buchungsdaten.get("mwst_betrag"),
                "date": _format_date_iso(buchungsdaten.get("datum_beleg")),
                "description": buchungsdaten.get("beschreibung", ""),
                "vendor": buchungsdaten.get("aussteller", ""),
                "invoice_number": buchungsdaten.get("rechnungsnummer"),
                "account": buchungsdaten.get("skr03_konto"),
                "counter_account": buchungsdaten.get("gegenkonto", "1200"),
                "bu_code": buchungsdaten.get("bu_schluessel"),
                "cost_center": buchungsdaten.get("kostenstelle"),
                "tax_category": buchungsdaten.get("steuer_kategorie"),
            }

            # Add source grounding metadata (our USP!)
            if buchungsdaten.get("quellreferenzen"):
                payload["metadata"] = {
                    "source_grounding": buchungsdaten["quellreferenzen"],
                    "extraction_method": buchungsdaten.get("extraktion_methode", "steuerpilot"),
                    "extraction_confidence": buchungsdaten.get("extraktion_konfidenz", "mittel"),
                    "steuerpilot_version": "1.0.0"
                }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Upload document file
            with open(beleg_dateipfad, "rb") as f:
                files = {"file": (beleg_dateiname, f)}
                resp = await client.post(
                    f"{MAESN_API_URL}/documents",
                    headers={"Authorization": f"Bearer {MAESN_API_KEY}"},
                    data={"payload": json.dumps(payload)},
                    files=files,
                )

            if resp.status_code in (200, 201):
                result = resp.json()
                return {
                    "success": True,
                    "datev_document_id": result.get("id"),
                    "datev_booking_id": result.get("booking_proposal_id"),
                    "status": result.get("status", "uploaded"),
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                    "status_code": resp.status_code,
                }

    except FileNotFoundError:
        return {"success": False, "error": f"Datei nicht gefunden: {beleg_dateipfad}"}
    except Exception as e:
        logger.error(f"Maesn upload error: {e}")
        return {"success": False, "error": str(e)}


async def sync_batch_to_datev(belege: list, company_id: str) -> dict:
    """Sync multiple Belege to DATEV in batch."""
    results = {"total": len(belege), "success": 0, "errors": 0, "details": []}

    for beleg in belege:
        buchungsdaten = {
            "beleg_typ": beleg.beleg_typ,
            "betrag_brutto": beleg.betrag_brutto,
            "betrag_netto": beleg.betrag_netto,
            "mwst_satz": beleg.mwst_satz,
            "mwst_betrag": beleg.mwst_betrag,
            "datum_beleg": beleg.datum_beleg,
            "aussteller": beleg.aussteller,
            "beschreibung": beleg.beschreibung,
            "rechnungsnummer": beleg.rechnungsnummer,
            "skr03_konto": beleg.skr03_konto,
            "gegenkonto": beleg.gegenkonto or "1200",
            "bu_schluessel": beleg.bu_schluessel,
            "kostenstelle": beleg.kostenstelle,
            "steuer_kategorie": beleg.steuer_kategorie,
            "quellreferenzen": beleg.quellreferenzen,
            "extraktion_methode": beleg.extraktion_methode,
            "extraktion_konfidenz": beleg.extraktion_konfidenz,
        }

        result = await upload_beleg_to_datev(
            beleg_dateipfad=beleg.dateipfad,
            beleg_dateiname=beleg.dateiname,
            company_id=company_id,
            buchungsdaten=buchungsdaten,
        )

        if result.get("success"):
            results["success"] += 1
        else:
            results["errors"] += 1

        results["details"].append({
            "beleg_id": beleg.id,
            "dateiname": beleg.dateiname,
            **result,
        })

    return results


def _map_beleg_typ(typ: str) -> str:
    """Map SteuerPilot Belegtyp to Maesn/DATEV category."""
    mapping = {
        "rechnung": "incoming_invoice",
        "handwerkerrechnung": "incoming_invoice",
        "lohnsteuerbescheinigung": "payroll",
        "spendenbescheinigung": "donation_receipt",
        "versicherungsnachweis": "insurance",
        "kontoauszug": "bank_statement",
        "nebenkostenabrechnung": "utility_bill",
        "arztrechnung": "incoming_invoice",
        "fahrtkosten": "travel_expense",
        "bewirtungsbeleg": "entertainment",
    }
    return mapping.get(typ, "other")


def _format_date_iso(datum: str) -> Optional[str]:
    """Convert TT.MM.JJJJ to YYYY-MM-DD."""
    if not datum:
        return None
    parts = datum.replace("-", ".").split(".")
    if len(parts) == 3:
        try:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        except (ValueError, IndexError):
            pass
    return datum


# ════════════════════════════════════════════
#  DATEV CSV Export (fallback for non-Maesn users)
# ════════════════════════════════════════════

def generate_datev_csv(belege: list, mandant_name: str, jahr: int) -> str:
    """Generate DATEV Buchungsstapel CSV (ASCII format) as fallback."""
    import csv, io

    HEADER = [
        "Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz",
        "Kurs", "Basis-Umsatz", "WKZ Basis-Umsatz", "Konto",
        "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel", "Belegdatum",
        "Belegfeld 1", "Belegfeld 2", "Skonto", "Buchungstext",
    ]

    out = io.StringIO()
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    out.write(f'"EXTF";700;21;"Buchungsstapel";12;{now};;"SteuerPilot";"";"";"";{jahr}0101;4;{jahr}1231;"{mandant_name}";"";1;;"";""\n')

    w = csv.writer(out, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(HEADER)

    for b in belege:
        if not b.betrag_brutto:
            continue
        betrag = f"{abs(b.betrag_brutto):.2f}".replace(".", ",")
        sh = "S" if b.betrag_brutto > 0 else "H"
        datum = ""
        if b.datum_beleg:
            parts = b.datum_beleg.replace("-", ".").split(".")
            if len(parts) >= 2:
                datum = f"{parts[0].zfill(2)}{parts[1].zfill(2)}"
        text = (b.beschreibung or b.aussteller or b.dateiname)[:60]
        w.writerow([
            betrag, sh, "EUR", "", "", "",
            b.skr03_konto or "4900", b.gegenkonto or "1200",
            b.bu_schluessel or "", datum,
            b.dateiname[:36], str(b.id), "", text,
        ])

    return out.getvalue()
