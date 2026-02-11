"""BelegSync – Extraction Service mit LLM-nativem Source Grounding + Vision-Dual-Pass.

Extrahiert steuerlich relevante Daten aus OCR-Text via Ollama (Llama 3.1 8B).
Eigenes Source Grounding: Das LLM liefert für jeden Wert den exakten Quelltext-
Ausschnitt aus dem OCR-Text. So kann der Steuerberater jeden extrahierten Wert
direkt im Originaldokument nachvollziehen (Explainable AI).

Bei schlechter OCR-Qualität (< Schwellwert): Zusätzlicher Vision-Pass mit
Qwen2.5-VL – liest das Originalbild direkt und ergänzt fehlende Felder.
"""
import os, json, re, logging, base64
from pathlib import Path
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")


# ════════════════════════════════════════════
#  Ollama Extraction – Prompt mit Source Grounding
# ════════════════════════════════════════════

SYSTEM_PROMPT = """Du bist ein Experte für deutsche Steuerbelege. Du analysierst OCR-Text und extrahierst steuerlich relevante Daten als JSON.

REGELN:
- Antworte NUR mit einem JSON-Objekt, kein anderer Text
- Deutsche Zahlen (1.234,56) als Dezimalzahl im JSON-Wert: 1234.56
- Unbekannte Felder: null (nicht "null", nicht "", nicht 0)
- Datum im Format TT.MM.JJJJ
- Bei Handwerkerrechnungen/Nebenkostenabrechnungen: trenne Arbeitskosten (§35a absetzbar) von Materialkosten (nicht absetzbar)
- Bei Kassenbons/Kassenzettel: Aussteller = Filialname/Marke (z.B. "REWE", "EDEKA", "dm"), Beschreibung = "Einkauf [Filiale]", Betrag = Summe/Total/GESAMT-Zeile, betrag_netto und arbeitskosten_35a sind null

QUELLENNACHWEISE (Source Grounding):
- Für JEDEN extrahierten Wert gib zusätzlich "quelle" an
- "quelle" = der EXAKTE Textausschnitt aus dem OCR-Text, aus dem du den Wert abgeleitet hast
- Kopiere den Text GENAU wie er im OCR-Text steht (inkl. Sonderzeichen, Leerzeichen)
- Für abgeleitete Felder (beleg_typ, steuer_kategorie, skr03_konto): quelle = null
- Format pro Feld: {"wert": <extrahierter_wert>, "quelle": "<exakter_OCR_text>" oder null}

FELDER:
- beleg_typ: rechnung | handwerkerrechnung | lohnsteuerbescheinigung | spendenbescheinigung | versicherungsnachweis | kontoauszug | nebenkostenabrechnung | arztrechnung | fahrtkosten | bewirtungsbeleg | kassenbon | sonstig
- aussteller: Name der Firma/Person
- beschreibung: Kurzbeschreibung (max 100 Zeichen)
- betrag_brutto: Gesamtbetrag inkl. MwSt
- betrag_netto: Nettobetrag ohne MwSt
- mwst_satz: MwSt-Prozentsatz (7 oder 19)
- mwst_betrag: MwSt-Betrag in Euro
- datum_beleg: Rechnungs-/Belegdatum
- rechnungsnummer: Rechnungs- oder Belegnummer
- steuer_kategorie: Werbungskosten | Sonderausgaben | Außergewöhnliche Belastungen | Haushaltsnahe Dienstleistungen §35a | Handwerkerleistungen §35a | Vorsorgeaufwendungen | Spenden und Mitgliedsbeiträge | Einkünfte nichtselbständige Arbeit | Einkünfte selbständige Arbeit | Einkünfte Vermietung/Verpachtung
- skr03_konto: 4-stelliges SKR03-Konto
- arbeitskosten_35a: Arbeits-/Lohnanteil (§35a absetzbar)
- materialkosten: Materialanteil (NICHT absetzbar)"""

ONE_SHOT_EXAMPLE = """
BEISPIEL 1 (Handwerkerrechnung):
OCR-Text: "Rechnung Nr. 2024-0815\\nMalermeister Schmidt GmbH\\nHauptstr. 12, 20095 Hamburg\\nAnstricharbeiten Wohnzimmer\\nArbeitskosten: 1.200,00 €\\nMaterial: 340,00 €\\nNetto: 1.540,00 €\\nMwSt 19%: 292,60 €\\nBrutto: 1.832,60 €\\nDatum: 15.03.2024"

Antwort:
{"beleg_typ": {"wert": "handwerkerrechnung", "quelle": null}, "aussteller": {"wert": "Malermeister Schmidt GmbH", "quelle": "Malermeister Schmidt GmbH"}, "beschreibung": {"wert": "Anstricharbeiten Wohnzimmer", "quelle": "Anstricharbeiten Wohnzimmer"}, "betrag_brutto": {"wert": 1832.60, "quelle": "Brutto: 1.832,60 \\u20ac"}, "betrag_netto": {"wert": 1540.00, "quelle": "Netto: 1.540,00 \\u20ac"}, "mwst_satz": {"wert": 19, "quelle": "MwSt 19%"}, "mwst_betrag": {"wert": 292.60, "quelle": "MwSt 19%: 292,60 \\u20ac"}, "datum_beleg": {"wert": "15.03.2024", "quelle": "Datum: 15.03.2024"}, "rechnungsnummer": {"wert": "2024-0815", "quelle": "Rechnung Nr. 2024-0815"}, "steuer_kategorie": {"wert": "Handwerkerleistungen \\u00a735a", "quelle": null}, "skr03_konto": {"wert": "4946", "quelle": null}, "arbeitskosten_35a": {"wert": 1200.00, "quelle": "Arbeitskosten: 1.200,00 \\u20ac"}, "materialkosten": {"wert": 340.00, "quelle": "Material: 340,00 \\u20ac"}}

BEISPIEL 2 (Kassenbon):
OCR-Text: "REWE Markt GmbH\\nFiliale 1234\\nSchloßstr. 15, 10965 Berlin\\n12.03.2024 14:23\\nBio Milch 3,5% 1,99\\nVollkornbrot 500g 2,49\\nApfel Braeburn 1kg 3,29\\n-----------\\nSumme EUR 7,77\\nMwSt 7% 0,51\\nBAR 10,00\\nRUCKGELD 2,23"

Antwort:
{"beleg_typ": {"wert": "kassenbon", "quelle": null}, "aussteller": {"wert": "REWE Markt GmbH", "quelle": "REWE Markt GmbH"}, "beschreibung": {"wert": "Einkauf REWE", "quelle": null}, "betrag_brutto": {"wert": 7.77, "quelle": "Summe EUR 7,77"}, "betrag_netto": {"wert": null, "quelle": null}, "mwst_satz": {"wert": 7, "quelle": "MwSt 7%"}, "mwst_betrag": {"wert": 0.51, "quelle": "MwSt 7% 0,51"}, "datum_beleg": {"wert": "12.03.2024", "quelle": "12.03.2024 14:23"}, "rechnungsnummer": {"wert": null, "quelle": null}, "steuer_kategorie": {"wert": "Werbungskosten", "quelle": null}, "skr03_konto": {"wert": "4900", "quelle": null}, "arbeitskosten_35a": {"wert": null, "quelle": null}, "materialkosten": {"wert": null, "quelle": null}}
"""

USER_PROMPT = """Analysiere diesen OCR-Text und extrahiere die steuerlich relevanten Daten als JSON mit Quellennachweisen:

{text}"""


# ════════════════════════════════════════════
#  Response Parsing & Cleaning
# ════════════════════════════════════════════

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


def _unwrap_sourced_response(data: dict) -> tuple:
    """Entpacke {wert, quelle}-Paare in flache Werte + Quellen-Dict.

    Tolerant: Akzeptiert gemischt flat/nested Antworten.

    Returns:
        (flat_data, source_quotes) – z.B.:
        flat_data:      {"aussteller": "Schmidt GmbH", "betrag_brutto": 1832.60}
        source_quotes:  {"aussteller": "Malermeister Schmidt GmbH", "betrag_brutto": "Brutto: 1.832,60 €"}
    """
    flat = {}
    quotes = {}
    for key, value in data.items():
        if isinstance(value, dict) and "wert" in value:
            # Nested {wert, quelle} Format
            flat[key] = value["wert"]
            if value.get("quelle"):
                quotes[key] = str(value["quelle"])
        else:
            # Flat value (LLM hat quelle-Anweisung ignoriert)
            flat[key] = value
    return flat, quotes


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


# ════════════════════════════════════════════
#  LLM-natives Source Grounding (Quellen-Matching)
# ════════════════════════════════════════════

def _build_source_spans_from_quotes(ocr_text: str, quotes: dict) -> list:
    """Lokalisiert LLM-Quellennachweise im OCR-Text.

    Das LLM hat für jeden Wert ein 'quelle'-Feld geliefert (exakter Textausschnitt).
    Hier finden wir die Position dieses Ausschnitts im Original-OCR-Text.
    """
    spans = []
    for feld, quote in quotes.items():
        if not quote or not isinstance(quote, str) or len(quote.strip()) < 2:
            continue

        span = _locate_quote_in_text(ocr_text, quote.strip(), feld)
        if span:
            spans.append(span)
        else:
            logger.debug(f"Source quote not found for '{feld}': '{quote[:50]}'")

    return spans


def _locate_quote_in_text(ocr_text: str, quote: str, feld: str) -> Optional[dict]:
    """4-stufige Matching-Kaskade: Findet ein LLM-Zitat im OCR-Text.

    Tier 1: Exakte Suche
    Tier 2: Case-insensitive
    Tier 3: Normalisiert (Whitespace kollabiert)
    Tier 4: Fuzzy Sliding Window (Bigram-Dice ≥ 0.80)
    """
    # Tier 1: Exakt
    idx = ocr_text.find(quote)
    if idx >= 0:
        return {"start": idx, "end": idx + len(quote), "text": quote, "feld": feld}

    # Tier 2: Case-insensitive
    idx = ocr_text.lower().find(quote.lower())
    if idx >= 0:
        matched = ocr_text[idx:idx + len(quote)]
        return {"start": idx, "end": idx + len(quote), "text": matched, "feld": feld}

    # Tier 3: Normalisiert (Whitespace, Zeilenumbrüche)
    norm_quote = _normalize_text(quote)
    norm_ocr = _normalize_text(ocr_text)
    norm_idx = norm_ocr.find(norm_quote)
    if norm_idx >= 0:
        orig_start, orig_end = _map_normalized_pos(ocr_text, norm_ocr, norm_idx, len(norm_quote))
        matched = ocr_text[orig_start:orig_end]
        return {"start": orig_start, "end": orig_end, "text": matched, "feld": feld}

    # Tier 4: Fuzzy (nur für nicht-triviale Strings)
    if len(quote) >= 5:
        result = _fuzzy_slide_match(ocr_text, quote, threshold=0.80)
        if result:
            start, end = result
            return {"start": start, "end": end, "text": ocr_text[start:end], "feld": feld}

    return None


def _normalize_text(text: str) -> str:
    """Normalisiert Text: Whitespace kollabieren, Lowercase."""
    return re.sub(r'\s+', ' ', text).strip().lower()


def _map_normalized_pos(original: str, normalized: str, norm_start: int, norm_len: int) -> tuple:
    """Mappt Position im normalisierten Text zurück auf Original-Positionen.

    Berücksichtigt kollabierte Whitespace-Sequenzen.
    """
    orig_pos = 0
    norm_pos = 0
    orig_start = None

    while norm_pos < len(normalized) and orig_pos < len(original):
        if norm_pos == norm_start and orig_start is None:
            orig_start = orig_pos
        if norm_pos == norm_start + norm_len:
            return (orig_start or 0, orig_pos)

        if normalized[norm_pos] == ' ' and original[orig_pos] in (' ', '\t', '\n', '\r'):
            norm_pos += 1
            while orig_pos < len(original) and original[orig_pos] in (' ', '\t', '\n', '\r'):
                orig_pos += 1
        else:
            norm_pos += 1
            orig_pos += 1

    if orig_start is not None:
        return (orig_start, orig_pos)
    return (0, min(norm_len, len(original)))


def _fuzzy_slide_match(ocr_text: str, quote: str, threshold: float = 0.80) -> Optional[tuple]:
    """Sliding-Window Fuzzy-Match mit Bigram-Dice-Koeffizient.

    Schiebt ein Fenster (±20% der Quote-Länge) über den OCR-Text und
    findet die Position mit der höchsten Ähnlichkeit.
    """
    qlen = len(quote)
    if qlen < 5 or len(ocr_text) < qlen:
        return None

    quote_lower = quote.lower()
    text_lower = ocr_text.lower()
    quote_bigrams = _bigrams(quote_lower)

    if not quote_bigrams:
        return None

    best_ratio = 0.0
    best_pos = None

    # Fenstergrößen: exakt, ±10%, ±20%
    window_sizes = sorted(set([
        qlen,
        max(3, int(qlen * 0.9)),
        min(len(ocr_text), int(qlen * 1.1)),
        max(3, int(qlen * 0.8)),
        min(len(ocr_text), int(qlen * 1.2)),
    ]))

    for window_size in window_sizes:
        if window_size > len(ocr_text):
            continue
        for i in range(0, len(ocr_text) - window_size + 1, 1):
            candidate = text_lower[i:i + window_size]
            cand_bigrams = _bigrams(candidate)
            if not cand_bigrams:
                continue

            # Dice-Koeffizient
            overlap = len(quote_bigrams & cand_bigrams)
            ratio = 2.0 * overlap / (len(quote_bigrams) + len(cand_bigrams))

            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = (i, i + window_size)

    if best_ratio >= threshold and best_pos:
        return best_pos
    return None


def _bigrams(s: str) -> set:
    """Erzeugt Bigram-Set aus einem String."""
    return set(s[i:i+2] for i in range(len(s) - 1)) if len(s) >= 2 else set()


# ════════════════════════════════════════════
#  Post-hoc Source Grounding (Fallback)
# ════════════════════════════════════════════

def _build_source_spans(ocr_text: str, attrs: dict) -> list:
    """Fallback: Findet extrahierte Werte im OCR-Text per Textsuche.
    Wird genutzt wenn das LLM keine quelle-Felder liefert."""
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
                # Ohne Tausender-Trenner (z.B. "1200,00")
                simple = value_str.split(".")[0] + "," + (value_str.split(".")[1] if "." in value_str else "00")
                idx = ocr_text.find(simple)
                if idx >= 0:
                    spans.append({"start": idx, "end": idx + len(simple), "text": simple, "feld": feld})

        # Case-insensitive für Textfelder
        if feld in ("aussteller", "rechnungsnummer", "beschreibung"):
            idx = text_lower.find(value_str.lower())
            if idx >= 0:
                spans.append({"start": idx, "end": idx + len(value_str), "text": ocr_text[idx:idx+len(value_str)], "feld": feld})
            elif feld == "aussteller" and len(value_str) > 5:
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
            dec_str = f"{decimal_part:.2f}"[2:]
            return f"{formatted_int},{dec_str}"
        return f"{formatted_int},00"
    except (ValueError, TypeError):
        return n


# ════════════════════════════════════════════
#  Confidence Assessment
# ════════════════════════════════════════════

def _assess_confidence(attrs: dict, spans: list = None) -> str:
    """Bewertet Extraktionsqualität: Feld-Vollständigkeit + Source Grounding.

    Kassenbons haben weniger Felder (kein Netto, keine Rechnungsnr.) und
    bekommen deshalb angepasste Schwellwerte.
    """
    required = ["beleg_typ", "betrag_brutto", "aussteller", "datum_beleg"]
    found = sum(1 for f in required if attrs.get(f) is not None)

    # Bonus: Wie viele Felder sind source-gegrundet?
    grounded = set(s["feld"] for s in (spans or []))
    grounded_count = sum(1 for f in ["betrag_brutto", "aussteller", "datum_beleg"] if f in grounded)

    beleg_typ = attrs.get("beleg_typ", "")

    # Kassenbons: weniger strenge Anforderungen
    # (haben typisch nur Betrag + Aussteller/Filiale + Datum, selten Rechnungsnr.)
    if beleg_typ == "kassenbon":
        if found >= 3 and grounded_count >= 1:
            return "hoch"
        elif found >= 2:
            return "mittel"
        return "niedrig"

    # Standard-Logik für andere Belegtypen
    if found >= 4 and grounded_count >= 2:
        return "hoch"
    elif found >= 3:
        return "mittel"
    elif found >= 2:
        return "mittel"
    return "niedrig"


# ════════════════════════════════════════════
#  Ollama Extraction
# ════════════════════════════════════════════

async def extract_with_ollama(ocr_text: str, retry: bool = True) -> dict:
    """Extrahiert Daten via Ollama mit LLM-nativem Source Grounding."""
    prompt = f"{SYSTEM_PROMPT}\n{ONE_SHOT_EXAMPLE}\n{USER_PROMPT.format(text=ocr_text[:4000])}"

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2000}
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            logger.info(f"Ollama raw response length: {len(raw)}")

            data = _parse_json_from_llm(raw)

            # Retry einmal bei Parse-Fehler
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

            # Entpacke {wert, quelle}-Paare (tolerant bei flat responses)
            flat_data, source_quotes = _unwrap_sourced_response(data)
            flat_data = _clean_extracted_data(flat_data)

            # Primär: LLM-native Source Spans aus quelle-Feldern
            spans = _build_source_spans_from_quotes(ocr_text, source_quotes)
            grounded_fields = {s["feld"] for s in spans}

            logger.info(f"LLM source grounding: {len(spans)} spans from {len(source_quotes)} quotes")

            # Fallback: Post-hoc Matching für un-gegrundete Felder
            fallback_data = {k: v for k, v in flat_data.items() if k not in grounded_fields}
            if fallback_data:
                fallback_spans = _build_source_spans(ocr_text, fallback_data)
                spans.extend(fallback_spans)
                logger.info(f"Fallback grounding: {len(fallback_spans)} additional spans")

            return {
                "extrahierte_daten": flat_data,
                "quellreferenzen": spans,
                "methode": "ollama_direkt",
                "konfidenz": _assess_confidence(flat_data, spans)
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
#  Vision-LLM Dual-Pass (Qwen2.5-VL)
# ════════════════════════════════════════════

VISION_PROMPT = """Du siehst ein Foto eines deutschen Belegs (Kassenbon, Rechnung, Quittung).
Extrahiere die folgenden Felder als JSON. Nur Felder die du SICHER lesen kannst.
Unbekannte Felder: null.

Felder: aussteller, betrag_brutto (als Dezimalzahl z.B. 7.77), datum_beleg (TT.MM.JJJJ), mwst_satz, mwst_betrag, rechnungsnummer, beleg_typ (kassenbon|rechnung|bewirtungsbeleg|sonstig), beschreibung

Antworte NUR mit JSON, kein anderer Text."""


async def _vision_extract(image_path: str) -> Optional[dict]:
    """Extract data from document image using Vision-LLM (Qwen2.5-VL).

    Reads the original image, converts to base64, and sends to Ollama
    with the vision model. Returns parsed extraction dict or None on failure.
    """
    from backend.app.config import settings

    if not settings.vision_model:
        return None

    path = Path(image_path)
    if not path.exists():
        logger.warning(f"Vision: Image not found: {image_path}")
        return None

    # For PDFs, we'd need to convert to image first
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(path), dpi=200, first_page=1, last_page=1)
            if not images:
                return None
            import io
            buf = io.BytesIO()
            images[0].save(buf, format='JPEG', quality=85)
            img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        except Exception as e:
            logger.error(f"Vision: PDF to image failed: {e}")
            return None
    elif ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.webp'):
        with open(path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
    else:
        logger.warning(f"Vision: Unsupported file type: {ext}")
        return None

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json={
                "model": settings.vision_model,
                "prompt": VISION_PROMPT,
                "images": [img_b64],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1000}
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            logger.info(f"Vision response length: {len(raw)}")

            data = _parse_json_from_llm(raw)
            if data:
                # Clean the extracted data
                return _clean_extracted_data(data)

            logger.warning(f"Vision: Could not parse JSON: {raw[:200]}")
            return None

    except httpx.ConnectError:
        logger.warning(f"Vision model not reachable at {OLLAMA_URL}")
    except httpx.TimeoutException:
        logger.warning("Vision model timeout after 120s")
    except Exception as e:
        logger.warning(f"Vision extraction error: {e}")

    return None


def _merge_extractions(tesseract_data: dict, vision_data: dict) -> tuple:
    """Merge Tesseract-LLM extraction with Vision-LLM extraction.

    Strategy:
    - Fields only Vision has → adopt (fills gaps from bad OCR)
    - Fields only Tesseract has → keep (has source grounding)
    - Both have same value → confidence boost
    - Both have different values → prefer Tesseract (has source grounding)

    Returns:
        (merged_data, method_suffix) – e.g. ("vision_ergänzt", True)
    """
    if not vision_data:
        return tesseract_data, False

    merged = dict(tesseract_data)
    vision_filled = []

    # Key fields that Vision might fill
    key_fields = ["aussteller", "betrag_brutto", "datum_beleg", "mwst_satz",
                  "mwst_betrag", "rechnungsnummer", "beleg_typ", "beschreibung"]

    for field in key_fields:
        tess_val = tesseract_data.get(field)
        vis_val = vision_data.get(field)

        if vis_val is not None and tess_val is None:
            # Vision found what Tesseract missed → adopt
            merged[field] = vis_val
            vision_filled.append(field)
            logger.info(f"Vision filled '{field}': {vis_val}")

    if vision_filled:
        logger.info(f"Vision merge: filled {len(vision_filled)} fields: {vision_filled}")
        return merged, True

    return merged, False


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
    "kassenbon": ("4900", "Sonst. betriebl. Aufwend.", "2"),
}


def auto_kontierung(beleg_typ: str, mwst_satz: float = None) -> dict:
    """Auto-Kontierung: SKR03-Konto anhand Belegtyp zuweisen."""
    entry = KONTIERUNG_MAP.get(beleg_typ, ("4900", "Sonst. betriebl. Aufwend.", ""))
    bu = entry[2]
    if mwst_satz and not bu:
        bu = "3" if mwst_satz >= 15 else ("2" if mwst_satz >= 5 else "")
    return {"skr03_konto": entry[0], "skr03_bezeichnung": entry[1], "bu_schluessel": bu}


# ════════════════════════════════════════════
#  BBox Enrichment (Geometric Source Grounding)
# ════════════════════════════════════════════

def _enrich_spans_with_bboxes(spans: list, ocr_data: dict) -> list:
    """Enrich text-based source spans with geometric bounding boxes.

    For each span (identified by char_start/end), find all OCR words whose
    character range overlaps and compute the union bounding box.

    This enables the frontend to highlight the exact region on the
    original PDF/image where the extracted value appears.
    """
    if not ocr_data or "pages" not in ocr_data:
        return spans

    # Build flat list of all words across pages (already have global char offsets)
    all_words = []
    for page in ocr_data["pages"]:
        page_num = page.get("page", 1)
        for word in page.get("words", []):
            if "char_start" in word and "char_end" in word:
                all_words.append({**word, "page": page_num})

    if not all_words:
        return spans

    enriched = []
    for span in spans:
        span_start = span.get("start")
        span_end = span.get("end")

        if span_start is None or span_end is None:
            enriched.append(span)
            continue

        # Find all words overlapping with this span's character range
        matching_words = []
        for w in all_words:
            w_start = w["char_start"]
            w_end = w["char_end"]
            # Overlap check: ranges overlap if start < other_end AND end > other_start
            if w_start < span_end and w_end > span_start:
                matching_words.append(w)

        if matching_words:
            # Compute union bounding box
            min_x = min(w["x"] for w in matching_words)
            min_y = min(w["y"] for w in matching_words)
            max_right = max(w["x"] + w["w"] for w in matching_words)
            max_bottom = max(w["y"] + w["h"] for w in matching_words)
            page = matching_words[0]["page"]

            span_with_bbox = {
                **span,
                "bbox": {
                    "x": min_x,
                    "y": min_y,
                    "w": max_right - min_x,
                    "h": max_bottom - min_y,
                    "page": page,
                }
            }
            enriched.append(span_with_bbox)
            logger.debug(f"BBox for '{span.get('feld')}': page {page}, ({min_x},{min_y}) {max_right - min_x}x{max_bottom - min_y}")
        else:
            # No matching words → keep span without bbox (frontend falls back to text view)
            enriched.append(span)

    bbox_count = sum(1 for s in enriched if "bbox" in s)
    logger.info(f"BBox enrichment: {bbox_count}/{len(enriched)} spans got bounding boxes")
    return enriched


# ════════════════════════════════════════════
#  Main Entry Point
# ════════════════════════════════════════════

async def extract_beleg(ocr_text: str, ocr_data: dict = None,
                        ocr_conf: float = 100.0, image_path: str = None) -> dict:
    """Hauptfunktion: Extrahiert Belegdaten via Ollama + Auto-Kontierung.

    Bei schlechter OCR-Qualität wird ein zusätzlicher Vision-Pass gestartet,
    der das Originalbild direkt liest und fehlende Felder ergänzt.

    Args:
        ocr_text: Full OCR text
        ocr_data: Optional word-level geometry from OCR service
        ocr_conf: OCR confidence (0-100), triggers vision pass if low
        image_path: Path to original image (for vision pass)
    """
    from backend.app.config import settings

    result = await extract_with_ollama(ocr_text)

    data = result.get("extrahierte_daten", {})
    methode = result.get("methode", "ollama_direkt")

    # Vision Dual-Pass: bei schlechter OCR oder wenigen Kernfeldern
    key_fields_found = sum(1 for f in ["betrag_brutto", "aussteller", "datum_beleg"]
                          if data.get(f) is not None)
    needs_vision = (
        image_path and
        settings.vision_model and
        (ocr_conf < settings.vision_threshold or key_fields_found < 2)
    )

    if needs_vision:
        logger.info(f"Vision pass triggered: OCR conf={ocr_conf:.1f}%, "
                     f"key fields={key_fields_found}/3, threshold={settings.vision_threshold}%")
        vision_data = await _vision_extract(image_path)
        if vision_data:
            data, was_merged = _merge_extractions(data, vision_data)
            if was_merged:
                methode = "ollama_vision_merged"
                result["extrahierte_daten"] = data
                result["methode"] = methode

    # Auto-Kontierung falls nicht vom LLM geliefert
    if data.get("beleg_typ") and not data.get("skr03_konto"):
        mwst = None
        try:
            mwst = float(data.get("mwst_satz", 0))
        except (ValueError, TypeError):
            pass
        kont = auto_kontierung(data["beleg_typ"], mwst)
        data.update(kont)
        result["extrahierte_daten"] = data

    # Re-assess confidence after potential vision merge
    spans = result.get("quellreferenzen", [])
    result["konfidenz"] = _assess_confidence(data, spans)

    # Enrich source spans with bounding boxes from OCR geometry
    if ocr_data and spans:
        result["quellreferenzen"] = _enrich_spans_with_bboxes(spans, ocr_data)

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
