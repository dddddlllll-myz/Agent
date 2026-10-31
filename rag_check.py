"""一次性诊断：检查知识库里有没有数据 + 检索分数。
用法（项目根目录）：uv run python rag_check.py
"""

import psycopg

from app.core.config import settings
from app.services import rag


def main() -> None:
    table = settings.RAG_TABLE_NAME
    # 1) 数一下表里有多少条
    with psycopg.connect(rag._conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table}")
            n = cur.fetchone()[0]
            cur.execute(f"SELECT DISTINCT source FROM {table}")
            sources = [r[0] for r in cur.fetchall()]
    print(f"[表 {table}] 共 {n} 块，来源: {sources}")

    if n == 0:
        print(">>> 知识库是空的！说明 ingest_docs.py 没灌进去。先跑灌库再说。")
        return

    # 2) 跑一次检索，看分数能不能过阈值
    q = "Nebula-7 项目的单实例 QPS 上限是多少"
    print(f"\n[检索] query = {q!r}")
    print(f"[配置] RAG_SCORE_THRESHOLD = {settings.RAG_SCORE_THRESHOLD}, RAG_TOP_K = {settings.RAG_TOP_K}")
    hits = rag.search(q)
    for i, r in enumerate(hits, 1):
        flag = "✅过阈值" if r["score"] >= settings.RAG_SCORE_THRESHOLD else "❌被过滤"
        print(f"  [{i}] score={r['score']:.4f} {flag} 来源={r['source']}")
        print(f"      {r['content'][:80]}...")
    if not hits:
        print("  检索无结果。")


if __name__ == "__main__":
    main()
