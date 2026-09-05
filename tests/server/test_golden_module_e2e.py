import io
import zipfile

from src.server.scenario.golden_suite import GoldenModuleSpec
from scripts.run_golden_module_suite import GoldenModuleSuiteRunner, _reset_database


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
    assert result["trace_complete"] is True
    assert result["trace_phase_names"][0] == "input_received"
    assert "resolution_returned" in result["trace_phase_names"]
    assert result["trace_phase_names"][-1] == "finalized"
    assert result["host_adjudication_count"] == 0
    assert result["ending"]["source_mode"] == "scenario"
    assert result["ending"]["citation"]["source_ref"].endswith("#paragraph:1")


def test_golden_suite_reset_removes_rule_supporting_assets(test_db):
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, license_type, created_by) "
        "VALUES ('golden-rule-set', 'Golden Rules', 'golden-suite-coc7', 'coc7', 'authorized', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, created_by) "
        "VALUES ('golden-rule-version', 'golden-rule-set', 1, 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_documents "
        "(doc_id, rule_set_version_id, title, category, content) "
        "VALUES ('golden-rule-doc', 'golden-rule-version', 'Rules', 'test', 'rule text')"
    )
    test_db.execute(
        "INSERT INTO document_chunks "
        "(chunk_id, source_type, source_id, content, rule_set_version_id) "
        "VALUES ('golden-rule-chunk', 'rule', 'golden-rule-doc', 'rule text', 'golden-rule-version')"
    )
    test_db.commit()

    _reset_database(test_db)

    for table_name in ("rule_sets", "rule_set_versions", "rule_documents", "document_chunks"):
        count = test_db.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"]
        assert count == 0


def _minimal_docx(text: str) -> bytes:
    document_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
