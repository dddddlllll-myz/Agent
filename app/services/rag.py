"""文档 RAG 服务：DashScope 向量化 + pgvector 检索。

放到 app/services/rag.py。

与 mem0 长期记忆互补：
  - mem0 记的是"关于用户的事实/偏好"（memory.py）；
  - 本模块管的是"你灌进来的知识库文档"，供 Agent 按需检索回答。

两者复用同一个 PostgreSQL + pgvector 实例和同一个 DashScope embedding 模型，
但各自独立的表（本模块用 knowledge_chunks，mem0 用它自己的 collection），互不干扰。

设计取向：
  - 不引入新依赖，直接用项目已装的 psycopg(3) + openai 客户端；
  - 向量以文本字面量 '[...]'::vector 写入/查询，避免依赖 pgvector 的 python 适配包；
  - 同步实现，和现有的 duckduckgo / calculator 工具风格一致（工具在 ToolNode 里调用）。
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from openai import OpenAI

from app.core.config import settings
from app.core.logging import logger

_EMBED_BATCH = 10  # DashScope 兼容模式单次 embedding 输入上限，保守取 10


def _conninfo() -> str:
    """拼 PostgreSQL 连接串（复用 mem0 那套 POSTGRES_* 配置）。"""
    return (
        f"host={settings.POSTGRES_HOST} port={settings.POSTGRES_PORT} "
        f"dbname={settings.POSTGRES_DB} user={settings.POSTGRES_USER} "
        f"password={settings.POSTGRES_PASSWORD}"
    )


def _embed_client() -> OpenAI:
    """返回指向 DashScope（OpenAI 兼容端点）的 embedding 客户端。"""
    return OpenAI(api_key=settings.DASHSCOPE_API_KEY, base_url=settings.DASHSCOPE_BASE_URL)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """把一批文本向量化，分批请求以避免超过单次输入上限。"""
    client = _embed_client()
    out: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        resp = client.embeddings.create(
            model=settings.LONG_TERM_MEMORY_EMBEDDER_MODEL,
            input=batch,
            dimensions=settings.LONG_TERM_MEMORY_EMBEDDING_DIMS,
        )
        out.extend([d.embedding for d in resp.data])
    return out


def _vec_literal(vec: list[float]) -> str:
    """把向量转成 pgvector 能识别的文本字面量 '[0.1,0.2,...]'。"""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def ensure_table() -> None:
    """建表 + 向量索引（幂等）。应用启动时调用一次。"""
    dims = settings.LONG_TERM_MEMORY_EMBEDDING_DIMS
    table = settings.RAG_TABLE_NAME
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id BIGSERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    source TEXT,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    embedding vector({dims}),
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )
            # HNSW 余弦索引，加速语义检索（pgvector >= 0.5）
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table}_embedding_idx
                ON {table} USING hnsw (embedding vector_cosine_ops);
                """
            )
    logger.info("rag_table_ready", table=table, dims=dims)


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """把长文本按字符切块，块间保留 overlap 重叠以免切断语义。

    优先在换行/句号附近断开，断不开再硬切。
    """
    size = size or settings.RAG_CHUNK_SIZE
    overlap = overlap or settings.RAG_CHUNK_OVERLAP
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 在 [end-overlap, end] 窗口里找个自然断点
            window = text[max(start, end - overlap) : end]
            for sep in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? "):
                pos = window.rfind(sep)
                if pos != -1:
                    end = max(start, end - overlap) + pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def add_document(content: str, source: str = "", metadata: dict[str, Any] | None = None) -> int:
    """切块 → 向量化 → 写入 pgvector。返回写入的块数。"""
    metadata = metadata or {}
    chunks = chunk_text(content)
    if not chunks:
        return 0

    vectors = embed_texts(chunks)
    table = settings.RAG_TABLE_NAME
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        with conn.cursor() as cur:
            for chunk, vec in zip(chunks, vectors):
                cur.execute(
                    f"INSERT INTO {table} (content, source, metadata, embedding) "
                    f"VALUES (%s, %s, %s::jsonb, %s::vector)",
                    (chunk, source, json.dumps(metadata, ensure_ascii=False), _vec_literal(vec)),
                )
    logger.info("rag_document_added", source=source, chunks=len(chunks))
    return len(chunks)


def search(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """语义检索：返回最相关的若干块。

    Returns:
        [{"content": str, "source": str, "score": float}]，score 越大越相关（1 - 余弦距离）。
    """
    top_k = top_k or settings.RAG_TOP_K
    qvec = embed_texts([query])[0]
    table = settings.RAG_TABLE_NAME
    rows: list[dict[str, Any]] = []
    with psycopg.connect(_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT content, source, 1 - (embedding <=> %s::vector) AS score
                FROM {table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (_vec_literal(qvec), _vec_literal(qvec), top_k),
            )
            for content, source, score in cur.fetchall():
                rows.append({"content": content, "source": source or "", "score": float(score)})
    return rows