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
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


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


class HybridEmbedding:
    def __init__(self, local: LocalEmbedding | None = None, remote: RemoteEmbedding | None = None):
        self.local = local or LocalEmbedding()
        self.remote = remote

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self.local.embed(texts)
        except Exception as e:
            if self.remote:
                logger.warning('Local embedding failed (%s), using remote', e)
                return self.remote.embed(texts)
            raise

    @property
    def dimension(self) -> int:
        return 768


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
