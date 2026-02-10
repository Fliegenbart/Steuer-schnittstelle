"""Extraction Service – LangExtract + Ollama with Source Grounding.

This is SteuerPilot's core differentiator:
- Every extracted value maps back to its exact position in the OCR text
- Explainable AI: the Steuerberater can verify each value at a glance
- This is what DATEV doesn't have and what they need (per their own Explainable AI article)
"""
import os, json, re, logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")


# ════════════════════════════════════════════
#  LangExtract Path (preferred – source grounding)
# ════════════════════════════════════════════

def _langextract_examples():
    try:
        import langextract as lx
    except ImportError:
        return None

    return [
        lx.ExampleData(
            text="Rechnung Nr. 2024-0815\nMalermeister Schmidt GmbH\nHauptstr. 12, 20095 Hamburg\nAnstricharbeiten Wohnzimmer\nArbeitskosten: 1.200,00 €\nMaterial: 340,00 €\nGesamt netto: 1.540,00 €\nMwSt 19%: 292,60 €\nBrutto: 1.832,60 €\nDatum: 15.03.2024",
            extractions=[lx.Extraction(
                entity="Handwerkerrechnung",
                attributes={
                    "beleg_typ": "handwerkerrechnung",
                    "aussteller": "Malermeister Schmidt GmbH",
                    "beschreibung": "Anstricharbeiten Wohnzimmer",
                    "betrag_brutto": "1832.60", "betrag_netto": "1540.00",
                    "mwst_satz": "19", "mwst_betrag": "292.60",
                    "datum_beleg": "15.03.2024",
                    "arbeitskosten_35a": "1200.00",
                    "materialkosten": "340.00",
                    "steuer_kategorie": "Handwerkerleistungen §35a",
                    "skr03_konto": "4946", "rechnungsnummer": "2024-0815"
                }
            )]
        ),
        lx.ExampleData(
            text="Lohnsteuerbescheinigung 2024\nArbeitgeber: TechCorp GmbH, München\nArbeitnehmer: Max Mustermann\nSteuer-ID: 12 345 678 901\n3. Bruttoarbeitslohn: 65.000,00 €\n4. Lohnsteuer: 12.450,00 €\n5. Solidaritätszuschlag: 685,00 €\n6. Kirchensteuer: 1.120,00 €\n23a. AN-Anteil Rentenversicherung: 6.045,00 €\n25. AN-Anteil Krankenversicherung: 5.005,00 €\n26. AN-Anteil Pflegeversicherung: 1.105,00 €",
            extractions=[lx.Extraction(
                entity="Lohnsteuerbescheinigung",
                attributes={
                    "beleg_typ": "lohnsteuerbescheinigung",
                    "aussteller": "TechCorp GmbH",
                    "beschreibung": "Lohnsteuerbescheinigung 2024 - Max Mustermann",
                    "betrag_brutto": "65000.00",
                    "datum_beleg": "2024",
                    "steuer_kategorie": "Einkünfte nichtselbständige Arbeit",
                    "lohnsteuer": "12450.00", "soli": "685.00", "kirchensteuer": "1120.00",
                    "rv_beitrag": "6045.00", "kv_beitrag": "5005.00", "pv_beitrag": "1105.00",
                    "steuer_id": "12 345 678 901"
                }
            )]
        ),
        lx.ExampleData(
            text="Spendenquittung\nCaritas Verband Hamburg e.V.\nSpende von: Maria Muster\nBetrag: 500,00 €\nDatum: 22.11.2024\nArt: Geldzuwendung\nDie Zuwendung wird für steuerbegünstigte Zwecke verwendet.\nWir sind nach §5 Abs. 1 Nr. 9 KStG von der Körperschaftsteuer befreit.",
            extractions=[lx.Extraction(
                entity="Spendenbescheinigung",
                attributes={
                    "beleg_typ": "spendenbescheinigung",
                    "aussteller": "Caritas Verband Hamburg e.V.",
                    "beschreibung": "Geldzuwendung an Caritas Verband Hamburg",
                    "betrag_brutto": "500.00",
                    "datum_beleg": "22.11.2024",
                    "steuer_kategorie": "Spenden und Mitgliedsbeiträge",
                    "skr03_konto": "6300"
                }
            )]
        ),
        lx.ExampleData(
            text="Nebenkostenabrechnung 2024\nHausverwaltung Meyer GmbH\nMieter: Familie Mustermann, Musterweg 5, 20357 Hamburg\nAbrechnungszeitraum: 01.01.2024 - 31.12.2024\nHausmeister: 420,00 €\nSchornsteinfeger: 85,00 €\nGartenpflege: 380,00 €\nTreppenhausreinigung: 520,00 €\nMüllabfuhr: 240,00 €\nGesamt: 1.645,00 €\nVorauszahlung: 1.500,00 €\nNachzahlung: 145,00 €",
            extractions=[lx.Extraction(
                entity="Nebenkostenabrechnung",
                attributes={
                    "beleg_typ": "nebenkostenabrechnung",
                    "aussteller": "Hausverwaltung Meyer GmbH",
                    "beschreibung": "Nebenkostenabrechnung 2024 - Musterweg 5",
                    "betrag_brutto": "1645.00",
                    "datum_beleg": "2024",
                    "steuer_kategorie": "Haushaltsnahe Dienstleistungen §35a",
                    "arbeitskosten_35a": "1320.00",
                    "materialkosten": "325.00",
                    "nachzahlung": "145.00"
                }
            )]
        ),
    ]


async def extract_with_langextract(ocr_text: str) -> Optional[dict]:
    """Extract with LangExtract – returns structured data WITH source grounding."""
    try:
        import langextract as lx
    except ImportError:
        logger.warning("LangExtract not installed, using fallback")
        return None

    examples = _langextract_examples()
    if not examples:
        return None

    prompt = (
        "Analysiere diesen deutschen Steuerbeleg und extrahiere alle steuerlich relevanten Informationen. "
        "Identifiziere: Belegtyp, Aussteller, Beträge (brutto/netto/MwSt), Datum, steuerliche Kategorie, "
        "SKR03-Konto, Rechnungsnummer, und ob §35a-Arbeitskosten enthalten sind. "
        "Bei Handwerkerrechnungen: trenne Arbeitskosten (§35a) von Materialkosten. "
        "Deutsche Zahlenformate: 1.234,56 → im Output als 1234.56"
    )

    try:
        result = lx.extract(
            text_or_documents=ocr_text,
            prompt_description=prompt,
            examples=examples,
            language_model_type=lx.inference.OllamaLanguageModel,
            model_id=OLLAMA_MODEL,
            model_url=OLLAMA_URL,
            fence_output=False,
            use_schema_constraints=False,
        )

        if not result or not result.extractions:
            return None

        ext = result.extractions[0]
        attrs = ext.attributes if hasattr(ext, 'attributes') else {}

        # Build source grounding spans
        spans = []
        if hasattr(ext, 'spans') and ext.spans:
            for s in ext.spans:
                span_text = ocr_text[s.start:s.end] if s.start < len(ocr_text) else ""
                spans.append({
                    "start": s.start, "end": s.end,
                    "text": span_text,
                    "feld": getattr(s, 'label', None)
                })

        # If LangExtract didn't produce spans, build them ourselves via text search
        if not spans:
            spans = _build_source_spans(ocr_text, attrs)

        return {
            "extrahierte_daten": attrs,
            "quellreferenzen": spans,
            "methode": "langextract",
            "konfidenz": _assess_confidence(attrs)
        }

    except Exception as e:
        logger.error(f"LangExtract error: {e}")
        return None


# ════════════════════════════════════════════
#  Ollama Fallback (no source grounding from LLM, but we build it post-hoc)
# ════════════════════════════════════════════

EXTRACTION_PROMPT = """Du bist ein Experte für deutsche Steuerdokumente. Analysiere den OCR-Text und extrahiere als JSON.

NUR valides JSON, kein anderer Text:
{{
  "beleg_typ": "rechnung|handwerkerrechnung|lohnsteuerbescheinigung|spendenbescheinigung|versicherungsnachweis|kontoauszug|nebenkostenabrechnung|arztrechnung|fahrtkosten|bewirtungsbeleg|sonstig",
  "aussteller": "Name",
  "beschreibung": "Kurzbeschreibung",
  "betrag_brutto": 0.00,
  "betrag_netto": 0.00,
  "mwst_satz": 19,
  "mwst_betrag": 0.00,
  "datum_beleg": "TT.MM.JJJJ",
  "rechnungsnummer": "falls vorhanden",
  "steuer_kategorie": "Werbungskosten|Sonderausgaben|Außergewöhnliche Belastungen|Haushaltsnahe Dienstleistungen §35a|Handwerkerleistungen §35a|Vorsorgeaufwendungen|Spenden und Mitgliedsbeiträge|Einkünfte nichtselbständige Arbeit",
  "skr03_konto": "4-stellig",
  "arbeitskosten_35a": 0.00,
  "materialkosten": 0.00,
  "konfidenz": "hoch|mittel|niedrig"
}}

Wichtig: Bei Handwerkerrechnungen und Nebenkostenabrechnungen trenne Arbeitskosten (§35a absetzbar) von Materialkosten (nicht absetzbar). arbeitskosten_35a = nur Lohn-/Arbeitsanteil. materialkosten = Material, Verbrauchsstoffe, Entsorgung etc.
Deutsche Zahlen: 1.234,56 → 1234.56 im JSON. Unbekannte Felder: null.

OCR-TEXT:
{text}"""


async def extract_with_ollama(ocr_text: str) -> dict:
    """Direct Ollama extraction with post-hoc source grounding."""
    prompt = EXTRACTION_PROMPT.format(text=ocr_text[:4000])

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024}
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                data = json.loads(match.group())
                spans = _build_source_spans(ocr_text, data)
                return {
                    "extrahierte_daten": data,
                    "quellreferenzen": spans,
                    "methode": "ollama_direkt",
                    "konfidenz": data.get("konfidenz", "mittel")
                }
    except Exception as e:
        logger.error(f"Ollama error: {e}")

    return {"extrahierte_daten": {}, "quellreferenzen": [], "methode": "fehler", "konfidenz": "niedrig"}


# ════════════════════════════════════════════
#  Post-hoc Source Grounding
# ════════════════════════════════════════════

def _build_source_spans(ocr_text: str, attrs: dict) -> list:
    """Build source grounding by finding extracted values in the OCR text.
    This is the fallback when LangExtract doesn't provide native spans."""
    spans = []
    text_lower = ocr_text.lower()

    search_fields = {
        "aussteller": attrs.get("aussteller"),
        "betrag_brutto": attrs.get("betrag_brutto"),
        "betrag_netto": attrs.get("betrag_netto"),
        "mwst_betrag": attrs.get("mwst_betrag"),
        "datum_beleg": attrs.get("datum_beleg"),
        "rechnungsnummer": attrs.get("rechnungsnummer"),
        "arbeitskosten_35a": attrs.get("arbeitskosten_35a"),
        "materialkosten": attrs.get("materialkosten"),
    }

    for feld, value in search_fields.items():
        if not value or value == "null":
            continue
        value_str = str(value)

        # Try exact match first
        idx = ocr_text.find(value_str)
        if idx >= 0:
            spans.append({"start": idx, "end": idx + len(value_str), "text": value_str, "feld": feld})
            continue

        # Try German number format (1234.56 → 1.234,56)
        if re.match(r'^\d+\.?\d*$', value_str):
            german = _to_german_number(value_str)
            for variant in [german, value_str.replace(".", ",")]:
                idx = ocr_text.find(variant)
                if idx >= 0:
                    spans.append({"start": idx, "end": idx + len(variant), "text": variant, "feld": feld})
                    break

        # Try case-insensitive for text fields
        if feld in ("aussteller", "rechnungsnummer"):
            idx = text_lower.find(value_str.lower())
            if idx >= 0:
                spans.append({"start": idx, "end": idx + len(value_str), "text": ocr_text[idx:idx+len(value_str)], "feld": feld})

    return spans


def _to_german_number(n: str) -> str:
    """Convert 1234.56 to 1.234,56."""
    try:
        f = float(n)
        integer_part = int(f)
        decimal_part = f - integer_part
        formatted_int = f"{integer_part:,}".replace(",", ".")
        if decimal_part > 0:
            return f"{formatted_int},{decimal_part:.2f}"[:-1].split(",")[0] + f",{round(decimal_part * 100):02d}"
        return f"{formatted_int},00"
    except (ValueError, TypeError):
        return n


def _assess_confidence(attrs: dict) -> str:
    """Assess extraction confidence based on field completeness."""
    required = ["beleg_typ", "betrag_brutto", "aussteller", "datum_beleg"]
    found = sum(1 for f in required if attrs.get(f) and attrs[f] != "null")
    if found >= 4:
        return "hoch"
    elif found >= 2:
        return "mittel"
    return "niedrig"


# ════════════════════════════════════════════
#  Auto-Kontierung (SKR03 mapping)
# ════════════════════════════════════════════

KONTIERUNG_MAP = {
    "handwerkerrechnung": ("4946", "Fremdleistungen", "3"),
    "rechnung": ("4900", "Sonst. betriebl. Aufwend.", "3"),
    "spendenbescheinigung": ("6300", "Sonst. betriebl. Aufwend.", ""),
    "bewirtungsbeleg": ("4650", "Bewirtungskosten", "3"),
    "fahrtkosten": ("4500", "Fahrzeugkosten", ""),
    "arztrechnung": ("4900", "Sonst. betriebl. Aufwend.", ""),
    "versicherungsnachweis": ("4300", "Versicherungen", ""),
    "nebenkostenabrechnung": ("4210", "Miete", ""),
    "lohnsteuerbescheinigung": ("4120", "Gehälter", ""),
}


def auto_kontierung(beleg_typ: str, mwst_satz: float = None) -> dict:
    """Auto-assign SKR03 account based on document type."""
    entry = KONTIERUNG_MAP.get(beleg_typ, ("4900", "Sonst. betriebl. Aufwend.", ""))
    bu = entry[2]
    if mwst_satz and not bu:
        bu = "3" if mwst_satz >= 15 else ("2" if mwst_satz >= 5 else "")
    return {"skr03_konto": entry[0], "skr03_bezeichnung": entry[1], "bu_schluessel": bu}


# ════════════════════════════════════════════
#  Main Entry Point
# ════════════════════════════════════════════

async def extract_beleg(ocr_text: str) -> dict:
    """Main extraction: tries LangExtract first, falls back to Ollama."""
    result = await extract_with_langextract(ocr_text)
    if not result:
        result = await extract_with_ollama(ocr_text)

    # Auto-kontierung if not provided
    data = result.get("extrahierte_daten", {})
    if data.get("beleg_typ") and not data.get("skr03_konto"):
        mwst = None
        try:
            mwst = float(data.get("mwst_satz", 0))
        except (ValueError, TypeError):
            pass
        kont = auto_kontierung(data["beleg_typ"], mwst)
        data.update(kont)
        result["extrahierte_daten"] = data

    return result


# ════════════════════════════════════════════
#  Missing Documents Detection
# ════════════════════════════════════════════

ERWARTETE_BELEGE = {
    "Pflicht": [
        ("lohnsteuerbescheinigung", "Lohnsteuerbescheinigung"),
    ],
    "Häufig relevant": [
        ("versicherungsnachweis", "Krankenversicherung"),
        ("spendenbescheinigung", "Spendenbescheinigungen"),
        ("handwerkerrechnung", "Handwerkerrechnungen (§35a)"),
        ("nebenkostenabrechnung", "Nebenkostenabrechnung"),
    ],
    "Prüfen": [
        ("arztrechnung", "Arztrechnungen (außergew. Belastungen)"),
        ("fahrtkosten", "Fahrtkosten (Pendlerpauschale)"),
        ("bewirtungsbeleg", "Bewirtungsbelege"),
    ],
}

def detect_missing(beleg_typen: list[str]) -> dict:
    vorhandene = set(beleg_typen)
    fehlend, empfehlungen = [], []
    for prio, items in ERWARTETE_BELEGE.items():
        for typ, label in items:
            if typ not in vorhandene:
                fehlend.append(label)
                icon = "🔴" if prio == "Pflicht" else ("🟡" if prio == "Häufig relevant" else "🔵")
                empfehlungen.append(f"{icon} {prio}: {label}")
    return {"fehlende": fehlend, "vorhandene": list(vorhandene), "empfehlungen": empfehlungen}
