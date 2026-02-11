"""OCR Service – Tesseract-based German document OCR with word-level geometry."""
import os, logging
from pathlib import Path
import pytesseract
from PIL import Image, ImageOps, ImageFilter
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


def _preprocess_image(img: Image.Image) -> Image.Image:
    """Preprocess image for better OCR on thermal receipts and low-quality scans.

    Steps:
    1. Grayscale conversion
    2. Auto-contrast (boosts faded thermal paper)
    3. Upscale small images (phone photos of receipts)
    4. Sharpen edges
    5. Binarize (clean black/white for Tesseract)
    """
    # 1. Grayscale
    if img.mode != 'L':
        img = img.convert('L')

    # 2. Auto-contrast: stretches histogram, great for faded thermal paper
    img = ImageOps.autocontrast(img, cutoff=2)

    # 3. Upscale small images (phone photos of receipts are often small)
    w, h = img.size
    if w < 1500:
        scale = 2
        img = img.resize((w * scale, h * scale), Image.LANCZOS)
        logger.info(f"Upscaled image from {w}x{h} to {w*scale}x{h*scale}")

    # 4. Sharpen (one pass – sharpens text edges)
    img = img.filter(ImageFilter.SHARPEN)

    # 5. Binarize: threshold at 140 – forces clean B&W (Tesseract loves this)
    img = img.point(lambda x: 255 if x > 140 else 0, '1')
    img = img.convert('L')  # back to grayscale for Tesseract

    return img


def _extract_page(img: Image.Image, page_num: int) -> dict:
    """Run image_to_data on a single page/image, return structured word data.

    Returns:
        dict with keys:
            page_data: {page, width, height, words: [...]}
            text: reconstructed text for this page
            confs: list of confidence values (> 0)
    """
    # Store original dimensions (for bbox mapping to original image)
    orig_width, orig_height = img.size

    # Preprocess for better OCR quality
    processed = _preprocess_image(img)
    data = pytesseract.image_to_data(processed, lang=LANG, output_type=pytesseract.Output.DICT)

    # Use original image dimensions for bbox coordinates
    # Scale factor if image was upscaled during preprocessing
    proc_width, proc_height = processed.size
    scale_x = orig_width / proc_width
    scale_y = orig_height / proc_height
    width, height = orig_width, orig_height

    # Group words by (block_num, line_num) to reconstruct text with proper spacing
    words = []
    lines: dict[tuple[int, int], list[dict]] = {}

    n = len(data["text"])
    for i in range(n):
        txt = data["text"][i].strip()
        if not txt:
            continue
        conf = int(data["conf"][i])
        # Scale coordinates back to original image dimensions
        word = {
            "text": txt,
            "x": int(data["left"][i] * scale_x),
            "y": int(data["top"][i] * scale_y),
            "w": int(data["width"][i] * scale_x),
            "h": int(data["height"][i] * scale_y),
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
