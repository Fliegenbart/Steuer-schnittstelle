"""API Schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MandantCreate(BaseModel):
    name: str
    firma: Optional[str] = None
    steuernummer: Optional[str] = None
    steuer_id: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    adresse: Optional[str] = None
    notizen: Optional[str] = None
    datev_berater_nr: Optional[str] = None
    datev_mandant_nr: Optional[str] = None

class MandantUpdate(BaseModel):
    name: Optional[str] = None
    firma: Optional[str] = None
    steuernummer: Optional[str] = None
    steuer_id: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    adresse: Optional[str] = None
    notizen: Optional[str] = None
    aktiv: Optional[bool] = None
    datev_berater_nr: Optional[str] = None
    datev_mandant_nr: Optional[str] = None

class MandantResponse(BaseModel):
    id: int
    name: str
    firma: Optional[str] = None
    steuernummer: Optional[str] = None
    steuer_id: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    adresse: Optional[str] = None
    notizen: Optional[str] = None
    aktiv: bool
    datev_berater_nr: Optional[str] = None
    datev_mandant_nr: Optional[str] = None
    maesn_company_id: Optional[str] = None
    erstellt_am: datetime
    anzahl_steuerjahre: int = 0
    class Config:
        from_attributes = True


class SteuerjahrCreate(BaseModel):
    mandant_id: int
    jahr: int
    notizen: Optional[str] = None

class SteuerjahrResponse(BaseModel):
    id: int
    mandant_id: int
    jahr: int
    status: str
    notizen: Optional[str] = None
    erstellt_am: datetime
    anzahl_belege: int = 0
    belege_geprueft: int = 0
    belege_synced: int = 0
    summe_brutto: float = 0.0
    vollstaendigkeit: dict = {}
    class Config:
        from_attributes = True


class SourceSpan(BaseModel):
    start: int
    end: int
    text: str
    feld: Optional[str] = None

class BelegResponse(BaseModel):
    id: int
    steuerjahr_id: int
    dateiname: str
    dateityp: Optional[str] = None
    status: str
    beleg_typ: Optional[str] = None
    extraktion_methode: Optional[str] = None
    extraktion_konfidenz: Optional[str] = None
    betrag_brutto: Optional[float] = None
    betrag_netto: Optional[float] = None
    mwst_satz: Optional[float] = None
    mwst_betrag: Optional[float] = None
    datum_beleg: Optional[str] = None
    aussteller: Optional[str] = None
    beschreibung: Optional[str] = None
    rechnungsnummer: Optional[str] = None
    skr03_konto: Optional[str] = None
    skr03_bezeichnung: Optional[str] = None
    gegenkonto: Optional[str] = None
    bu_schluessel: Optional[str] = None
    kostenstelle: Optional[str] = None
    steuer_kategorie: Optional[str] = None
    paragraph_35a_anteil: Optional[float] = None
    datev_sync_status: Optional[str] = None
    datev_sync_at: Optional[datetime] = None
    manuell_geprueft: bool = False
    pruefnotiz: Optional[str] = None
    extrahierte_daten: Optional[dict] = None
    quellreferenzen: Optional[list] = None
    ocr_text: Optional[str] = None
    ocr_konfidenz: Optional[float] = None
    erstellt_am: datetime
    class Config:
        from_attributes = True

class BelegUpdate(BaseModel):
    beleg_typ: Optional[str] = None
    betrag_brutto: Optional[float] = None
    betrag_netto: Optional[float] = None
    mwst_satz: Optional[float] = None
    mwst_betrag: Optional[float] = None
    datum_beleg: Optional[str] = None
    aussteller: Optional[str] = None
    beschreibung: Optional[str] = None
    rechnungsnummer: Optional[str] = None
    skr03_konto: Optional[str] = None
    skr03_bezeichnung: Optional[str] = None
    gegenkonto: Optional[str] = None
    bu_schluessel: Optional[str] = None
    kostenstelle: Optional[str] = None
    steuer_kategorie: Optional[str] = None
    paragraph_35a_anteil: Optional[float] = None
    manuell_geprueft: Optional[bool] = None
    pruefnotiz: Optional[str] = None


class DashboardStats(BaseModel):
    mandanten_aktiv: int
    belege_gesamt: int
    belege_offen: int
    belege_geprueft: int
    belege_synced: int
    belege_fehler: int
    summe_brutto: float
    extraktion_rate: float  # % successfully extracted
    datev_sync_rate: float  # % synced to DATEV


class DATEVSyncRequest(BaseModel):
    steuerjahr_id: int
    nur_gepruefte: bool = True
