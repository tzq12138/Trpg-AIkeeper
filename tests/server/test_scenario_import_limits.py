import pytest

from src.server.scenario.import_service import (
    ScenarioImportFailure,
    ScenarioImportService,
    UploadedSource,
)


def test_default_import_limit_rejects_an_oversized_source():
    service = ScenarioImportService(None, max_file_bytes=4, max_total_bytes=8)

    with pytest.raises(ScenarioImportFailure, match="文件过大"):
        service._validate_sources(
            [UploadedSource(filename="large.pdf", content=b"12345")],
            "authorized",
        )


def test_golden_import_limit_accepts_a_larger_source_without_relaxing_default():
    service = ScenarioImportService(None, max_file_bytes=8, max_total_bytes=12)

    service._validate_sources(
        [UploadedSource(filename="large.pdf", content=b"12345678")],
        "authorized",
    )
