import pytest


def test_cosine_similarity():
    from src.server.ai.embedding import cosine_similarity
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) > 0.99
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(a, b)) < 0.01


def test_chunk_text():
    from src.server.ai.rag import chunk_text
    chunks = chunk_text('A' * 1000, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunk_text_short():
    from src.server.ai.rag import chunk_text
    chunks = chunk_text('Short text')
    assert len(chunks) == 1


def test_chunk_text_empty():
    from src.server.ai.rag import chunk_text
    chunks = chunk_text('')
    assert len(chunks) == 0


def test_hybrid_embedding_tracks_actual_model_and_dimensions_after_switch():
    from src.server.ai.embedding import HybridEmbedding

    class Local:
        model_name = "local-v1"

        def embed(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class FailingLocal(Local):
        def embed(self, texts):
            raise RuntimeError("local unavailable")

    class Remote:
        model_name = "remote-v2"

        def embed(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    local_hybrid = HybridEmbedding(local=Local(), remote=Remote())
    local_hybrid.embed(["local"])
    assert local_hybrid.model_name == "local-v1"
    assert local_hybrid.dimension == 2

    remote_hybrid = HybridEmbedding(local=FailingLocal(), remote=Remote())
    remote_hybrid.embed(["remote"])
    assert remote_hybrid.model_name == "remote-v2"
    assert remote_hybrid.dimension == 3
