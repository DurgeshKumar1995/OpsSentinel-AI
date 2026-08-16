"""Reviewed, durable memory for improving future incident responses."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from config.settings import settings
from services.embeddings import Embedder, cosine_similarity
from services.security import safe_for_learning


@dataclass(frozen=True)
class Lesson:
    service_name: str
    symptom: str
    resolution: str
    rating: int


@dataclass(frozen=True)
class LearnedResponse:
    query: str
    response: str
    created_at: str
    uses: int
    similarity: float = 1.0


@dataclass(frozen=True)
class KnowledgeDocument:
    source: str
    content: str
    metadata: dict
    similarity: float = 0.0


class LearningStore:
    """Stores operator-reviewed outcomes; unreviewed model output is never learned."""

    def __init__(self, db_path: str | None = None, embedder: Embedder | None = None):
        self.db_path = Path(db_path or settings.memory_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._setup()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _setup(self):
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lessons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        service_name TEXT NOT NULL,
                        symptom TEXT NOT NULL,
                        resolution TEXT NOT NULL,
                        rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                        approved INTEGER NOT NULL CHECK (approved IN (0, 1)),
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS learned_responses (
                        query_key TEXT PRIMARY KEY,
                        query TEXT NOT NULL,
                        response TEXT NOT NULL,
                        safe_read_only INTEGER NOT NULL CHECK (safe_read_only = 1),
                        uses INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        last_used_at TEXT
                    )
                    """
                )
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(learned_responses)")
                }
                if "embedding" not in columns:
                    connection.execute("ALTER TABLE learned_responses ADD COLUMN embedding TEXT")
                if "embedding_model" not in columns:
                    connection.execute("ALTER TABLE learned_responses ADD COLUMN embedding_model TEXT")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_documents (
                        document_key TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata TEXT NOT NULL,
                        embedding TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS request_usage (
                        thread_id TEXT PRIMARY KEY,
                        query TEXT NOT NULL,
                        source TEXT NOT NULL,
                        model TEXT,
                        ai_calls INTEGER NOT NULL,
                        input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL,
                        total_tokens INTEGER NOT NULL,
                        estimated_cost_usd REAL NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Normalize harmless wording differences while keeping matching strict."""
        return re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()

    @classmethod
    def _query_key(cls, query: str) -> str:
        return hashlib.sha256(cls._normalize_query(query).encode("utf-8")).hexdigest()

    @classmethod
    def _compatible_query(cls, current: str, stored: str) -> bool:
        """Fail closed when embeddings match requests with different intent."""
        ignored = {
            "a", "an", "and", "for", "in", "is", "of", "please", "the", "to",
            "me", "my", "show", "tell", "can", "you", "last", "minutes", "minute",
        }
        current_terms = set(cls._normalize_query(current).split()) - ignored
        stored_terms = set(cls._normalize_query(stored).split()) - ignored
        if not current_terms or not stored_terms:
            return False
        overlap = len(current_terms & stored_terms) / len(current_terms | stored_terms)
        intent_groups = (
            {"log", "logs", "health", "status", "monitor", "check"},
            {"deploy", "deployment", "release", "rollout"},
            {"restart", "fix", "repair", "resolve"},
            {"design", "architecture", "diagram"},
            {"pipeline", "ci", "cd", "build"},
        )
        current_intents = {i for i, group in enumerate(intent_groups) if current_terms & group}
        stored_intents = {i for i, group in enumerate(intent_groups) if stored_terms & group}
        if current_intents != stored_intents:
            return False
        return overlap >= 0.65

    def remember_safe_response(self, query: str, response: str) -> None:
        """Remember only a completed read-only result; callers enforce that policy."""
        if not query.strip() or not response.strip() or not safe_for_learning(query, response):
            return
        now = datetime.now(UTC).isoformat()
        vector = self.embedder.embed(query) if self.embedder else None
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """INSERT INTO learned_responses
                       (query_key, query, response, safe_read_only, uses, created_at,
                        embedding, embedding_model)
                       VALUES (?, ?, ?, 1, 0, ?, ?, ?)
                       ON CONFLICT(query_key) DO UPDATE SET
                         query = excluded.query,
                         response = excluded.response,
                         created_at = excluded.created_at,
                         embedding = excluded.embedding,
                         embedding_model = excluded.embedding_model""",
                    (
                        self._query_key(query), query.strip(), response.strip(), now,
                        json.dumps(vector) if vector else None,
                        self.embedder.model_name if self.embedder else None,
                    ),
                )

    def recall_safe_response(self, query: str) -> LearnedResponse | None:
        key = self._query_key(query)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT query, response, created_at, uses
                   FROM learned_responses
                   WHERE query_key = ? AND safe_read_only = 1""",
                (key,),
            ).fetchone()
            if row is None:
                return None
            with connection:
                connection.execute(
                    """UPDATE learned_responses
                       SET uses = uses + 1, last_used_at = ? WHERE query_key = ?""",
                    (datetime.now(UTC).isoformat(), key),
                )
        return LearnedResponse(row[0], row[1], row[2], row[3] + 1)

    def recall_similar_response(
        self, query: str, threshold: float = 0.92
    ) -> LearnedResponse | None:
        """Return a safe response only when semantic similarity is very high."""
        if not self.embedder:
            return None
        query_vector = self.embedder.embed(query)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT query_key, query, response, created_at, uses, embedding
                   FROM learned_responses
                   WHERE safe_read_only = 1 AND embedding IS NOT NULL
                     AND embedding_model = ?""",
                (self.embedder.model_name,),
            ).fetchall()
            scored = [
                (cosine_similarity(query_vector, json.loads(row[5])), row)
                for row in rows if self._compatible_query(query, row[1])
            ]
            if not scored:
                return None
            score, row = max(scored, key=lambda item: item[0])
            if score < threshold:
                return None
            with connection:
                connection.execute(
                    """UPDATE learned_responses SET uses = uses + 1, last_used_at = ?
                       WHERE query_key = ?""",
                    (datetime.now(UTC).isoformat(), row[0]),
                )
        return LearnedResponse(row[1], row[2], row[3], row[4] + 1, score)

    def index_document(self, source: str, content: str, metadata: dict) -> bool:
        """Index a sanitized public/reviewed document for retrieval, not action replay."""
        if not self.embedder or not content.strip() or not safe_for_learning(content, content):
            return False
        key_material = f"{source}\n{content}"
        document_key = hashlib.sha256(key_material.encode()).hexdigest()
        vector = self.embedder.embed(content)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """INSERT INTO knowledge_documents
                       (document_key, source, content, metadata, embedding,
                        embedding_model, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(document_key) DO UPDATE SET
                         metadata = excluded.metadata,
                         embedding = excluded.embedding,
                         embedding_model = excluded.embedding_model""",
                    (
                        document_key,
                        source,
                        content.strip(),
                        json.dumps(metadata, sort_keys=True),
                        json.dumps(vector),
                        self.embedder.model_name,
                        datetime.now(UTC).isoformat(),
                    ),
                )
        return True

    def search_documents(
        self, query: str, limit: int = 3, threshold: float = 0.35
    ) -> list[KnowledgeDocument]:
        if not self.embedder:
            return []
        query_vector = self.embedder.embed(query)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT source, content, metadata, embedding
                   FROM knowledge_documents WHERE embedding_model = ?""",
                (self.embedder.model_name,),
            ).fetchall()
        scored = [
            (cosine_similarity(query_vector, json.loads(row[3])), row) for row in rows
        ]
        return [
            KnowledgeDocument(row[0], row[1], json.loads(row[2]), score)
            for score, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
            if score >= threshold
        ]

    def record(self, lesson: Lesson, approved: bool) -> int:
        if not 1 <= lesson.rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """INSERT INTO lessons
                       (service_name, symptom, resolution, rating, approved, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        lesson.service_name.strip(), lesson.symptom.strip(),
                        lesson.resolution.strip(), lesson.rating, int(approved),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                return int(cursor.lastrowid)

    def record_usage(self, thread_id: str, query: str, source: str, usage: dict) -> None:
        """Store the latest cumulative usage for an incident thread."""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """INSERT INTO request_usage
                       (thread_id, query, source, model, ai_calls, input_tokens,
                        output_tokens, total_tokens, estimated_cost_usd, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(thread_id) DO UPDATE SET
                         query = excluded.query, source = excluded.source,
                         model = excluded.model, ai_calls = excluded.ai_calls,
                         input_tokens = excluded.input_tokens,
                         output_tokens = excluded.output_tokens,
                         total_tokens = excluded.total_tokens,
                         estimated_cost_usd = excluded.estimated_cost_usd,
                         updated_at = excluded.updated_at""",
                    (
                        thread_id, query.strip(), source, usage.get("model"),
                        usage["ai_calls"], usage["input_tokens"],
                        usage["output_tokens"], usage["total_tokens"],
                        usage["estimated_cost_usd"], datetime.now(UTC).isoformat(),
                    ),
                )

    def recent_usage(self, limit: int = 50) -> list[dict]:
        """Return recent request costs for operator auditing."""
        with closing(self._connect()) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM request_usage ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def relevant(self, query: str, limit: int = 3) -> list[Lesson]:
        """Retrieve highly rated, approved lessons using safe lexical matching."""
        terms = {term.lower().strip("'\".,") for term in query.split() if len(term) > 3}
        if not terms:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT service_name, symptom, resolution, rating
                   FROM lessons WHERE approved = 1 AND rating >= 4
                   ORDER BY rating DESC, id DESC LIMIT 100"""
            ).fetchall()
        ranked = []
        for row in rows:
            haystack = f"{row[0]} {row[1]}".lower()
            score = sum(term in haystack for term in terms)
            if score:
                ranked.append((score, Lesson(*row)))
        return [lesson for _, lesson in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]


def format_lessons(lessons: list[Lesson]) -> str:
    if not lessons:
        return "No reviewed lessons apply to this incident."
    return "\n".join(
        f"- {lesson.service_name}: symptom={lesson.symptom}; reviewed resolution={lesson.resolution}"
        for lesson in lessons
    )
