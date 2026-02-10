"""OCR Service – Tesseract-based German document OCR with word-level geometry."""
import os, logging
from pathlib import Path
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)
LANG = os.getenv("OCR_LANGUAGE", "deu")
PAGE_SEPARATOR = "\n\n--- Seite ---\n\n"


def process_file(file_path: str) -> dict:
    """Process a document file and return OCR text, word geometry, and confidence.

    Returns:
        dict with keys:
            text (str): Full reconstructed OCR text
            data (dict): {pages: [{page, width, height, words: [{x,y,w,h,text,conf,char_start,char_end}]}]}
            conf (float): Average confidence (0-100)
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return _ocr_pdf(file_path)
    elif ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"):
        return _ocr_image(file_path)
    raise ValueError(f"Unsupported file type: {ext}")


def _extract_page(img: Image.Image, page_num: int) -> dict:
    """Run image_to_data on a single page/image, return structured word data.

    Returns:
        dict with keys:
            page_data: {page, width, height, words: [...]}
            text: reconstructed text for this page
            confs: list of confidence values (> 0)
    """
    data = pytesseract.image_to_data(img, lang=LANG, output_type=pytesseract.Output.DICT)
    width, height = img.size

    # Group words by (block_num, line_num) to reconstruct text with proper spacing
    words = []
    lines: dict[tuple[int, int], list[dict]] = {}

    n = len(data["text"])
    for i in range(n):
        txt = data["text"][i].strip()
        if not txt:
            continue
        conf = int(data["conf"][i])
        word = {
            "text": txt,
            "x": int(data["left"][i]),
            "y": int(data["top"][i]),
            "w": int(data["width"][i]),
            "h": int(data["height"][i]),
            "conf": conf,
        }
        block = int(data["block_num"][i])
        line = int(data["line_num"][i])
        key = (block, line)
        if key not in lines:
            lines[key] = []
        lines[key].append(word)
        words.append(word)

    # Reconstruct text and assign char_start / char_end
    char_offset = 0
    text_parts = []
    prev_block = None

    for key in sorted(lines.keys()):
        block, line = key
        # Insert block separator (extra newline between blocks)
        if prev_block is not None and block != prev_block:
            text_parts.append("\n")
            char_offset += 1
        prev_block = block

        line_words = lines[key]
        for j, w in enumerate(line_words):
            if j > 0:
                # Space between words on same line
                text_parts.append(" ")
                char_offset += 1
            w["char_start"] = char_offset
            w["char_end"] = char_offset + len(w["text"])
            char_offset = w["char_end"]
            text_parts.append(w["text"])

        # Newline at end of line
        text_parts.append("\n")
        char_offset += 1

    page_text = "".join(text_parts).rstrip("\n")
    confs = [w["conf"] for w in words if w["conf"] > 0]

    page_data = {
        "page": page_num,
        "width": width,
        "height": height,
        "words": words,
    }

    return {"page_data": page_data, "text": page_text, "confs": confs}


def _ocr_image(path: str) -> dict:
    """OCR a single image file."""
    img = Image.open(path)
    result = _extract_page(img, page_num=1)
    avg = sum(result["confs"]) / len(result["confs"]) if result["confs"] else 0.0

    return {
        "text": result["text"],
        "data": {"pages": [result["page_data"]]},
        "conf": round(avg, 2),
    }


def _ocr_pdf(path: str) -> dict:
    """OCR a multi-page PDF file."""
    images = convert_from_path(path, dpi=300)
    all_pages = []
    all_texts = []
    all_confs = []
    global_char_offset = 0

    for idx, img in enumerate(images):
        result = _extract_page(img, page_num=idx + 1)

        # Adjust char_start/char_end for global offset across pages
        if global_char_offset > 0:
            for w in result["page_data"]["words"]:
                w["char_start"] += global_char_offset
                w["char_end"] += global_char_offset

        all_pages.append(result["page_data"])
        all_texts.append(result["text"])
        all_confs.extend(result["confs"])

        # Update global offset: page text length + separator length
        global_char_offset += len(result["text"]) + len(PAGE_SEPARATOR)

    full_text = PAGE_SEPARATOR.join(all_texts)
    avg = sum(all_confs) / len(all_confs) if all_confs else 0.0

    return {
        "text": full_text,
        "data": {"pages": all_pages},
        "conf": round(avg, 2),
    }
