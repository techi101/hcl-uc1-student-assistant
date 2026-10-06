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
    """Render one page to an image and read its text, top-to-bottom. Returns '' on failure."""
    try:
        import numpy as np
        import pypdfium2 as pdfium
        page = pdfium.PdfDocument(pdf_path)[page_index]
        img = np.array(page.render(scale=scale).to_pil().convert("RGB"))
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
