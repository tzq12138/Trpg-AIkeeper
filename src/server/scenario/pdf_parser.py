import logging

logger = logging.getLogger(__name__)


class PDFPage:
    def __init__(self, page_num: int, text: str):
        self.page_num = page_num
        self.text = text


def extract_text_from_pdf(pdf_path: str) -> list[PDFPage]:
    try:
        pages = _extract_pdfplumber(pdf_path)
        logger.info("PDF extracted with pdfplumber: %s pages from %s", len(pages), pdf_path)
        return pages
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("pdfplumber extraction failed for %s: %s", pdf_path, exc)
    try:
        pages = _extract_pypdf(pdf_path)
        logger.info("PDF extracted with pypdf: %s pages from %s", len(pages), pdf_path)
        return pages
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("pypdf extraction failed for %s: %s", pdf_path, exc)
    logger.error("PDF extraction failed (both libraries): %s", pdf_path)
    return []


def _extract_pdfplumber(pdf_path: str) -> list[PDFPage]:
    import pdfplumber

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append(PDFPage(page_num=i + 1, text=text))
    return pages


def _extract_pypdf(pdf_path: str) -> list[PDFPage]:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(PDFPage(page_num=i + 1, text=text))
    return pages


def is_scanned_pdf(pages: list[PDFPage]) -> bool:
    if not pages:
        return False
    total_chars = sum(len(p.text.strip()) for p in pages)
    return total_chars < 50


def chunk_text(pages: list[PDFPage], max_chars: int = 2000) -> list[dict]:
    chunks = []
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        for i in range(0, len(text), max_chars):
            chunks.append({
                "page": page.page_num,
                "text": text[i : i + max_chars],
                "offset": i,
            })
    return chunks
