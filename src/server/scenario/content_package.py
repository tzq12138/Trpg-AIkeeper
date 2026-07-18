from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pdfplumber

from .pdf_parser import PDFPage, is_scanned_pdf

MAX_ZIP_ENTRIES = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 25 * 1024 * 1024

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOC_MIME = "application/msword"
_PDF_MIME = "application/pdf"
_SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ContentPackageError(Exception):
    pass


@dataclass(slots=True)
class ContentPart:
    ordinal: int
    kind: str
    text: str = ""
    mime_type: str = ""
    page_number: int | None = None
    data_url: str = ""
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "kind": self.kind,
            "text": self.text,
            "mime_type": self.mime_type,
            "page_number": self.page_number,
            "data_url": self.data_url,
            "source_ref": self.source_ref,
            "metadata": _copy_metadata(self.metadata),
        }


@dataclass(slots=True)
class ContentPackage:
    source_filename: str
    source_sha256: str
    mime_type: str
    parts: list[ContentPart]
    canonical_text: str
    requires_multimodal: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "source_filename": self.source_filename,
            "source_sha256": self.source_sha256,
            "mime_type": self.mime_type,
            "parts": [part.to_provider_payload() for part in self.parts],
            "canonical_text": self.canonical_text,
            "requires_multimodal": self.requires_multimodal,
            "metadata": _copy_metadata(self.metadata),
        }


def build_content_package(filename: str, content: bytes, declared_mime: str = "") -> ContentPackage:
    source_filename = Path(filename).name
    source_sha256 = hashlib.sha256(content).hexdigest()
    mime_type = _resolve_mime_type(filename, declared_mime)

    if mime_type == _PDF_MIME:
        return _build_pdf_package(source_filename, source_sha256, content)
    if mime_type in _SUPPORTED_IMAGE_MIMES:
        return _build_image_package(source_filename, source_sha256, content, mime_type)
    if mime_type == _DOCX_MIME:
        return _build_docx_package(source_filename, source_sha256, content)
    if mime_type == _DOC_MIME:
        converted_pdf = _convert_legacy_doc_to_pdf(source_filename, content)
        package = _build_pdf_package(source_filename, source_sha256, converted_pdf)
        package.mime_type = _DOC_MIME
        package.metadata["conversion"] = "legacy_doc_to_pdf"
        package.metadata["converted_mime_type"] = _PDF_MIME
        return package

    raise ContentPackageError(f"Unsupported content type: {mime_type or filename}")


def _convert_legacy_doc_to_pdf(filename: str, content: bytes) -> bytes:
    try:
        import win32com.client
    except ImportError as exc:
        raise ContentPackageError("旧 DOC 转换器不可用") from exc

    with tempfile.TemporaryDirectory(prefix="aikeeper-doc-") as directory:
        source_path = Path(directory) / Path(filename).with_suffix(".doc").name
        output_path = Path(directory) / "converted.pdf"
        source_path.write_bytes(content)
        application = None
        document = None
        try:
            application = win32com.client.DispatchEx("Word.Application")
            application.Visible = False
            application.DisplayAlerts = 0
            document = application.Documents.Open(str(source_path))
            document.SaveAs(str(output_path), FileFormat=17)
            if not output_path.is_file() or not output_path.stat().st_size:
                raise ContentPackageError("旧 DOC 转换未生成 PDF")
            return output_path.read_bytes()
        except ContentPackageError:
            raise
        except Exception as exc:
            raise ContentPackageError("旧 DOC 转换失败") from exc
        finally:
            if document is not None:
                try:
                    document.Close(False)
                except Exception:
                    pass
            if application is not None:
                try:
                    application.Quit()
                except Exception:
                    pass


def _build_pdf_package(source_filename: str, source_sha256: str, content: bytes) -> ContentPackage:
    pages = _extract_pdf_pages(content)
    if not pages:
        raise ContentPackageError("PDF contains no pages")

    if is_scanned_pdf(pages):
        parts = [
            ContentPart(
                ordinal=index,
                kind="image",
                mime_type="image/png",
                data_url=_render_pdf_page_as_data_url(content, page.page_num),
                page_number=page.page_num,
                source_ref=f"page:{page.page_num}",
            )
            for index, page in enumerate(pages, start=1)
        ]
        return ContentPackage(
            source_filename=source_filename,
            source_sha256=source_sha256,
            mime_type=_PDF_MIME,
            parts=parts,
            canonical_text="",
            requires_multimodal=True,
        )

    parts = [
        ContentPart(
            ordinal=index,
            kind="text",
            text=page.text.strip(),
            page_number=page.page_num,
            source_ref=f"page:{page.page_num}",
        )
        for index, page in enumerate(pages, start=1)
        if page.text.strip()
    ]
    canonical_text = "\n".join(part.text for part in parts if part.text).strip()
    return ContentPackage(
        source_filename=source_filename,
        source_sha256=source_sha256,
        mime_type=_PDF_MIME,
        parts=parts,
        canonical_text=canonical_text,
        requires_multimodal=False,
    )


def _build_image_package(
    source_filename: str,
    source_sha256: str,
    content: bytes,
    mime_type: str,
) -> ContentPackage:
    return ContentPackage(
        source_filename=source_filename,
        source_sha256=source_sha256,
        mime_type=mime_type,
        parts=[
            ContentPart(
                ordinal=1,
                kind="image",
                mime_type=mime_type,
                data_url=_bytes_to_data_url(content, mime_type),
                source_ref="inline",
            )
        ],
        canonical_text="",
        requires_multimodal=True,
    )


def _build_docx_package(source_filename: str, source_sha256: str, content: bytes) -> ContentPackage:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            _validate_zip_limits(archive)
            text_parts, image_parts = _extract_docx_parts(archive)
    except ContentPackageError:
        raise
    except Exception as exc:
        raise ContentPackageError("DOCX parsing failed") from exc

    parts = text_parts + image_parts
    canonical_text = "\n".join(part.text for part in text_parts if part.text).strip()
    return ContentPackage(
        source_filename=source_filename,
        source_sha256=source_sha256,
        mime_type=_DOCX_MIME,
        parts=parts,
        canonical_text=canonical_text,
        requires_multimodal=bool(image_parts),
    )


def _extract_pdf_pages(content: bytes) -> list[PDFPage]:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [
            PDFPage(page_num=index + 1, text=_extract_pdf_page_text(page))
            for index, page in enumerate(pdf.pages)
        ]


def _extract_pdf_page_text(page) -> str:
    words = page.extract_words()
    if not _has_overlapping_columns(page, words):
        return _strip_pdf_page_chrome(page.extract_text() or "")

    midpoint = float(page.width) / 2
    left_text = page.crop((0, 0, midpoint, page.height)).extract_text() or ""
    right_text = page.crop((midpoint, 0, page.width, page.height)).extract_text() or ""
    return _strip_pdf_page_chrome(
        "\n".join(part for part in (left_text, right_text) if part)
    )


def _strip_pdf_page_chrome(text: str) -> str:
    lines = []
    for line in text.splitlines():
        normalized = line.strip().upper()
        if re.fullmatch(r"[IVXLCDM]+", normalized):
            continue
        if re.fullmatch(r"[A-Z ]+", normalized) and (
            "ALONE" in normalized or "FLAMES" in normalized
        ):
            continue
        lines.append(line)
    return "\n".join(lines)


def _has_overlapping_columns(page, words: list[dict[str, Any]]) -> bool:
    if len(words) < 24:
        return False

    midpoint = float(page.width) / 2
    gutter = max(6.0, float(page.width) * 0.015)
    left_tops = [float(word["top"]) for word in words if float(word["x0"]) < midpoint - gutter]
    right_tops = [float(word["top"]) for word in words if float(word["x0"]) > midpoint + gutter]
    if len(left_tops) < 12 or len(right_tops) < 12:
        return False

    overlap = min(max(left_tops), max(right_tops)) - max(min(left_tops), min(right_tops))
    return overlap >= float(page.height) * 0.25


def _render_pdf_page_as_data_url(content: bytes, page_number: int) -> str:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page = pdf.pages[page_number - 1]
        page_image = page.to_image(resolution=144)
        buffer = io.BytesIO()
        page_image.original.save(buffer, format="PNG")
        return _bytes_to_data_url(buffer.getvalue(), "image/png")


def _extract_docx_parts(archive: zipfile.ZipFile) -> tuple[list[ContentPart], list[ContentPart]]:
    text_parts: list[ContentPart] = []
    image_parts: list[ContentPart] = []

    if "word/document.xml" in archive.namelist():
        document_xml = ET.fromstring(archive.read("word/document.xml"))
        paragraphs: list[str] = []
        for paragraph in document_xml.findall(f".//{_W_NS}p"):
            text = "".join(node.text or "" for node in paragraph.findall(f".//{_W_NS}t")).strip()
            if text:
                paragraphs.append(text)
        for index, paragraph_text in enumerate(paragraphs, start=1):
            text_parts.append(
                ContentPart(
                    ordinal=index,
                    kind="text",
                    text=paragraph_text,
                    source_ref=f"paragraph:{index}",
                )
            )

    image_index = len(text_parts)
    for name in sorted(archive.namelist()):
        if not name.startswith("word/media/"):
            continue
        mime_type = _guess_image_mime_type(name)
        if mime_type is None:
            continue
        image_index += 1
        image_parts.append(
            ContentPart(
                ordinal=image_index,
                kind="image",
                mime_type=mime_type,
                data_url=_bytes_to_data_url(archive.read(name), mime_type),
                source_ref=name,
            )
        )

    return text_parts, image_parts


def _validate_zip_limits(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        raise ContentPackageError("ZIP entry count exceeds limit")

    total_uncompressed = 0
    for entry in entries:
        total_uncompressed += entry.file_size
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ContentPackageError("ZIP uncompressed size exceeds limit")


def _resolve_mime_type(filename: str, declared_mime: str) -> str:
    normalized_declared = (declared_mime or "").strip().lower()
    if normalized_declared:
        if normalized_declared in {_PDF_MIME, _DOCX_MIME, _DOC_MIME, *_SUPPORTED_IMAGE_MIMES}:
            return normalized_declared
        if normalized_declared.startswith("image/"):
            return normalized_declared

    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        return _PDF_MIME
    if extension == ".docx":
        return _DOCX_MIME
    if extension == ".doc":
        return _DOC_MIME
    if extension in {".png"}:
        return "image/png"
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"

    guessed = mimetypes.guess_type(filename)[0]
    if guessed:
        return guessed.lower()
    return normalized_declared


def _bytes_to_data_url(content: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"


def _guess_image_mime_type(filename: str) -> str | None:
    extension = Path(filename).suffix.lower()
    if extension == ".png":
        return "image/png"
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"
    return None


_PATH_METADATA_KEYS = {
    "absolute_path",
    "local_path",
    "original_file_path",
    "relative_path",
    "storage_path",
}


def _copy_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return _sanitize_metadata_value(metadata) if metadata else {}


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_metadata_value(item)
            for key, item in value.items()
            if key.lower() not in _PATH_METADATA_KEYS
            and not key.lower().endswith("_path")
        }
    if isinstance(value, list):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, str) and _looks_like_local_path(value):
        return ""
    return value


def _looks_like_local_path(value: str) -> bool:
    stripped = value.strip()
    return bool(
        re.match(r"^[A-Za-z]:[\\/]", stripped)
        or stripped.startswith(("/", "\\\\", "file://"))
    )
