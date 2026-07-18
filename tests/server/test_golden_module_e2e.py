import io
import zipfile

from src.server.scenario.golden_suite import GoldenModuleSpec
from scripts.run_golden_module_suite import GoldenModuleSuiteRunner


def test_runner_imports_runs_and_ends_a_module_through_official_routes(
    client, test_db, tmp_path
):
    source = tmp_path / "module.docx"
    source.write_bytes(_minimal_docx("钟楼大厅。黑色钥匙藏在祭坛下。"))
    runner = GoldenModuleSuiteRunner(
        client,
        test_db,
        storage_root=tmp_path / "sources",
        asset_root=tmp_path / "assets",
    )

    result = runner.run_spec(GoldenModuleSpec(
        slug="fixture-module",
        title="钟楼疑云",
        source_paths=(source,),
        source_mode="scenario",
    ))

    assert result["import_status"] == "draft_ready"
    assert result["runtime_gate_status"] == "ready"
    assert result["room_status"] == "completed"
    assert result["action_status"] == "completed"
    assert result["ending"]["source_mode"] == "scenario"
    assert result["ending"]["citation"]["source_ref"].endswith("#paragraph:1")


def _minimal_docx(text: str) -> bytes:
    document_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
