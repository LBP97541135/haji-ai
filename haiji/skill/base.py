"""
skill/base.py - Skill 注册表、装饰器和工具函数

提供：
- @skill 装饰器：将函数或类注册为 Skill
- SkillRegistry：全局 Skill 注册表
- SkillSearcher：基于向量相似度的 Skill 检索
- build_prompt_fragment：将激活的 Skill 拼成 prompt 片段
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Optional, Union

from haiji.skill.definition import SkillEntry, XSkillDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """
    全局 Skill 注册表。

    所有通过 @skill 装饰的函数/类自动注册到这里。
    Agent 执行时从这里查找并激活所需 Skill。

    示例：
        registry = get_skill_registry()
        entry = registry.get("web_research")
        all_entries = registry.all()
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillEntry] = {}

    def register(self, entry: SkillEntry) -> None:
        """注册一个 Skill，若 code 已存在则覆盖并警告。"""
        code = entry.code
        if code in self._skills:
            logger.warning("[SkillRegistry] skill_code=%s 已存在，将被覆盖", code)
        self._skills[code] = entry
        logger.debug("[SkillRegistry] 注册 skill: %s", code)

    def get(self, code: str) -> Optional[SkillEntry]:
        """按 code 查找 Skill，不存在返回 None。"""
        return self._skills.get(code)

    def all(self) -> list[SkillEntry]:
        """返回所有已注册 Skill 列表。"""
        return list(self._skills.values())

    def all_codes(self) -> list[str]:
        """返回所有已注册 Skill 的 code 列表。"""
        return list(self._skills.keys())

    def __len__(self) -> int:
        return len(self._skills)


# 全局注册表单例
_registry = SkillRegistry()


def get_skill_registry() -> SkillRegistry:
    """获取全局 SkillRegistry 单例。"""
    return _registry


# ---------------------------------------------------------------------------
# @skill 装饰器
# ---------------------------------------------------------------------------


def skill(
    *,
    description: str,
    tools: Optional[list[Any]] = None,
    code: Optional[str] = None,
    name: Optional[str] = None,
    prompt_fragment: str = "",
) -> Callable:
    """
    @skill 装饰器，将函数或类注册为 Skill。

    可以装饰：
    - 一个普通函数（此时 Skill 本身不执行逻辑，只是元数据载体）
    - 一个类（约定类上有 prompt 属性作为 prompt_fragment 备用）

    Args:
        description:     Skill 功能描述，用于向量检索
        tools:           该 Skill 激活的 Tool 列表（函数或 XTool 实例均可）
        code:            Skill 唯一标识，默认用函数/类名
        name:            Skill 人类可读名称，默认用 code
        prompt_fragment: 注入给 LLM 的 prompt 片段；若装饰 class 且为空，
                         则尝试读取 class.prompt 属性

    示例::

        @skill(
            description="搜索网络获取最新信息",
            tools=[search_web, fetch_page],
            prompt_fragment="当用户需要查找信息时，优先使用 search_web 工具。",
        )
        class WebResearchSkill:
            pass

        @skill(description="基础计算能力", tools=[calculator])
        def math_skill():
            pass
    """

    def decorator(target: Any) -> Any:
        skill_code = code or (target.__name__ if hasattr(target, "__name__") else str(target))
        skill_name = name or skill_code

        # 收集 tool_codes
        tool_codes: list[str] = []
        for t in tools or []:
            # @tool 装饰的函数：有 _tool 属性（FunctionTool 实例）
            if hasattr(t, "_tool"):
                tool_codes.append(t._tool.tool_code)
            # XTool 子类实例
            elif hasattr(t, "tool_code"):
                tool_codes.append(t.tool_code)
            # 直接传字符串 code
            elif isinstance(t, str):
                tool_codes.append(t)
            else:
                logger.warning("[skill] 无法识别 tool=%r，跳过", t)

        # 优先用装饰器参数，其次读 class.prompt
        pf = prompt_fragment
        if not pf and isinstance(target, type):
            pf = getattr(target, "prompt", "") or ""

        skill_def = XSkillDef(
            code=skill_code,
            name=skill_name,
            description=description,
            tool_codes=tool_codes,
            prompt_fragment=pf,
        )

        entry = SkillEntry(
            definition=skill_def,
            skill_class=target if isinstance(target, type) else None,
        )
        _registry.register(entry)

        # 保留原始对象可以继续正常使用
        return target

    return decorator


# ---------------------------------------------------------------------------
# SkillSearcher - 基于向量相似度的 Skill 检索
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    计算两个向量的余弦相似度（纯 Python 实现，无需 numpy）。

    Args:
        a: 向量 A
        b: 向量 B

    Returns:
        float: 余弦相似度，范围 [-1, 1]；维度不同时返回 0.0
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SkillSearcher:
    """
    基于向量相似度的 Skill 检索器（升级点：相比 Java 版的关键词匹配，语义更准）。

    使用流程：
    1. 创建 SkillSearcher，传入 embed_fn（将文本转为向量的异步函数）
    2. 调用 index(skills) 为所有 Skill 构建索引（填充 embedding）
    3. 调用 search(query, top_k) 检索最相关的 Skill

    embed_fn 签名：
        async def embed_fn(texts: list[str]) -> list[list[float]]: ...

    示例::

        async def my_embed(texts):
            # 调用 embedding API
            ...

        searcher = SkillSearcher(embed_fn=my_embed)
        await searcher.index(registry.all())
        results = await searcher.search("我需要查找最新新闻", top_k=3)
    """

    def __init__(self, embed_fn: Optional[Callable] = None) -> None:
        """
        Args:
            embed_fn: 异步 embedding 函数，签名为
                      async (texts: list[str]) -> list[list[float]]
                      若为 None，则退化为基于 description 关键词的简单匹配。
        """
        self._embed_fn = embed_fn
        self._indexed_entries: list[SkillEntry] = []

    async def index(self, entries: list[SkillEntry]) -> None:
        """
        为 Skill 列表构建向量索引。

        若 embed_fn 未设置，则跳过向量化（仍可使用关键词匹配）。

        Args:
            entries: 待索引的 Skill 列表
        """
        self._indexed_entries = entries
        if not self._embed_fn or not entries:
            logger.debug("[SkillSearcher] embed_fn 未设置，跳过向量化")
            return

        texts = [e.definition.description for e in entries]
        try:
            embeddings: list[list[float]] = await self._embed_fn(texts)
            for entry, emb in zip(entries, embeddings):
                entry.definition.embedding = emb
            logger.info("[SkillSearcher] 完成向量索引，共 %d 个 Skill", len(entries))
        except Exception as exc:
            logger.error("[SkillSearcher] 向量化失败: %s", exc)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[tuple[SkillEntry, float]]:
        """
        检索与 query 最相关的 top_k 个 Skill。

        优先使用向量相似度；若无 embedding，则退化为 description 关键词匹配。

        Args:
            query:           用户查询文本
            top_k:           最多返回条数（防止 context 撑爆，上限 20）
            score_threshold: 分数阈值，低于此分数的结果丢弃

        Returns:
            list of (SkillEntry, score)，按分数降序排列
        """
        top_k = min(top_k, 20)  # 性能规范：候选池大小上限 20

        if not self._indexed_entries:
            return []

        # 判断是否有向量
        has_embedding = any(
            e.definition.embedding is not None for e in self._indexed_entries
        )

        if has_embedding and self._embed_fn:
            # 向量检索路径
            try:
                query_emb_list: list[list[float]] = await self._embed_fn([query])
                query_emb = query_emb_list[0]
                scored = [
                    (entry, _cosine_similarity(query_emb, entry.definition.embedding or []))
                    for entry in self._indexed_entries
                    if entry.definition.embedding is not None
                ]
            except Exception as exc:
                logger.warning("[SkillSearcher] 向量检索失败，降级关键词: %s", exc)
                scored = self._keyword_score(query)
        else:
            # 关键词匹配降级路径
            scored = self._keyword_score(query)

        # 过滤 + 排序
        filtered = [(e, s) for e, s in scored if s >= score_threshold]
        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered[:top_k]

    def _keyword_score(self, query: str) -> list[tuple[SkillEntry, float]]:
        """
        简单关键词匹配评分（降级方案）。

        将 query 按空格切分，统计命中 description 的词数，
        归一化到 [0, 1]。
        """
        words = query.lower().split()
        if not words:
            return [(e, 0.0) for e in self._indexed_entries]

        results = []
        for entry in self._indexed_entries:
            desc_lower = entry.definition.description.lower()
            hits = sum(1 for w in words if w in desc_lower)
            score = hits / len(words)
            results.append((entry, score))
        return results


# ---------------------------------------------------------------------------
# build_prompt_fragment - 将激活的 Skill 拼成 prompt 片段
# ---------------------------------------------------------------------------


def build_prompt_fragment(entries: list[SkillEntry]) -> str:
    """
    将激活的 Skill 列表拼成可直接注入 system prompt 的文本块。

    格式示例：
        ## 可用能力（Skills）

        ### 网络调研（web_research）
        当用户需要查找信息时，使用 search_web 工具...
        可用工具：search_web, fetch_page

        ### 计算能力（math_skill）
        ...

    Args:
        entries: 激活的 Skill 列表

    Returns:
        str: 格式化后的 prompt 片段；若列表为空则返回空字符串
    """
    if not entries:
        return ""

    lines: list[str] = ["## 可用能力（Skills）\n"]
    for entry in entries:
        d = entry.definition
        lines.append(f"### {d.name}（{d.code}）")
        if d.prompt_fragment:
            lines.append(d.prompt_fragment)
        if d.tool_codes:
            lines.append(f"可用工具：{', '.join(d.tool_codes)}")
        lines.append("")  # 空行分隔

    return "\n".join(lines).rstrip()
