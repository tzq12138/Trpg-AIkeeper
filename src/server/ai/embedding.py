import hashlib
import math
import numpy as np
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedding:
    def __init__(self, model_name: str = 'shibing624/text2vec-base-chinese'):
        self._model = None
        self._model_name = model_name

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info('Loading embedding model: %s', self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.model.encode(texts, normalize_embeddings=True)
            return vectors.tolist()
        except ModuleNotFoundError as e:
            if e.name != 'sentence_transformers':
                raise
            logger.warning('sentence_transformers is not installed, using deterministic fallback embeddings')
            return _fallback_embed(texts)

    @property
    def model_name(self) -> str:
        return self._model_name


class RemoteEmbedding:
    def __init__(self, api_key: str, model: str = 'deepseek-embedding', api_base: str = 'https://api.deepseek.com'):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        resp = httpx.post(
            f'{self.api_base}/v1/embeddings',
            headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
            json={'model': self.model, 'input': texts},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item['embedding'] for item in data['data']]

    @property
    def model_name(self) -> str:
        return self.model


class HybridEmbedding:
    def __init__(self, local: LocalEmbedding | None = None, remote: RemoteEmbedding | None = None):
        self.local = local or LocalEmbedding()
        self.remote = remote
        self._last_model_name = _provider_model_name(self.local)
        self._last_dimension: int | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.local.embed(texts)
            self._record_embedding_metadata(self.local, vectors)
            return vectors
        except Exception as e:
            if self.remote:
                logger.warning('Local embedding failed (%s), using remote', e)
                vectors = self.remote.embed(texts)
                self._record_embedding_metadata(self.remote, vectors)
                return vectors
            raise

    @property
    def model_name(self) -> str:
        return self._last_model_name

    @property
    def dimension(self) -> int:
        return self._last_dimension or 768

    def _record_embedding_metadata(self, provider, vectors: list[list[float]]) -> None:
        self._last_model_name = _provider_model_name(provider)
        if vectors:
            self._last_dimension = len(vectors[0])


def _provider_model_name(provider) -> str:
    return str(
        getattr(provider, 'model_name', '')
        or getattr(provider, '_model_name', '')
        or getattr(provider, 'model', '')
        or type(provider).__name__
    )


def _fallback_embed(texts: list[str], dimension: int = 768) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * dimension
        for char in text:
            digest = hashlib.sha256(char.encode('utf-8')).digest()
            index = int.from_bytes(digest[:4], 'big') % dimension
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
