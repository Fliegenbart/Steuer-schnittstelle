"""Demo-Daten für BelegSync – realistische Belege für DATEV-Pitch."""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.deps import get_db
from backend.app.models.database import Mandant, Steuerjahr, Beleg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/demo", tags=["demo"])


def _make_spans(ocr_text: str, quotes: dict) -> list:
    """Berechnet start/end Source-Grounding-Spans aus OCR-Text + Zitat-Dict.
    quotes = {"feld_name": "exakter text aus OCR"}
    """
    spans = []
    for feld, quote in quotes.items():
        if not quote:
            continue
        idx = ocr_text.find(quote)
        if idx == -1:
            # Case-insensitive fallback
            idx = ocr_text.lower().find(quote.lower())
        if idx >= 0:
            spans.append({
                "start": idx,
                "end": idx + len(quote),
                "text": quote,
                "feld": feld,
            })
    return spans


# ── Die 6 Demo-Belege ──────────────────────────────────────────────

def _beleg_handwerker(sj_id: int) -> Beleg:
    """Handwerkerrechnung Malermeister Schmidt – §35a mit Arbeitskosten/Materialkosten Split."""
    ocr = """Malermeister Schmidt GmbH
Handwerksbetrieb für Maler- und Lackierarbeiten
Musterstraße 12, 20457 Hamburg
Tel: 040 / 123 456 78 | USt-IdNr: DE123456789

RECHNUNG

Rechnungsnummer: R-2024-0847
Rechnungsdatum: 15.03.2024

An:
Herr Max Mustermann
Elbchaussee 42
22605 Hamburg

Betreff: Malerarbeiten Wohnung EG – Renovierung

Pos.  Beschreibung                        Menge    Einzelpreis    Gesamt
─────────────────────────────────────────────────────────────────────────
1     Wandfarbe Premium Weiß 10L          4 Eimer     45,00 €    180,00 €
2     Abdeckmaterial / Kreppband          1 Pauschal   35,00 €     35,00 €
3     Malerarbeiten Wohnzimmer            18 qm        28,00 €    504,00 €
4     Malerarbeiten Schlafzimmer          14 qm        28,00 €    392,00 €
5     Malerarbeiten Flur                  8 qm         28,00 €    224,00 €
6     Lackierung Türrahmen                3 Stk        65,00 €    195,00 €
7     Spachtelmasse / Grundierung         1 Pauschal   48,00 €     48,00 €

                                          Nettobetrag:          1.578,00 €
                                          Materialkosten netto:   263,00 €
                                          Arbeitskosten netto:  1.315,00 €
                                          zzgl. 19% MwSt:         299,82 €
                                          Bruttobetrag:         1.877,82 €

Hinweis gem. §35a EStG: Die Arbeitskosten (Lohnanteil) betragen 1.315,00 € netto
(1.564,85 € brutto). Diese können als Handwerkerleistungen steuerlich geltend
gemacht werden.

Zahlbar innerhalb von 14 Tagen auf: IBAN DE89 3704 0044 0532 0130 00
Vielen Dank für Ihren Auftrag!"""

    quotes = {
        "aussteller": "Malermeister Schmidt GmbH",
        "rechnungsnummer": "R-2024-0847",
        "datum_beleg": "15.03.2024",
        "betrag_brutto": "1.877,82 €",
        "betrag_netto": "1.578,00 €",
        "mwst_betrag": "299,82 €",
        "arbeitskosten_35a": "1.315,00 €",
        "materialkosten": "263,00 €",
    }

    return Beleg(
        steuerjahr_id=sj_id,
        dateiname="Rechnung_Malermeister_Schmidt_2024-03.pdf",
        dateipfad="demo/Rechnung_Malermeister_Schmidt_2024-03.pdf",
        dateityp="application/pdf",
        dateigroesse=284_000,
        ocr_text=ocr,
        ocr_konfidenz=94.2,
        status="extrahiert",
        beleg_typ="handwerkerrechnung",
        extrahierte_daten={
            "aussteller": "Malermeister Schmidt GmbH",
            "rechnungsnummer": "R-2024-0847",
            "datum_beleg": "15.03.2024",
            "betrag_brutto": 1877.82,
            "betrag_netto": 1578.00,
            "mwst_satz": 19.0,
            "mwst_betrag": 299.82,
            "arbeitskosten_35a": 1315.00,
            "materialkosten": 263.00,
            "skr03_konto": "4800",
            "beschreibung": "Malerarbeiten Wohnung EG – Renovierung",
        },
        quellreferenzen=_make_spans(ocr, quotes),
        extraktion_methode="ollama_source_grounding",
        extraktion_konfidenz="hoch",
        betrag_brutto=1877.82,
        betrag_netto=1578.00,
        mwst_satz=19.0,
        mwst_betrag=299.82,
        datum_beleg="15.03.2024",
        aussteller="Malermeister Schmidt GmbH",
        beschreibung="Malerarbeiten Wohnung EG – Renovierung",
        rechnungsnummer="R-2024-0847",
        skr03_konto="4800",
        skr03_bezeichnung="Reparaturen/Instandhaltung",
        gegenkonto="1200",
        bu_schluessel="9",
        steuer_kategorie="Handwerkerleistungen §35a",
        paragraph_35a_anteil=1315.00,
        materialkosten=263.00,
        manuell_geprueft=False,
    )


def _beleg_nebenkosten(sj_id: int) -> Beleg:
    """Nebenkostenabrechnung Hausverwaltung Meyer – §35a Split."""
    ocr = """Hausverwaltung Meyer & Co. KG
Große Bergstraße 210, 22767 Hamburg
Tel: 040 / 987 654 32

NEBENKOSTENABRECHNUNG 2023

Mietobjekt: Elbchaussee 42, 22605 Hamburg
Mieter: Herr Max Mustermann
Abrechnungszeitraum: 01.01.2023 – 31.12.2023

Abrechnung der umlagefähigen Nebenkosten:

Position                          Gesamt      Ihr Anteil (28,5%)
─────────────────────────────────────────────────────────────────
Grundsteuer                       4.280,00 €     1.219,80 €
Wasserversorgung                  3.150,00 €       897,75 €
Entwässerung                      1.840,00 €       524,40 €
Müllabfuhr                        2.960,00 €       843,60 €
Straßenreinigung                    780,00 €       222,30 €
Gebäudeversicherung               3.200,00 €       912,00 €
Allgemeinstrom                    1.420,00 €       404,70 €
Hausmeister                       8.400,00 €     2.394,00 €
Treppenhausreinigung              3.600,00 €     1.026,00 €
Gartenpflege                      2.400,00 €       684,00 €
Schornsteinfeger                    480,00 €       136,80 €
Wartung Heizungsanlage            1.200,00 €       342,00 €

Summe Nebenkosten:                                9.607,35 €
Vorauszahlungen 2023:                            -9.000,00 €
─────────────────────────────────────────────────────────────────
Nachzahlung:                                        607,35 €

Hinweis gem. §35a EStG – Haushaltsnahe Dienstleistungen:
Hausmeister (Ihr Anteil):         2.394,00 €
Treppenhausreinigung:             1.026,00 €
Gartenpflege:                       684,00 €
Anteilige Arbeitskosten gesamt:   4.104,00 €

Bitte überweisen Sie die Nachzahlung bis zum 30.04.2024.
IBAN: DE43 2005 0550 1234 5678 90"""

    quotes = {
        "aussteller": "Hausverwaltung Meyer & Co. KG",
        "datum_beleg": "01.01.2023 – 31.12.2023",
        "betrag_brutto": "9.607,35 €",
        "arbeitskosten_35a": "4.104,00 €",
    }

    return Beleg(
        steuerjahr_id=sj_id,
        dateiname="Nebenkostenabrechnung_2023.pdf",
        dateipfad="demo/Nebenkostenabrechnung_2023.pdf",
        dateityp="application/pdf",
        dateigroesse=512_000,
        ocr_text=ocr,
        ocr_konfidenz=91.8,
        status="geprueft",
        beleg_typ="nebenkostenabrechnung",
        extrahierte_daten={
            "aussteller": "Hausverwaltung Meyer & Co. KG",
            "datum_beleg": "01.01.2023 – 31.12.2023",
            "betrag_brutto": 9607.35,
            "arbeitskosten_35a": 4104.00,
            "materialkosten": 0,
            "skr03_konto": "4210",
            "beschreibung": "Nebenkostenabrechnung 2023 – Elbchaussee 42",
        },
        quellreferenzen=_make_spans(ocr, quotes),
        extraktion_methode="ollama_source_grounding",
        extraktion_konfidenz="hoch",
        betrag_brutto=9607.35,
        betrag_netto=9607.35,
        mwst_satz=0,
        mwst_betrag=0,
        datum_beleg="01.01.2023",
        aussteller="Hausverwaltung Meyer & Co. KG",
        beschreibung="Nebenkostenabrechnung 2023 – Elbchaussee 42",
        skr03_konto="4210",
        skr03_bezeichnung="Miete",
        gegenkonto="1200",
        steuer_kategorie="Haushaltsnahe Dienstleistungen §35a",
        paragraph_35a_anteil=4104.00,
        materialkosten=0,
        manuell_geprueft=True,
        pruefnotiz="§35a-Aufteilung geprüft und korrekt",
    )


def _beleg_lohnsteuer(sj_id: int) -> Beleg:
    """Lohnsteuerbescheinigung TechCorp GmbH."""
    ocr = """Elektronische Lohnsteuerbescheinigung 2024

Arbeitgeber:
TechCorp GmbH
Speicherstadt 7, 20457 Hamburg
Steuernummer AG: 27/456/12345

Arbeitnehmer:
Max Mustermann
Steuer-IdNr.: 12 345 678 901

Zeile  Bezeichnung                                          Betrag
──────────────────────────────────────────────────────────────────
 3     Bruttoarbeitslohn                                 68.400,00 €
 4     Einbehaltene Lohnsteuer                            9.876,00 €
 5     Einbehaltener Solidaritätszuschlag                   543,18 €
 6     Einbehaltene Kirchensteuer ev.                       790,08 €
22     Arbeitnehmeranteil Rentenversicherung              6.358,80 €
23     Arbeitnehmeranteil Arbeitslosenversicherung          889,20 €
25     Arbeitnehmeranteil Krankenversicherung              5.609,64 €
26     Arbeitnehmeranteil Pflegeversicherung              1.162,80 €
28     AG-Zuschuss freiwillige KV                         2.804,82 €

Bescheinigung erstellt am: 01.02.2025
Dies ist eine maschinell erstellte Bescheinigung."""

    quotes = {
        "aussteller": "TechCorp GmbH",
        "betrag_brutto": "68.400,00 €",
        "datum_beleg": "01.02.2025",
    }

    return Beleg(
        steuerjahr_id=sj_id,
        dateiname="Lohnsteuerbescheinigung_2024_TechCorp.pdf",
        dateipfad="demo/Lohnsteuerbescheinigung_2024_TechCorp.pdf",
        dateityp="application/pdf",
        dateigroesse=198_000,
        ocr_text=ocr,
        ocr_konfidenz=97.5,
        status="extrahiert",
        beleg_typ="lohnsteuerbescheinigung",
        extrahierte_daten={
            "aussteller": "TechCorp GmbH",
            "betrag_brutto": 68400.00,
            "datum_beleg": "01.02.2025",
            "beschreibung": "Elektronische Lohnsteuerbescheinigung 2024",
            "skr03_konto": "4120",
        },
        quellreferenzen=_make_spans(ocr, quotes),
        extraktion_methode="ollama_source_grounding",
        extraktion_konfidenz="hoch",
        betrag_brutto=68400.00,
        datum_beleg="01.02.2025",
        aussteller="TechCorp GmbH",
        beschreibung="Elektronische Lohnsteuerbescheinigung 2024",
        skr03_konto="4120",
        skr03_bezeichnung="Gehälter",
        gegenkonto="1200",
        steuer_kategorie="Einkünfte nichtselbständige Arbeit",
        manuell_geprueft=False,
    )


def _beleg_spende(sj_id: int) -> Beleg:
    """Spendenbescheinigung Caritas Hamburg."""
    ocr = """Caritasverband für Hamburg e.V.
Danziger Str. 66, 20099 Hamburg
Steuernummer: 17/401/03456

Bestätigung über Geldzuwendungen/Mitgliedsbeiträge
im Sinne des § 10b des Einkommensteuergesetzes

Zuwendender:
Max Mustermann, Elbchaussee 42, 22605 Hamburg

Art der Zuwendung: Geldzuwendung
Betrag der Zuwendung – in Ziffern: 1.200,00 €
                     – in Buchstaben: eintausendzweihundert Euro
Tag der Zuwendung: 20.12.2024

Es handelt sich um den Verzicht auf Erstattung von Aufwendungen:  Nein

Wir sind wegen Förderung mildtätiger Zwecke nach dem Freistellungsbescheid
des Finanzamts Hamburg-Nord, StNr. 17/401/03456, vom 12.05.2023 für den
letzten Veranlagungszeitraum 2021 nach § 5 Abs. 1 Nr. 9 des
Körperschaftsteuergesetzes von der Körperschaftsteuer befreit.

Es wird bestätigt, dass die Zuwendung nur zur Förderung mildtätiger Zwecke
verwendet wird.

Hamburg, 22.12.2024

_________________________________
Caritasverband für Hamburg e.V.
(Maschinell erstellte Zuwendungsbestätigung)"""

    quotes = {
        "aussteller": "Caritasverband für Hamburg e.V.",
        "betrag_brutto": "1.200,00 €",
        "datum_beleg": "20.12.2024",
    }

    return Beleg(
        steuerjahr_id=sj_id,
        dateiname="Spendenbescheinigung_Caritas_2024.pdf",
        dateipfad="demo/Spendenbescheinigung_Caritas_2024.pdf",
        dateityp="application/pdf",
        dateigroesse=145_000,
        ocr_text=ocr,
        ocr_konfidenz=96.1,
        status="geprueft",
        beleg_typ="spendenbescheinigung",
        extrahierte_daten={
            "aussteller": "Caritasverband für Hamburg e.V.",
            "betrag_brutto": 1200.00,
            "datum_beleg": "20.12.2024",
            "beschreibung": "Geldzuwendung – Förderung mildtätiger Zwecke",
            "skr03_konto": "6815",
        },
        quellreferenzen=_make_spans(ocr, quotes),
        extraktion_methode="ollama_source_grounding",
        extraktion_konfidenz="hoch",
        betrag_brutto=1200.00,
        datum_beleg="20.12.2024",
        aussteller="Caritasverband für Hamburg e.V.",
        beschreibung="Geldzuwendung – Förderung mildtätiger Zwecke",
        skr03_konto="6815",
        skr03_bezeichnung="Zinsaufwendungen",
        gegenkonto="1200",
        steuer_kategorie="Spenden und Mitgliedsbeiträge",
        manuell_geprueft=True,
        pruefnotiz="Spendenbescheinigung formal korrekt",
    )


def _beleg_bewirtung(sj_id: int) -> Beleg:
    """Bewirtungsbeleg Restaurant Alster – Konfidenz "mittel"."""
    ocr = """Restaurant Alsterperle
Alsterufer 22, 20354 Hamburg
Tel: 040 / 555 123 00
USt-IdNr: DE987654321

Rechnung Nr. 4523
Tisch 7 | Datum: 08.11.2024 | Bedienung: Markus

2x Hamburger Pannfisch              29,80 €
1x Labskaus klassisch               18,50 €
1x Caesar Salad                     14,90 €
3x Holsten Pils 0,4L                14,70 €
1x Flasche Riesling Rheingau        38,00 €
2x Espresso                          7,20 €
1x Crème Brûlée                      9,90 €

                        Zwischensumme: 133,00 €
                        zzgl. 19% USt:  25,27 €
                        Gesamtbetrag:  158,27 €

Bezahlt: EC-Karte
Bewirtungsanlass: _______________________
Teilnehmer: _____________________________

Vielen Dank für Ihren Besuch!
Öffnungszeiten: Mo-Sa 11-23 Uhr"""

    quotes = {
        "aussteller": "Restaurant Alsterperle",
        "rechnungsnummer": "4523",
        "datum_beleg": "08.11.2024",
        "betrag_brutto": "158,27 €",
        "betrag_netto": "133,00 €",
        "mwst_betrag": "25,27 €",
    }

    return Beleg(
        steuerjahr_id=sj_id,
        dateiname="Bewirtungsbeleg_Alsterperle_2024-11.jpg",
        dateipfad="demo/Bewirtungsbeleg_Alsterperle_2024-11.jpg",
        dateityp="image/jpeg",
        dateigroesse=1_840_000,
        ocr_text=ocr,
        ocr_konfidenz=87.3,
        status="extrahiert",
        beleg_typ="bewirtungsbeleg",
        extrahierte_daten={
            "aussteller": "Restaurant Alsterperle",
            "rechnungsnummer": "4523",
            "datum_beleg": "08.11.2024",
            "betrag_brutto": 158.27,
            "betrag_netto": 133.00,
            "mwst_satz": 19.0,
            "mwst_betrag": 25.27,
            "skr03_konto": "4650",
            "beschreibung": "Geschäftsessen – Bewirtungsbeleg",
        },
        quellreferenzen=_make_spans(ocr, quotes),
        extraktion_methode="ollama_source_grounding",
        extraktion_konfidenz="mittel",
        betrag_brutto=158.27,
        betrag_netto=133.00,
        mwst_satz=19.0,
        mwst_betrag=25.27,
        datum_beleg="08.11.2024",
        aussteller="Restaurant Alsterperle",
        beschreibung="Geschäftsessen – Bewirtungsbeleg",
        rechnungsnummer="4523",
        skr03_konto="4650",
        skr03_bezeichnung="Bewirtungskosten",
        gegenkonto="1200",
        bu_schluessel="9",
        steuer_kategorie="Werbungskosten",
        manuell_geprueft=False,
    )


def _beleg_arzt(sj_id: int) -> Beleg:
    """Arztrechnung Dr. med. Weber – Status an_datev."""
    ocr = """Dr. med. Katharina Weber
Fachärztin für Innere Medizin
Rothenbaumchaussee 88, 20148 Hamburg
Tel: 040 / 444 789 00

Privatärztliche Liquidation

Patient: Max Mustermann, geb. 15.04.1982
Rechnungsnummer: PL-2024-1156
Rechnungsdatum: 22.09.2024

Leistungen nach GOÄ:

Datum       Ziffer  Bezeichnung                          Faktor  Betrag
────────────────────────────────────────────────────────────────────────
22.09.24    1       Beratung                             2,3     26,81 €
22.09.24    5       Symptombezogene Untersuchung         2,3     26,81 €
22.09.24    250     Blutentnahme                         1,8     4,02 €
22.09.24    3501    Kleines Blutbild                     1,15    4,03 €
22.09.24    3511    Glucose                              1,15    2,87 €
22.09.24    3585    Cholesterin                          1,15    2,87 €
22.09.24    3560    HbA1c                                1,15    11,49 €
22.09.24    651     EKG (12 Ableitungen)                 2,3     33,52 €
22.09.24    75      Ausführlicher Befundbericht          2,3     17,43 €

                                        Summe netto:    129,85 €
                                        MwSt-frei gem. §4 Nr. 14a UStG

Gesamtbetrag: 129,85 €

Bitte überweisen Sie den Betrag innerhalb von 30 Tagen.
IBAN: DE77 2004 0000 0987 6543 21
Verwendungszweck: PL-2024-1156"""

    quotes = {
        "aussteller": "Dr. med. Katharina Weber",
        "rechnungsnummer": "PL-2024-1156",
        "datum_beleg": "22.09.2024",
        "betrag_brutto": "129,85 €",
    }

    return Beleg(
        steuerjahr_id=sj_id,
        dateiname="Arztrechnung_Dr_Weber_2024-09.pdf",
        dateipfad="demo/Arztrechnung_Dr_Weber_2024-09.pdf",
        dateityp="application/pdf",
        dateigroesse=176_000,
        ocr_text=ocr,
        ocr_konfidenz=95.8,
        status="an_datev",
        beleg_typ="arztrechnung",
        extrahierte_daten={
            "aussteller": "Dr. med. Katharina Weber",
            "rechnungsnummer": "PL-2024-1156",
            "datum_beleg": "22.09.2024",
            "betrag_brutto": 129.85,
            "betrag_netto": 129.85,
            "mwst_satz": 0,
            "mwst_betrag": 0,
            "skr03_konto": "4900",
            "beschreibung": "Privatärztliche Liquidation – Innere Medizin",
        },
        quellreferenzen=_make_spans(ocr, quotes),
        extraktion_methode="ollama_source_grounding",
        extraktion_konfidenz="hoch",
        betrag_brutto=129.85,
        betrag_netto=129.85,
        mwst_satz=0,
        mwst_betrag=0,
        datum_beleg="22.09.2024",
        aussteller="Dr. med. Katharina Weber",
        beschreibung="Privatärztliche Liquidation – Innere Medizin",
        rechnungsnummer="PL-2024-1156",
        skr03_konto="4900",
        skr03_bezeichnung="Sonstige betriebl. Aufwendungen",
        gegenkonto="1200",
        steuer_kategorie="Außergewöhnliche Belastungen",
        manuell_geprueft=True,
        pruefnotiz="GOÄ-Positionen verifiziert",
        datev_sync_status="synced",
        datev_sync_id="DATEV-2024-00847",
    )


# ── Seed-Funktion ──────────────────────────────────────────────────

def seed_demo_data(db: Session) -> dict:
    """Erstellt Demo-Mandant mit 6 realistischen Belegen."""
    # Mandant
    mandant = Mandant(
        name="Mustermann & Partner",
        firma="Mustermann & Partner Steuerberatung",
        steuernummer="27/123/45678",
        steuer_id="12 345 678 901",
        email="info@mustermann-partner.de",
        telefon="040 / 123 456 00",
        adresse="Elbchaussee 42, 22605 Hamburg",
        aktiv=True,
        datev_berater_nr="12345",
        datev_mandant_nr="10001",
    )
    db.add(mandant)
    db.flush()

    # Steuerjahr
    steuerjahr = Steuerjahr(
        mandant_id=mandant.id,
        jahr=2024,
        status="in_bearbeitung",
    )
    db.add(steuerjahr)
    db.flush()

    # 6 Belege
    belege = [
        _beleg_handwerker(steuerjahr.id),
        _beleg_nebenkosten(steuerjahr.id),
        _beleg_lohnsteuer(steuerjahr.id),
        _beleg_spende(steuerjahr.id),
        _beleg_bewirtung(steuerjahr.id),
        _beleg_arzt(steuerjahr.id),
    ]
    db.add_all(belege)
    db.commit()

    logger.info(f"Demo-Daten erstellt: Mandant '{mandant.name}', {len(belege)} Belege")
    return {
        "mandant_id": mandant.id,
        "steuerjahr_id": steuerjahr.id,
        "belege_count": len(belege),
    }


# ── API Endpoints ──────────────────────────────────────────────────

@router.post("/seed")
def api_seed(db: Session = Depends(get_db)):
    """Demo-Daten erstellen."""
    result = seed_demo_data(db)
    return {"status": "ok", "message": "Demo-Daten erstellt", **result}


@router.delete("/reset")
def api_reset(db: Session = Depends(get_db)):
    """Alle Demo-Daten löschen (Mandant 'Mustermann & Partner')."""
    mandant = db.query(Mandant).filter(Mandant.name == "Mustermann & Partner").first()
    if mandant:
        db.delete(mandant)
        db.commit()
        return {"status": "ok", "message": "Demo-Daten gelöscht"}
    return {"status": "ok", "message": "Keine Demo-Daten gefunden"}
