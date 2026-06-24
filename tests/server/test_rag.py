import pytest
from src.server.db_pg import PgDatabase
from src.server.embedding import HybridEmbedding
from src.server.rag import RAGStore


@pytest.fixture
def rag_store():
    try:
        db = PgDatabase()
        pool = db.connect()
        db.initialize()
        emb = HybridEmbedding()
        store = RAGStore(db, emb)
        yield store
        db.close()
    except Exception as e:
        pytest.skip(f'RAG not available: {e}')


def test_index_and_search(rag_store):
    rag_store.index_scenario('test-sc-1', '这是一个测试剧本。玩家需要找到隐藏的钥匙。钥匙在地下室。', 'room-test')
    results = rag_store.search('钥匙在哪里', room_id='room-test', top_k=3)
    assert len(results) > 0
    assert any('钥匙' in r['content'] for r in results)


def test_search_different_source_types(rag_store):
    rag_store.index_scenario('test-sc-2', '场景一：黑暗的走廊', 'room-test-2')
    rag_store.index_clue('room-test-2', 'clue-1', '发现了一封信', 'room-1')
    results = rag_store.search('信', source_types=['clue'], room_id='room-test-2')
    assert all(r['source_type'] == 'clue' for r in results)


def test_stats(rag_store):
    stats = rag_store.get_stats()
    assert isinstance(stats, dict)
