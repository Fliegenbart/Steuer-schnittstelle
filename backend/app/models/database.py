"""SteuerPilot Database Models."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean,
    ForeignKey, JSON, create_engine, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Mandant(Base):
    __tablename__ = "mandanten"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, index=True)
    firma = Column(String(300))
    steuernummer = Column(String(30))
    steuer_id = Column(String(20))
    email = Column(String(200))
    telefon = Column(String(50))
    adresse = Column(Text)
    notizen = Column(Text)
    aktiv = Column(Boolean, default=True)
    # Maesn/DATEV IDs
    maesn_company_id = Column(String(100))
    datev_berater_nr = Column(String(20))
    datev_mandant_nr = Column(String(20))
    erstellt_am = Column(DateTime, default=datetime.utcnow)
    aktualisiert_am = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steuerjahre = relationship("Steuerjahr", back_populates="mandant", cascade="all, delete-orphan")


class Steuerjahr(Base):
    __tablename__ = "steuerjahre"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mandant_id = Column(Integer, ForeignKey("mandanten.id"), nullable=False)
    jahr = Column(Integer, nullable=False)
    status = Column(String(50), default="offen")
    notizen = Column(Text)
    erstellt_am = Column(DateTime, default=datetime.utcnow)

    mandant = relationship("Mandant", back_populates="steuerjahre")
    belege = relationship("Beleg", back_populates="steuerjahr", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_sj_mandant_jahr", "mandant_id", "jahr", unique=True),)


class Beleg(Base):
    __tablename__ = "belege"

    id = Column(Integer, primary_key=True, autoincrement=True)
    steuerjahr_id = Column(Integer, ForeignKey("steuerjahre.id"), nullable=False)

    # Datei
    dateiname = Column(String(500), nullable=False)
    dateipfad = Column(String(1000), nullable=False)
    dateityp = Column(String(50))
    dateigroesse = Column(Integer)

    # OCR
    ocr_text = Column(Text)
    ocr_konfidenz = Column(Float)

    # Status-Pipeline
    status = Column(String(50), default="hochgeladen", index=True)
    # hochgeladen → ocr_laeuft → ocr_fertig → extraktion_laeuft → extrahiert → geprueft → an_datev → fehler

    # Extraktion (LangExtract)
    beleg_typ = Column(String(50))
    extrahierte_daten = Column(JSON)
    quellreferenzen = Column(JSON)  # Source grounding spans
    extraktion_methode = Column(String(50))  # langextract | ollama_direkt
    extraktion_konfidenz = Column(String(20))  # hoch | mittel | niedrig

    # Steuerliche Daten
    betrag_brutto = Column(Float)
    betrag_netto = Column(Float)
    mwst_satz = Column(Float)
    mwst_betrag = Column(Float)
    datum_beleg = Column(String(20))
    aussteller = Column(String(300))
    beschreibung = Column(Text)
    rechnungsnummer = Column(String(100))

    # Kontierung (SKR03/04)
    skr03_konto = Column(String(10))
    skr03_bezeichnung = Column(String(200))
    gegenkonto = Column(String(10), default="1200")
    kostenstelle = Column(String(50))
    bu_schluessel = Column(String(5))

    # Steuer-Kategorie (EStE / betrieblich)
    steuer_kategorie = Column(String(100))
    paragraph_35a_anteil = Column(Float)  # Arbeitskosten §35a

    # DATEV Sync
    datev_sync_status = Column(String(50))  # pending | synced | error
    datev_sync_at = Column(DateTime)
    datev_sync_id = Column(String(100))
    datev_buchungsvorschlag_id = Column(String(100))

    # Prüfung
    manuell_geprueft = Column(Boolean, default=False)
    pruefnotiz = Column(Text)

    erstellt_am = Column(DateTime, default=datetime.utcnow)
    aktualisiert_am = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steuerjahr = relationship("Steuerjahr", back_populates="belege")


class DATEVSyncLog(Base):
    """Log every DATEV sync attempt for auditability."""
    __tablename__ = "datev_sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    beleg_id = Column(Integer, ForeignKey("belege.id"))
    mandant_id = Column(Integer)
    aktion = Column(String(50))  # upload_beleg | create_buchungsvorschlag | sync_status
    status = Column(String(50))  # success | error
    request_data = Column(JSON)
    response_data = Column(JSON)
    fehler_nachricht = Column(Text)
    erstellt_am = Column(DateTime, default=datetime.utcnow)


# SKR03 Kontenrahmen (häufigste Konten)
SKR03 = {
    "1000": "Kasse", "1200": "Bank", "1400": "Ford. a. Lief. u. Leist.",
    "1600": "Verb. a. Lief. u. Leist.", "1776": "Umsatzsteuer 19%", "1571": "Vorsteuer 7%", "1576": "Vorsteuer 19%",
    "3300": "Wareneingang 7%", "3400": "Wareneingang 19%",
    "4100": "Löhne", "4120": "Gehälter", "4130": "Gesetzl. Sozialaufwendungen",
    "4200": "Raumkosten", "4210": "Miete", "4220": "Pacht",
    "4240": "Gas/Strom/Wasser", "4260": "Instandhaltung Räume",
    "4300": "Versicherungen", "4360": "Beiträge",
    "4500": "Fahrzeugkosten", "4510": "Kfz-Steuer/Versicherung",
    "4520": "Kfz-Reparaturen", "4530": "Laufende Kfz-Betriebskosten",
    "4580": "Leasingkosten Kfz",
    "4600": "Werbekosten", "4630": "Geschenke", "4650": "Bewirtungskosten",
    "4700": "Kosten Warenabgabe",
    "4800": "Reparaturen/Instandhaltung", "4806": "Wartungskosten",
    "4900": "Sonstige betriebl. Aufwendungen",
    "4910": "Porto", "4920": "Telefon", "4930": "Bürobedarf",
    "4940": "Zeitschriften/Bücher", "4946": "Fremdleistungen",
    "4950": "Rechts-/Beratungskosten", "4955": "Buchführungskosten",
    "4960": "Mieten für Einrichtungen", "4969": "Fortbildungskosten",
    "4970": "Nebenkosten Geldverkehr",
    "6300": "Sonstige betriebl. Aufwendungen", "6815": "Zinsaufwendungen",
    "8100": "Erlöse Inland 7%", "8400": "Erlöse Inland 19%",
}

# Steuerliche Kategorien für EStE
STEUER_KATEGORIEN = [
    "Einkünfte nichtselbständige Arbeit",
    "Einkünfte selbständige Arbeit",
    "Einkünfte Gewerbebetrieb",
    "Einkünfte Vermietung/Verpachtung",
    "Einkünfte Kapitalvermögen",
    "Werbungskosten",
    "Sonderausgaben",
    "Außergewöhnliche Belastungen",
    "Haushaltsnahe Dienstleistungen §35a",
    "Handwerkerleistungen §35a",
    "Vorsorgeaufwendungen",
    "Spenden und Mitgliedsbeiträge",
    "Kinderbetreuungskosten",
]


def get_engine(database_url: str):
    return create_engine(database_url, echo=False)

def get_session_factory(engine):
    return sessionmaker(bind=engine)

def init_db(engine):
    Base.metadata.create_all(engine)
