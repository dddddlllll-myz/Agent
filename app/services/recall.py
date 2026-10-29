"""分层召回 (layered recall) + token 预算控制。

放到 app/services/recall.py。

借鉴 OpenViking 的 L0/L1/L2 分级按需加载思路，适配到 mem0 的扁平事实记忆：
  - L1(完整)：分数最高、且在 token 预算内的若干条，渲染全文，模型重点参考；
  - L0(索引)：预算外但仍高于阈值的记忆，压成一行短摘要，让模型"知道还有这些"
             但几乎不花 token（需要时可追问）；
  - 低于阈值 / 超出溢出上限的，直接丢弃。
整个过程受 score_threshold（相关性闸门）与 token_budget（注入总量）双重约束，
保证无论库里有多少记忆，注入上下文的体量稳定可控。

这是一个纯函数模块，不依赖 mem0 / 数据库，便于单测。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecallConfig:
    """分层召回参数。字段默认值对标 dsh-openviking 的 autoRecall 配置。"""

    score_threshold: float = 0.15  # 综合相关性最低分（低于此分视为噪声丢弃）
    token_budget: int = 1500       # 注入总预算（约 token 数）
    chars_per_token: int = 4       # token≈字符换算；中文偏保守取 4
    l1_max_items: int = 8          # L1 全文最多条数
    l0_overflow_items: int = 12    # L0 索引最多条数
    l0_headline_chars: int = 40    # 单条 L0 索引截断长度


def _headline(text: str, limit: int) -> str:
    """把一条记忆压成单行短摘要（折叠空白 + 截断）。"""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_layered_context(results: list[dict], cfg: RecallConfig | None = None) -> str:
    """把 mem0 的原始 results 构造成分层上下文字符串。

    Args:
        results: mem0 ``memory.search(...)["results"]``，每项形如
                 ``{"memory": str, "score": float, ...}``。
        cfg: 分层召回参数；为 None 时用默认值。

    Returns:
        可直接作为 ``long_term_memory`` 注入 prompt 的字符串；无命中时返回 ""。
    """
    cfg = cfg or RecallConfig()

    # 1) 过滤：只保留有正文、且分数达到阈值的；按分数降序
    scored = [
        r
        for r in results
        if isinstance(r.get("memory"), str)
        and r["memory"].strip()
        and float(r.get("score") or 0.0) >= cfg.score_threshold
    ]
    scored.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    if not scored:
        return ""

    char_budget = cfg.token_budget * cfg.chars_per_token
    used = 0
    l1_lines: list[str] = []
    overflow: list[dict] = []

    # 2) L1 全文：高分优先，受 token 预算 + 条数上限双限；超出的降级到 overflow
    for r in scored:
        if len(l1_lines) >= cfg.l1_max_items:
            overflow.append(r)
            continue
        line = f"* {r['memory'].strip()}"
        # 至少保留 1 条全文，避免预算过小导致全空
        if l1_lines and used + len(line) > char_budget:
            overflow.append(r)
            continue
        l1_lines.append(line)
        used += len(line) + 1

    # 3) L0 索引：预算外的记忆压成一行短摘要
    l0_lines = [_headline(r["memory"], cfg.l0_headline_chars) for r in overflow[: cfg.l0_overflow_items]]

    parts = ["\n".join(l1_lines)]
    if l0_lines:
        parts.append("(相关但次要，可按需向用户追问) " + "; ".join(l0_lines))
    return "\n\n".join(p for p in parts if p)