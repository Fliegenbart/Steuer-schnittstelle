"""BelegSync – Extraction Service (Ollama-only).

Extrahiert steuerlich relevante Daten aus OCR-Text via Llama 3.1 8B.
Source Grounding: Jeder extrahierte Wert wird auf seine Position im OCR-Text gemappt.
"""
import os, json, re, logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")


# ════════════════════════════════════════════
#  Ollama Extraction – optimierter Prompt
# ════════════════════════════════════════════

SYSTEM_PROMPT = """Du bist ein Experte für deutsche Steuerbelege. Du analysierst OCR-Text und extrahierst steuerlich relevante Daten als JSON.

REGELN:
- Antworte NUR mit einem JSON-Objekt, kein anderer Text
- Deutsche Zahlen (1.234,56) als Dezimalzahl im JSON: 1234.56
- Unbekannte Felder: null (nicht "null", nicht "", nicht 0)
- Datum im Format TT.MM.JJJJ
- Bei Handwerkerrechnungen/Nebenkostenabrechnungen: trenne Arbeitskosten (§35a absetzbar) von Materialkosten (nicht absetzbar)

FELDER:
- beleg_typ: rechnung | handwerkerrechnung | lohnsteuerbescheinigung | spendenbescheinigung | versicherungsnachweis | kontoauszug | nebenkostenabrechnung | arztrechnung | fahrtkosten | bewirtungsbeleg | sonstig
- aussteller: Name der Firma/Person die den Beleg ausgestellt hat
- beschreibung: Kurzbeschreibung des Belegs (max 100 Zeichen)
- betrag_brutto: Gesamtbetrag inkl. MwSt
- betrag_netto: Nettobetrag ohne MwSt (null falls nicht angegeben)
- mwst_satz: MwSt-Prozentsatz (7 oder 19, null falls nicht erkennbar)
- mwst_betrag: MwSt-Betrag in Euro
- datum_beleg: Rechnungs-/Belegdatum
- rechnungsnummer: Rechnungs- oder Belegnummer
- steuer_kategorie: Eine der folgenden Kategorien:
  Werbungskosten | Sonderausgaben | Außergewöhnliche Belastungen | Haushaltsnahe Dienstleistungen §35a | Handwerkerleistungen §35a | Vorsorgeaufwendungen | Spenden und Mitgliedsbeiträge | Einkünfte nichtselbständige Arbeit | Einkünfte selbständige Arbeit | Einkünfte Vermietung/Verpachtung
- skr03_konto: 4-stelliges SKR03-Konto (z.B. 4946 für Fremdleistungen, 4210 für Miete)
- arbeitskosten_35a: Nur der Arbeits-/Lohnanteil bei Handwerkerrechnungen oder haushaltsnahen Dienstleistungen (§35a EStG absetzbar)
- materialkosten: Nur der Materialanteil (NICHT absetzbar nach §35a)"""

ONE_SHOT_EXAMPLE = """
BEISPIEL:
OCR-Text: "Rechnung Nr. 2024-0815\\nMalermeister Schmidt GmbH\\nAnstricharbeiten Wohnzimmer\\nArbeitskosten: 1.200,00 €\\nMaterial: 340,00 €\\nNetto: 1.540,00 €\\nMwSt 19%: 292,60 €\\nBrutto: 1.832,60 €\\nDatum: 15.03.2024"

Antwort:
{"beleg_typ": "handwerkerrechnung", "aussteller": "Malermeister Schmidt GmbH", "beschreibung": "Anstricharbeiten Wohnzimmer", "betrag_brutto": 1832.60, "betrag_netto": 1540.00, "mwst_satz": 19, "mwst_betrag": 292.60, "datum_beleg": "15.03.2024", "rechnungsnummer": "2024-0815", "steuer_kategorie": "Handwerkerleistungen §35a", "skr03_konto": "4946", "arbeitskosten_35a": 1200.00, "materialkosten": 340.00}
"""

USER_PROMPT = """Analysiere diesen OCR-Text und extrahiere die steuerlich relevanten Daten als JSON:

{text}"""


def _clean_extracted_data(data: dict) -> dict:
    """Bereinige LLM-Output: String-Nulls, leere Strings, ungültige Werte."""
    cleaned = {}
    for key, value in data.items():
        # "null", "None", "", "N/A" → None
        if isinstance(value, str) and value.strip().lower() in ("null", "none", "", "n/a", "nicht angegeben", "unbekannt"):
            cleaned[key] = None
        # 0 bei optionalen Geldbeträgen → None (LLM gibt oft 0.00 statt null)
        elif isinstance(value, (int, float)) and value == 0 and key in (
            "betrag_netto", "mwst_betrag", "mwst_satz", "arbeitskosten_35a", "materialkosten"
        ):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


def _parse_json_from_llm(raw: str) -> Optional[dict]:
    """Robust JSON-Parsing aus LLM-Output (mit/ohne Markdown-Fences)."""
    if not raw or not raw.strip():
        return None

    # Versuch 1: Markdown ```json ... ``` Block
    fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Versuch 2: Erstes JSON-Objekt im Text
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Versuch 3: Ganzer Text als JSON
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    return None


async def extract_with_ollama(ocr_text: str, retry: bool = True) -> dict:
    """Extrahiert steuerlich relevante Daten via Ollama mit post-hoc Source Grounding."""
    prompt = f"{SYSTEM_PROMPT}\n{ONE_SHOT_EXAMPLE}\n{USER_PROMPT.format(text=ocr_text[:4000])}"

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1500}
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            logger.info(f"Ollama raw response length: {len(raw)}")

            data = _parse_json_from_llm(raw)

            # Retry einmal bei Parse-Fehler (LLM kann inkonsistent sein)
            if data is None and retry:
                logger.warning("JSON parse failed, retrying extraction...")
                return await extract_with_ollama(ocr_text, retry=False)

            if data is None:
                logger.error(f"Could not parse JSON from Ollama response: {raw[:200]}")
                return {
                    "extrahierte_daten": {},
                    "quellreferenzen": [],
                    "methode": "ollama_direkt",
                    "konfidenz": "niedrig"
                }

            data = _clean_extracted_data(data)
            spans = _build_source_spans(ocr_text, data)

            return {
                "extrahierte_daten": data,
                "quellreferenzen": spans,
                "methode": "ollama_direkt",
                "konfidenz": _assess_confidence(data)
            }

    except httpx.ConnectError:
        logger.error(f"Ollama not reachable at {OLLAMA_URL}")
    except httpx.TimeoutException:
        logger.error(f"Ollama timeout after 180s")
    except Exception as e:
        logger.error(f"Ollama error: {e}")

    return {
        "extrahierte_daten": {},
        "quellreferenzen": [],
        "methode": "fehler",
        "konfidenz": "niedrig"
    }


# ════════════════════════════════════════════
#  Post-hoc Source Grounding
# ════════════════════════════════════════════

def _build_source_spans(ocr_text: str, attrs: dict) -> list:
    """Findet extrahierte Werte im OCR-Text und erstellt Source-Grounding-Spans.
    Jeder Span zeigt: wo im Originaltext steht der extrahierte Wert."""
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
        "beschreibung": attrs.get("beschreibung"),
    }

    for feld, value in search_fields.items():
        if value is None:
            continue
        value_str = str(value)
        if not value_str or value_str == "null":
            continue

        # Exakte Suche
        idx = ocr_text.find(value_str)
        if idx >= 0:
            spans.append({"start": idx, "end": idx + len(value_str), "text": value_str, "feld": feld})
            continue

        # Deutsche Zahlenformate (1234.56 → 1.234,56)
        if re.match(r'^\d+\.?\d*$', value_str):
            german = _to_german_number(value_str)
            for variant in [german, value_str.replace(".", ",")]:
                idx = ocr_text.find(variant)
                if idx >= 0:
                    spans.append({"start": idx, "end": idx + len(variant), "text": variant, "feld": feld})
                    break
            else:
                # Auch ohne Tausender-Trenner suchen (z.B. "1200,00" statt "1.200,00")
                simple = value_str.split(".")[0] + "," + (value_str.split(".")[1] if "." in value_str else "00")
                idx = ocr_text.find(simple)
                if idx >= 0:
                    spans.append({"start": idx, "end": idx + len(simple), "text": simple, "feld": feld})

        # Case-insensitive für Textfelder + Teilstring-Matching
        if feld in ("aussteller", "rechnungsnummer", "beschreibung"):
            idx = text_lower.find(value_str.lower())
            if idx >= 0:
                spans.append({"start": idx, "end": idx + len(value_str), "text": ocr_text[idx:idx+len(value_str)], "feld": feld})
            elif feld == "aussteller" and len(value_str) > 5:
                # Fuzzy: Suche nach den ersten 2 Wörtern des Ausstellers (OCR-Fehler-tolerant)
                words = value_str.split()[:2]
                if len(words) >= 2:
                    pattern = re.escape(words[0]) + r'[\s\-]+' + re.escape(words[1])
                    match = re.search(pattern, ocr_text, re.IGNORECASE)
                    if match:
                        spans.append({"start": match.start(), "end": match.end(), "text": match.group(), "feld": feld})

    return spans


def _to_german_number(n: str) -> str:
    """Konvertiert 1234.56 → 1.234,56."""
    try:
        f = float(n)
        integer_part = int(f)
        decimal_part = round(f - integer_part, 2)
        formatted_int = f"{integer_part:,}".replace(",", ".")
        if decimal_part > 0:
            dec_str = f"{decimal_part:.2f}"[2:]  # ".56" → "56"
            return f"{formatted_int},{dec_str}"
        return f"{formatted_int},00"
    except (ValueError, TypeError):
        return n


def _assess_confidence(attrs: dict) -> str:
    """Bewertet Extraktionsqualität anhand Feld-Vollständigkeit."""
    required = ["beleg_typ", "betrag_brutto", "aussteller", "datum_beleg"]
    found = sum(1 for f in required if attrs.get(f) is not None)
    if found >= 4:
        return "hoch"
    elif found >= 2:
        return "mittel"
    return "niedrig"


# ════════════════════════════════════════════
#  Auto-Kontierung (SKR03 Mapping)
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
    """Auto-Kontierung: SKR03-Konto anhand Belegtyp zuweisen."""
    entry = KONTIERUNG_MAP.get(beleg_typ, ("4900", "Sonst. betriebl. Aufwend.", ""))
    bu = entry[2]
    if mwst_satz and not bu:
        bu = "3" if mwst_satz >= 15 else ("2" if mwst_satz >= 5 else "")
    return {"skr03_konto": entry[0], "skr03_bezeichnung": entry[1], "bu_schluessel": bu}


# ════════════════════════════════════════════
#  Main Entry Point
# ════════════════════════════════════════════

async def extract_beleg(ocr_text: str) -> dict:
    """Hauptfunktion: Extrahiert Belegdaten via Ollama + Auto-Kontierung."""
    result = await extract_with_ollama(ocr_text)

    # Auto-Kontierung falls nicht vom LLM geliefert
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
