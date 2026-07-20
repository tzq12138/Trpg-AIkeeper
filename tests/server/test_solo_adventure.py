from pathlib import Path

from src.server.scenario.content_package import build_content_package
from src.server.scenario.solo_adventure import extract_solo_adventure


def test_extracts_numbered_nodes_transitions_and_source_anchors():
    result = extract_solo_adventure([
        {
            "source_part_id": "part-page-1",
            "page_number": 1,
            "source_ref": "向火独行.pdf#page=1",
            "text_content": "1# 你抵达车站。要上车，转到 2。\n2# 车门在你身后关上。",
        }
    ])

    assert result["detected"] is True
    assert result["integrity"]["is_valid"] is True
    assert result["root_node_id"] == "1"
    assert result["integrity"]["terminal_node_ids"] == ["2"]
    assert result["nodes"][0]["node_id"] == "1"
    assert result["nodes"][0]["target_node_ids"] == ["2"]
    assert result["nodes"][0]["citation"] == {
        "source_part_id": "part-page-1",
        "source_ref": "向火独行.pdf#page=1",
        "page_number": 1,
    }


def test_marks_duplicate_or_missing_targets_as_invalid():
    result = extract_solo_adventure([
        {
            "source_part_id": "part-page-2",
            "page_number": 2,
            "source_ref": "向火独行.pdf#page=2",
            "text_content": "1# 第一段。转到 3。\n1# 重复条目。\n2# 另一段。",
        }
    ])

    assert result["detected"] is True
    assert result["integrity"]["is_valid"] is False
    assert result["integrity"]["duplicate_node_ids"] == ["1"]
    assert result["integrity"]["missing_target_node_ids"] == ["3"]


def test_extracts_ocr_split_dice_and_flipped_targets():
    text = (
        "1# "
        "\u8f6c 1 \u523064\u3002\u5982\u679c\u5931\u8d25\uff0c\u7ffb\n"
        "\u5230127\u3002\u5bab\u6d9f\u8f6c\u5230\u4e2a 205\u3002\n"
        "64# \u7ee7\u7eed\u3002\n127# \u7ee7\u7eed\u3002\n205# \u7ee7\u7eed\u3002"
    )

    result = extract_solo_adventure([{"text_content": text}])

    assert result["nodes"][0]["target_node_ids"] == ["64", "127", "205"]
    assert result["integrity"]["terminal_node_ids"] == ["64", "127", "205"]


def test_alone_against_the_flames_original_has_complete_unique_jump_graph():
    root = Path(__file__).resolve().parents[2]
    source = root / "data" / "test_assets" / "最小测试模块" / "向火独行.pdf"
    package = build_content_package(
        source.name, source.read_bytes(), "application/pdf"
    )
    result = extract_solo_adventure([
        {
            "source_part_id": f"golden-{part.ordinal}",
            "page_number": part.page_number,
            "source_ref": part.source_ref,
            "text_content": part.text,
        }
        for part in package.parts
        if part.kind == "text"
    ])

    assert result["root_node_id"] == "1"
    assert result["integrity"]["node_count"] == 270
    assert result["integrity"]["edge_count"] == 410
    assert result["integrity"]["duplicate_node_ids"] == []
    assert result["integrity"]["missing_target_node_ids"] == []
    assert result["integrity"]["is_valid"] is True
    terminal_nodes = [
        node for node in result["nodes"] if not node["target_node_ids"]
    ]
    assert terminal_nodes
    assert all("\u5267\u7ec8" in node["text"] for node in terminal_nodes)
    node_one = next(node for node in result["nodes"] if node["node_id"] == "1")
    assert node_one["text"].startswith("太阳高悬天空")
    assert node_one["target_node_ids"] == ["263"]
    node_263 = next(node for node in result["nodes"] if node["node_id"] == "263")
    assert "ALONE" not in node_263["text"]
