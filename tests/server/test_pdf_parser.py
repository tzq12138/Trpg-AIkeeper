from src.server.pdf_parser import extract_text_from_pdf, is_scanned_pdf, chunk_text, PDFPage


def test_extract_text_returns_list():
    result = extract_text_from_pdf("/nonexistent.pdf")
    assert isinstance(result, list)


def test_is_scanned_pdf_empty():
    assert is_scanned_pdf([]) is False


def test_is_scanned_pdf_with_few_chars():
    pages = [PDFPage(1, "  ")]
    assert is_scanned_pdf(pages) is True


def test_is_scanned_pdf_with_text():
    pages = [PDFPage(1, "This is a real page with lots of text content for testing purposes")]
    assert is_scanned_pdf(pages) is False


def test_chunk_text():
    pages = [PDFPage(1, "A" * 5000)]
    chunks = chunk_text(pages, max_chars=2000)
    assert len(chunks) == 3
    assert chunks[0]["page"] == 1
    assert chunks[0]["offset"] == 0
    assert chunks[1]["offset"] == 2000


def test_chunk_text_empty_pages():
    pages = [PDFPage(1, "")]
    chunks = chunk_text(pages)
    assert len(chunks) == 0
