from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from src.server.scenario import content_package
from src.server.scenario.content_package import (
    ContentPackageError,
    build_content_package,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_ASSET_DIR = ROOT / "data" / "test_assets" / "最小测试模块"
PNG_ASSET = TEST_ASSET_DIR / "Along Against the Flames" / "三角.png"
PDF_ASSET = TEST_ASSET_DIR / "向火独行.pdf"


def test_build_content_package_for_native_pdf_uses_text_parts_and_stable_sha256():
    content = PDF_ASSET.read_bytes()
    package = build_content_package(str(PDF_ASSET), content)

    assert package.source_filename == PDF_ASSET.name
    assert package.source_sha256 == hashlib.sha256(content).hexdigest()
    assert package.mime_type == "application/pdf"
    assert package.requires_multimodal is False
    assert package.canonical_text.strip()
    assert package.parts
    assert all(part.kind == "text" for part in package.parts)
    assert all(part.page_number is not None for part in package.parts)
    assert all(part.source_ref.startswith("page:") for part in package.parts)


def test_build_content_package_for_blank_pdf_falls_back_to_multimodal_images():
    content = _build_blank_pdf_bytes()
    package = build_content_package("blank.pdf", content)

    assert package.mime_type == "application/pdf"
    assert package.requires_multimodal is True
    assert package.canonical_text == ""
    assert len(package.parts) == 1
    assert package.parts[0].kind == "image"
    assert package.parts[0].data_url.startswith("data:image/png;base64,")
    assert package.parts[0].page_number == 1


def test_build_content_package_for_png_emits_single_data_url_image():
    content = PNG_ASSET.read_bytes()
    package = build_content_package(str(PNG_ASSET), content)

    assert package.mime_type == "image/png"
    assert package.requires_multimodal is True
    assert package.canonical_text == ""
    assert len(package.parts) == 1
    assert package.parts[0].kind == "image"
    assert package.parts[0].data_url.startswith("data:image/png;base64,")
    assert package.parts[0].source_ref == "inline"


def test_build_content_package_for_docx_extracts_text_and_media():
    content = _build_minimal_docx_bytes()
    package = build_content_package("sample.docx", content)

    assert package.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert package.source_filename == "sample.docx"
    assert package.canonical_text.strip() == "Hello DOCX"
    assert any(part.kind == "text" and part.text == "Hello DOCX" for part in package.parts)
    assert any(part.kind == "image" and part.data_url.startswith("data:image/png;base64,") for part in package.parts)


def test_build_content_package_rejects_zip_bomb_like_docx():
    content = _build_oversized_docx_zip_bytes()

    with pytest.raises(ContentPackageError):
        build_content_package("bomb.docx", content)


def test_to_provider_payload_is_json_serializable_and_does_not_leak_paths():
    content = PDF_ASSET.read_bytes()
    package = build_content_package(str(PDF_ASSET), content)

    payload = package.to_provider_payload()
    json.dumps(payload, ensure_ascii=False)

    flattened = _collect_strings(payload)
    forbidden = {str(ROOT).lower(), str(PDF_ASSET.parent).lower(), str(PDF_ASSET).lower()}
    assert "storage_path" not in json.dumps(payload, ensure_ascii=False)
    assert all(not value.lower().startswith("c:\\") for value in flattened if value)
    assert all(not any(marker in value.lower() for marker in forbidden) for value in flattened if value)


def test_to_provider_payload_sanitizes_path_metadata_recursively():
    package = build_content_package("pixel.png", base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO8L5m0AAAAASUVORK5CYII="
    ))
    package.metadata = {
        "storage_path": "C:\\secret\\source.png",
        "nested": {"absolute_path": "C:\\secret\\nested.png", "label": "safe"},
    }
    package.parts[0].metadata = {"local_path": "C:\\secret\\part.png"}

    payload = package.to_provider_payload()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "C:\\\\secret" not in serialized
    assert "storage_path" not in serialized
    assert "absolute_path" not in serialized
    assert "local_path" not in serialized
    assert payload["metadata"]["nested"]["label"] == "safe"


def test_build_content_package_wraps_malformed_docx_as_domain_error():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document>")

    with pytest.raises(ContentPackageError):
        build_content_package("broken.docx", buffer.getvalue())


def test_build_content_package_for_legacy_doc_uses_converter_and_preserves_original_hash(monkeypatch):
    original = b"legacy-doc-source"
    converted_pdf = _build_blank_pdf_bytes()
    monkeypatch.setattr(
        content_package,
        "_convert_legacy_doc_to_pdf",
        lambda filename, content: converted_pdf,
    )

    package = build_content_package("scan.doc", original)

    assert package.source_filename == "scan.doc"
    assert package.source_sha256 == hashlib.sha256(original).hexdigest()
    assert package.mime_type == "application/msword"
    assert package.requires_multimodal is True
    assert package.metadata["conversion"] == "legacy_doc_to_pdf"
    assert package.parts[0].source_ref == "page:1"


def _build_blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _build_minimal_docx_bytes() -> bytes:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO8L5m0AAAAASUVORK5CYII="
    )
    document_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body>
    <w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p>
  </w:body>
</w:document>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Default Extension='png' ContentType='image/png'/>
  <Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>
</Types>
""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/>
</Relationships>
""",
        )
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/media/image1.png", png_bytes)
    return buffer.getvalue()


def _build_oversized_docx_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(1001):
            archive.writestr(f"word/media/image{index}.bin", b"x")
    return buffer.getvalue()


def _collect_strings(value):
    collected = []
    if isinstance(value, dict):
        for item in value.values():
            collected.extend(_collect_strings(item))
    elif isinstance(value, list):
        for item in value:
            collected.extend(_collect_strings(item))
    elif isinstance(value, tuple):
        for item in value:
            collected.extend(_collect_strings(item))
    elif isinstance(value, str):
        collected.append(value)
    return collected
