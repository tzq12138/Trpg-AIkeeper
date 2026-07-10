from src.server.ai.contracts import KpCitation
from src.server.ai.rag_context import RAGContextBuilder


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def execute(self, sql, params):
        if "FROM rooms" in sql:
            return Result({"scenario_id": "sc-1"})
        return Result(None)


class FakeRag:
    def __init__(self):
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if kwargs["source_types"] != ["scenario"]:
            return []
        return [{
            "chunk_id": "chunk-1",
            "source_type": "scenario",
            "source_id": "sc-1",
            "content": "钟楼地下室有一把黑色钥匙。",
            "similarity": 0.88,
            "score": 0.91,
            "citation": {
                "chunk_id": "chunk-1",
                "source_type": "scenario",
                "source_id": "sc-1",
                "source_part_id": "part-7",
                "scenario_version_id": "sv-2",
                "source_ref": "page:7",
                "page_number": 7,
                "anchor": {"page": 7, "bbox": [1, 2, 3, 4]},
                "start_offset": 12,
                "end_offset": 28,
                "excerpt": "钟楼地下室有一把黑色钥匙。",
            },
        }]


def test_context_builder_uses_ai_audience_and_preserves_auditable_citation():
    rag = FakeRag()

    context = RAGContextBuilder(FakeConnection(), rag).build(
        "room-1", "调查钟楼"
    )

    assert rag.calls
    assert all(call[1]["audience"] == "ai" for call in rag.calls)
    assert context["scenario"][0]["citation"]["scenario_version_id"] == "sv-2"
    assert context["scenario"][0]["citation"]["anchor"]["page"] == 7
    assert context["citations"][0]["source_part_id"] == "part-7"
    assert context["citations"][0]["score"] == 0.91


def test_kp_citation_accepts_structured_provenance_without_breaking_legacy_fields():
    citation = KpCitation(
        source="旧版来源",
        text="旧版摘录",
        chunkId="chunk-1",
        sourceType="scenario",
        sourceId="sc-1",
        sourcePartId="part-1",
        scenarioVersionId="sv-1",
        sourceRef="page:3",
        pageNumber=3,
        anchor={"page": 3},
        startOffset=10,
        endOffset=20,
        excerpt="新版摘录",
        score=0.8,
    )

    dumped = citation.model_dump(by_alias=True)
    assert dumped["source"] == "旧版来源"
    assert dumped["chunkId"] == "chunk-1"
    assert dumped["scenarioVersionId"] == "sv-1"
    assert dumped["anchor"] == {"page": 3}

