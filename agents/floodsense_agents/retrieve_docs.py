"""One document retrieve. Ranking stays in Postgres. Hydration stays in Zetaris.

The API key and the database DSN are never logged. FF_RAG_DOCS stays off
until a caller passes the flag.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_CHUNK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,127}$")
_EVENTS = {"EMSR773", "EMSR517"}
_HYDRATE_SQL = (
    "SELECT chunk_id, text, text_sha256, title, source_url, publisher, licence, "
    "attribution, page, paragraph, lines, section FROM PGVECTOR_RAG.chunks "
    "WHERE chunk_id IN ({ids})"
)
_HALFVEC_SQL = """
SELECT chunk_id, (embedding::halfvec(2048) <=> $1::halfvec(2048)) AS distance
FROM rag.chunks
WHERE level = 'paragraph'
  AND embedding IS NOT NULL
  AND ($2::text IS NULL OR event_id = $2)
ORDER BY embedding::halfvec(2048) <=> $1::halfvec(2048)
LIMIT $3
""".strip()
_EXACT_SQL = """
SELECT chunk_id, (embedding <=> $1::vector) AS distance
FROM rag.chunks
WHERE level = 'paragraph'
  AND embedding IS NOT NULL
  AND ($2::text IS NULL OR event_id = $2)
ORDER BY embedding <=> $1::vector
LIMIT $3
""".strip()

Embedder = Callable[[list[str], str], list[list[float]]]
Search = Callable[[list[float], str | None, int], list[tuple[str, float]]]
Hydrate = Callable[[list[str]], tuple[str, list[dict]]]


@dataclass(frozen=True)
class RetrieveResult:
    citations: list[dict]
    error: str | None


def quote_from_text(text: str, paragraph_lines: str) -> tuple[str, str]:
    """Return a verbatim quote of at most 600 characters and its line range."""
    pieces = text.split("\n")
    if len(text) <= 600 and len(pieces) == 1:
        return text, "1-1"
    if len(text) <= 600:
        return text, paragraph_lines
    chosen: list[str] = []
    for line in pieces:
        candidate = line if not chosen else "\n".join([*chosen, line])
        if len(candidate) > 600:
            break
        chosen.append(line)
    if not chosen:
        return text[:600], "1-1"
    return "\n".join(chosen), f"1-{len(chosen)}"


def retrieve_docs(
    query: str,
    k: int,
    filters: dict | None,
    *,
    embedder: Embedder,
    search: Search,
    hydrate: Hydrate,
) -> RetrieveResult:
    """Embed the query, rank in Postgres, and hydrate text through Zetaris."""
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
        return RetrieveResult([], "k must be from 1 to 20")
    event_id, event_error = _event_id(filters)
    if event_error:
        return RetrieveResult([], event_error)
    try:
        vectors = embedder([query], "query")
    except Exception as exc:
        return RetrieveResult([], _short(exc))
    if not vectors:
        return RetrieveResult([], "embedder returned no vector")
    try:
        ranked = search(vectors[0], event_id, k)
    except Exception as exc:
        return RetrieveResult([], _short(exc))
    if not ranked:
        return RetrieveResult([], None)
    ids = [chunk_id for chunk_id, _distance in ranked]
    if any(_CHUNK_ID.fullmatch(chunk_id) is None for chunk_id in ids):
        return RetrieveResult([], "chunk_id is not safe to query")
    try:
        query_id, rows = hydrate(ids)
    except Exception as exc:
        return RetrieveResult([], _short(exc))
    if not query_id:
        return RetrieveResult([], None)
    by_id = {row.get("chunk_id"): row for row in rows if isinstance(row, dict)}
    citations = []
    for chunk_id, _distance in ranked:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        citation = _citation(query_id, row)
        if citation is not None:
            citations.append(citation)
    return RetrieveResult(citations, None)


def default_embedder(texts: list[str], input_type: str) -> list[list[float]]:
    from floodsense_agents.nim_embed import DEFAULT_URL, EmbedError, embed_texts

    key = os.environ.get("NVIDIA_NIM_API_KEY", "")
    if not key:
        raise EmbedError("NVIDIA_NIM_API_KEY is not set")
    url = os.environ.get("NIM_EMBEDDINGS_URL") or DEFAULT_URL
    root = Path(__file__).resolve().parents[2]
    return embed_texts(texts, input_type, root=root, api_key=key, url=url)


def default_search(vector: list[float], event_id: str | None, k: int) -> list[tuple[str, float]]:
    dsn = os.environ.get("PGVECTOR_DSN", "")
    if not dsn:
        raise RuntimeError("PGVECTOR_DSN is not set")
    try:
        return _search(dsn, _HALFVEC_SQL, vector, event_id, k)
    except Exception as exc:
        if "halfvec" not in str(exc).lower():
            raise RuntimeError(_hide(str(exc), dsn)) from None
        return _search(dsn, _EXACT_SQL, vector, event_id, k)


def default_hydrate(chunk_ids: list[str], zetaris) -> tuple[str, list[dict]]:
    if any(_CHUNK_ID.fullmatch(chunk_id) is None for chunk_id in chunk_ids):
        raise ValueError("chunk_id is not safe to query")
    if not chunk_ids:
        return "", []
    quoted = ", ".join("'" + chunk_id + "'" for chunk_id in chunk_ids)
    sql = _HYDRATE_SQL.format(ids=quoted)
    if "<=>" in sql or "<->" in sql or "embedding" in sql.lower():
        raise ValueError("hydrate sql is not metadata only")
    evidence = zetaris.run_sql(sql)
    if evidence.error:
        raise RuntimeError(str(evidence.error)[:200])
    return evidence.query_id, list(evidence.rows_sample)


def _event_id(filters: dict | None) -> tuple[str | None, str | None]:
    if not filters or "event_id" not in filters or filters.get("event_id") is None:
        return None, None
    event_id = filters.get("event_id")
    if event_id in _EVENTS:
        return str(event_id), None
    return None, "event_id must be EMSR773 or EMSR517"


def _positive_int(value: object) -> int | None:
    """Zetaris REST returns every column as a string, so '3' counts as 3."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, int) and value >= 1:
        return value
    return None


def _citation(query_id: str, row: dict) -> dict | None:
    text = row.get("text")
    page = _positive_int(row.get("page"))
    if not isinstance(text, str) or page is None:
        return None
    paragraph = _positive_int(row.get("paragraph"))
    lines = row.get("lines")
    if paragraph is None:
        return None
    if not isinstance(lines, str) or not lines:
        return None
    quote, quote_lines = quote_from_text(text, lines)
    locator = {"page": page, "paragraph": paragraph, "lines": quote_lines}
    section = row.get("section")
    if isinstance(section, str) and section:
        locator["section"] = section
    chunk_id = row.get("chunk_id")
    citation = {
        "layer": "c",
        "query_id": query_id,
        "source_url": row.get("source_url"),
        "title": row.get("title"),
        "publisher": row.get("publisher"),
        "licence": row.get("licence"),
        "attribution": row.get("attribution"),
        "locator": locator,
        "quote": quote,
        "content_sha256": hashlib.sha256(quote.encode()).hexdigest(),
        "storage": "full_text",
        "chunk_id": chunk_id,
        "text": text,
        "text_sha256": row.get("text_sha256"),
    }
    return citation


def bind_search(
    statement: str, vector: list[float], event_id: str | None, k: int
) -> tuple[str, dict]:
    """Bind $1, $2, and $3 by name. The statements reuse $1 and $2."""
    sql = (
        statement.replace("$1", "%(vector)s")
        .replace("$2", "%(event_id)s")
        .replace("$3", "%(k)s")
    )
    rendered = "[" + ",".join(str(item) for item in vector) + "]"
    return sql, {"vector": rendered, "event_id": event_id, "k": k}


def _connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn)


def _search(
    dsn: str, statement: str, vector: list[float], event_id: str | None, k: int
) -> list[tuple[str, float]]:
    sql, params = bind_search(statement, vector, event_id, k)
    try:
        with _connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [(str(chunk_id), float(distance)) for chunk_id, distance in cur.fetchall()]
    except Exception as exc:
        message = _hide(str(exc), dsn)
        if "halfvec" in message.lower():
            raise RuntimeError(message) from None
        raise RuntimeError(message) from None


def _hide(message: str, secret: str) -> str:
    if secret and secret in message:
        return "pgvector search failed"
    return message[:200]


def _short(exc: BaseException) -> str:
    return str(exc)[:200]
