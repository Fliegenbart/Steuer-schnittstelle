"""OCR Service – Tesseract-based German document OCR."""
import os, logging
from pathlib import Path
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)
LANG = os.getenv("OCR_LANGUAGE", "deu")


def process_file(file_path: str) -> tuple[str, float]:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return _ocr_pdf(file_path)
    elif ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"):
        return _ocr_image(file_path)
    raise ValueError(f"Unsupported: {ext}")


def _ocr_image(path: str) -> tuple[str, float]:
    img = Image.open(path)
    data = pytesseract.image_to_data(img, lang=LANG, output_type=pytesseract.Output.DICT)
    confs = [int(c) for c in data["conf"] if int(c) > 0]
    avg = sum(confs) / len(confs) if confs else 0.0
    text = pytesseract.image_to_string(img, lang=LANG)
    return text.strip(), round(avg, 2)


def _ocr_pdf(path: str) -> tuple[str, float]:
    images = convert_from_path(path, dpi=300)
    texts, confs = [], []
    for img in images:
        data = pytesseract.image_to_data(img, lang=LANG, output_type=pytesseract.Output.DICT)
        confs.extend([int(c) for c in data["conf"] if int(c) > 0])
        texts.append(pytesseract.image_to_string(img, lang=LANG).strip())
    full = "\n\n--- Seite ---\n\n".join(texts)
    avg = sum(confs) / len(confs) if confs else 0.0
    return full, round(avg, 2)
