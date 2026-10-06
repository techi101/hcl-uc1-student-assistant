"""OCR for scanned PDF pages (no text layer). Owner: A.
rapidocr (ONNX) = pure pip install, works in Docker, no Tesseract binary needed."""
# WHAT THIS FILE IS: the "eyes" for scanned PDFs. Some PDFs are just photos of paper pages, so there is
# no text inside to copy. OCR (Optical Character Recognition) looks at the page picture and reads the letters.
# Real example: a scanned notice page has no text layer, so retrieval.extract_pages calls ocr_pdf_page(path, 0).
# We draw the page as an image at 2x size (bigger letters read better), rapidocr reads it, and we save the
# text in storage/ocr_cache/, so after a restart the same page is read from disk in a blink instead of ~10 s.
# ONNX = a standard file format for AI models; "onnxruntime" runs them on a normal CPU with no GPU.
# logging = writes warnings to the server log (team rule: logging, not print, in app code).
import logging
# lru_cache = remembers a function's result, so calling it again returns the saved result instead of redoing it.
from functools import lru_cache

# log = this file's own logger.
log = logging.getLogger(__name__)


# IN: nothing  ->  OUT: the RapidOCR reader object (the loaded OCR model).
# WHY: loading the model is slow. @lru_cache(maxsize=1) keeps the first one, so we load it only ONCE per run.
# The import is inside the function so the server starts fast and only loads OCR if a scanned page appears.
@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


# IN: PDF file path + page number (0 = first page) + zoom (2.0 = draw page at double size)
#  ->  OUT: the text read from that page ("" if nothing could be read).
# WHY the disk cache: OCR takes about 10 s per page on a CPU. Re-ingesting after a restart should be instant.
# Example: page 3 (page_index 2) of a file whose hash starts "a1b2..." is saved as storage/ocr_cache/a1b2..._p3.txt
def ocr_pdf_page(pdf_path: str, page_index: int, scale: float = 2.0) -> str:
    """OCR one page, cached on disk by file hash + page (OCR is ~10 s/page on CPU; re-ingest should be instant)."""
    # hashlib = makes a "fingerprint" (hash) of the file. Same bytes -> same fingerprint.
    import hashlib
    # STORAGE = our git-ignored storage/ folder (set in app/config.py).
    from app.config import STORAGE
    # Fingerprint the whole PDF with SHA-256 and keep the first 16 characters as a short name.
    # WHY a hash and not the file name: if someone uploads a NEW version with the same name, the hash changes,
    # so we never reuse old text for a changed file.
    sha = hashlib.sha256(open(pdf_path, "rb").read()).hexdigest()[:16]
    # Cache file name = fingerprint + human page number (page_index 0 -> "_p1").
    cache = STORAGE / "ocr_cache" / f"{sha}_p{page_index + 1}.txt"
    # Already read before? Return the saved text and skip OCR completely.
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    # Not cached: do the real (slow) OCR.
    text = _ocr(pdf_path, page_index, scale)
    # Save only if we got some text. An empty result is not saved, so a failed page is retried next time.
    # mkdir(parents=True, exist_ok=True) = create the folder if missing, no error if it already exists.
    if text:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return text


# IN: PDF path + page number + zoom  ->  OUT: page text with one line per row of the page ("" on any error).
# Example: a table row "Roll No   Name   Attendance" is found by OCR as 3 separate boxes; we join them
# into one line "Roll No  Name  Attendance" because the boxes sit at the same height.
def _ocr(pdf_path: str, page_index: int, scale: float) -> str:
    """Render one page to an image and read its text, top-to-bottom. Returns '' on failure."""
    try:
        # numpy = number arrays (the OCR model wants the image as a grid of pixel numbers).
        # pypdfium2 = opens a PDF and draws (renders) a page as a picture.
        import numpy as np
        import pypdfium2 as pdfium
        # Open the PDF, draw the chosen page at "scale" size, turn it into an RGB colour picture,
        # then into a numpy pixel grid. Close the PDF so the file is not left locked (matters on Windows).
        pdf = pdfium.PdfDocument(pdf_path)
        img = np.array(pdf[page_index].render(scale=scale).to_pil().convert("RGB"))
        pdf.close()
        # Run the OCR model on the picture. It returns (result, timing); we do not need the timing, so "_".
        result, _ = _engine()(img)
        # Nothing found on the page (blank or unreadable) -> empty text.
        if not result:
            return ""
        # result = [[box, text, conf], ...]; sort by top y then x so table rows read left-to-right
        # box = the 4 corner points of where the text sits; box[0] = top-left corner = (x, y).
        # conf = how sure the model is (0 to 1). We sort by: rounded height first, then left-to-right position.
        # WHY divide y by 15 and round: words on the same printed line can differ by a few pixels in height.
        # Putting heights into 15-pixel "bands" treats y=301 and y=306 as the same line (301/15 = 20.07 and
        # 306/15 = 20.4, both round to 20), while y=330 (330/15 = 22) starts a new line.
        rows = sorted(result, key=lambda r: (round(r[0][0][1] / 15), r[0][0][0]))
        # lines = finished lines of text; last_y = band of the previous box; cur = boxes on the current line.
        lines, last_y, cur = [], None, []
        for box, text, conf in rows:
            y = round(box[0][1] / 15)
            # This box is in a new band (a lower line): finish the current line, join its pieces with 2 spaces.
            if last_y is not None and y != last_y:
                lines.append("  ".join(cur))
                cur = []
            cur.append(text)
            last_y = y
        # Do not forget the very last line after the loop ends.
        if cur:
            lines.append("  ".join(cur))
        # Join all lines with newlines into one page of text.
        return "\n".join(lines)
    # Any error (bad PDF, missing package, model problem): log a warning and return "" so ingestion goes on
    # with the other pages instead of crashing.
    except Exception as e:
        log.warning("OCR failed for %s page %d: %s", pdf_path, page_index + 1, e)
        return ""
