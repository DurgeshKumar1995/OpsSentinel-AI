"""Embedding providers for semantic incident memory."""

import hashlib
import math
import re
from typing import Protocol

from openai import OpenAI

from config.settings import Settings


class Embedder(Protocol):
    model_name: str

    def embed(self, text: str) -> list[float]: ...


class LocalHashEmbedder:
    """Deterministic, offline feature-hashing embeddings for development/tests."""

    model_name = "local-hash-v1"

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimensions
            sign = 1.0 if digest[0] & 1 else -1.0
            vector[index] += sign
        return normalize(vector)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model_name = model

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model_name, input=text)
        return normalize(response.data[0].embedding)


def normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    return vector if magnitude == 0 else [value / magnitude for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def create_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings.openai_api_key or "", settings.embedding_model)
    return LocalHashEmbedder(settings.embedding_dimensions)
