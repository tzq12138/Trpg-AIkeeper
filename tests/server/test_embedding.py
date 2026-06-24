import pytest


def test_cosine_similarity():
    from src.server.embedding import cosine_similarity
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) > 0.99
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(a, b)) < 0.01


def test_chunk_text():
    from src.server.rag import chunk_text
    chunks = chunk_text('A' * 1000, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunk_text_short():
    from src.server.rag import chunk_text
    chunks = chunk_text('Short text')
    assert len(chunks) == 1


def test_chunk_text_empty():
    from src.server.rag import chunk_text
    chunks = chunk_text('')
    assert len(chunks) == 0
