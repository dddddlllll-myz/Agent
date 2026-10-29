"""LangGraph 知识库检索工具（文档 RAG）。

放到 app/core/langgraph/tools/knowledge_search.py。

让大模型在需要"查资料"时主动调用：它会把问题向量化，在 pgvector 知识库里
检索最相关的文档片段返回。与 mem0 记忆（记"你是谁"）互补，这里查"你的资料"。
"""

from langchain_core.tools import tool

from app.core.config import settings
from app.services import rag


@tool
def knowledge_search(query: str) -> str:
    """从知识库中检索与问题相关的文档片段.

    当用户的问题可能需要依据已导入的资料、文档、手册、规范来回答时，
    调用本工具获取相关片段，再基于片段作答，并尽量标注来源。
    纯常识或闲聊无需调用。

    参数：
        query: 要检索的问题或关键词。

    返回：
        str: 若干相关片段（含来源）；无结果或出错时返回说明文本。
    """
    try:
        results = rag.search(query)
    except Exception as e:  # 工具出错不应中断 Agent
        return f"知识库检索失败：{e}"

    hits = [r for r in results if r["score"] >= settings.RAG_SCORE_THRESHOLD]
    if not hits:
        return "知识库中没有找到相关内容。"

    lines = []
    for i, r in enumerate(hits, 1):
        src = f"（来源：{r['source']}）" if r["source"] else ""
        lines.append(f"[{i}] {r['content']}{src}")
    return "\n\n".join(lines)