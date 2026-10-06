"""OCR for scanned PDF pages (no text layer). Owner: A.
rapidocr (ONNX) = pure pip install, works in Docker, no Tesseract binary needed."""
import logging
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def ocr_pdf_page(pdf_path: str, page_index: int, scale: float = 2.0) -> str:
    """OCR one page, cached on disk by file hash + page (OCR is ~10 s/page on CPU; re-ingest should be instant)."""
    import hashlib
    from app.config import STORAGE
    sha = hashlib.sha256(open(pdf_path, "rb").read()).hexdigest()[:16]
    cache = STORAGE / "ocr_cache" / f"{sha}_p{page_index + 1}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    text = _ocr(pdf_path, page_index, scale)
    if text:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return text


def _ocr(pdf_path: str, page_index: int, scale: float) -> str:
    """Render one page to an image and read its text, top-to-bottom. Returns '' on failure."""
    try:
        import numpy as np
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_path)
        img = np.array(pdf[page_index].render(scale=scale).to_pil().convert("RGB"))
        pdf.close()
        result, _ = _engine()(img)
        if not result:
            return ""
        # result = [[box, text, conf], ...]; sort by top y then x so table rows read left-to-right
        rows = sorted(result, key=lambda r: (round(r[0][0][1] / 15), r[0][0][0]))
        lines, last_y, cur = [], None, []
        for box, text, conf in rows:
            y = round(box[0][1] / 15)
            if last_y is not None and y != last_y:
                lines.append("  ".join(cur))
                cur = []
            cur.append(text)
            last_y = y
        if cur:
            lines.append("  ".join(cur))
        return "\n".join(lines)
    except Exception as e:
        log.warning("OCR failed for %s page %d: %s", pdf_path, page_index + 1, e)
        return ""
