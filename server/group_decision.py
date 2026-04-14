"""
group_decision.py - 群聊发言决策引擎

轻量规则 + LLM 决策，决定哪些 Agent 要发言。
"""
from __future__ import annotations

import re
from haiji.agent.registry import get_agent_registry
from server.group_store import Group, GroupRole

# Demo 模式开关：False 时所有 Agent 直接发言，跳过决策
GROUP_DECISION_ENABLED = True


def _is_at_all(message: str) -> bool:
    """检测消息是否包含 @all / @全体"""
    return bool(re.search(r'@(all|全体|所有人)', message, re.IGNORECASE))


def _extract_at_names(message: str) -> list[str]:
    """提取消息中 @的名字列表"""
    return re.findall(r'@([^\s@]+)', message)


def _agent_is_relevant(agent_code: str, message: str) -> bool:
    """
    轻量规则：Agent 是否和消息相关。
    用 Agent 的 tags + bio 关键词做简单匹配。
    不相关 → 直接跳过，不调 LLM。
    """
    registry = get_agent_registry()
    cls = registry.get(agent_code)
    if not cls:
        return False
    d = cls._agent_definition

    # 收集 Agent 相关关键词
    keywords = []
    if d.tags:
        keywords.extend(d.tags)
    if d.bio:
        keywords.extend(d.bio.split())
    if d.name:
        keywords.append(d.name)

    # 消息太短（<= 5字）或关键词匹配 → 认为相关
    if len(message.strip()) <= 5:
        return True

    msg_lower = message.lower()
    for kw in keywords:
        if kw.lower() in msg_lower:
            return True

    # 默认：没有明显相关性，但 eager Agent 也参与
    # （懒/积极程度由 LLM 决策环节自行判断）
    return True  # 先全部进入 LLM 决策，让 LLM 自己判断


async def decide_speakers(
    group: Group,
    message: str,
    sender_user_id: str,
    sender_is_admin: bool,
    llm_client=None,
) -> list[str]:
    """
    返回本轮应该发言的 Agent code 列表（按发言顺序排序）。

    规则优先级：
    1. @all（且发送者是管理员/群主）→ 全员发言
    2. @name → 对应 Agent 必须发言
    3. GROUP_DECISION_ENABLED=False → 全员发言
    4. 轻量规则过滤 + LLM 决策
    """
    registry = get_agent_registry()
    all_codes = group.ordered_codes()

    # 过滤掉未注册的 Agent
    all_codes = [c for c in all_codes if registry.get(c) is not None]

    # 过滤禁言成员（禁言的 Agent 不参与任何发言，包括被 @）
    muted_codes = {m.agent_code for m in group.members if m.muted}
    all_codes = [c for c in all_codes if c not in muted_codes]

    if not all_codes:
        return []

    # 规则1：@all（且发送者有权限）
    if _is_at_all(message) and sender_is_admin:
        return all_codes

    # 规则3：关闭决策模式
    if not GROUP_DECISION_ENABLED:
        return all_codes

    # 提取 @mentions
    at_names = _extract_at_names(message)
    forced: set[str] = set()

    # 匹配 @name 到 agent_code（用 Agent 的 name 字段匹配）
    if at_names:
        for code in all_codes:
            cls = registry.get(code)
            if cls:
                agent_name = cls._agent_definition.name
                for at in at_names:
                    if at in agent_name or agent_name in at:
                        forced.add(code)

    # 规则4：LLM 决策（轻量）
    # 对非强制的 Agent，用简单 prompt 让其自决
    voluntary: list[str] = []

    for code in all_codes:
        if code in forced:
            continue

        cls = registry.get(code)
        if not cls:
            continue

        d = cls._agent_definition

        if llm_client is None:
            # 没有 LLM client → 全部参与
            voluntary.append(code)
            continue

        # 构造决策 prompt
        decision_prompt = f"""你是一个名叫"{d.name}"的AI，性格：{d.bio or '无特别描述'}。
群里有人发了这条消息："{message}"
请判断你是否需要回复这条消息。
规则：
- 如果消息和你的专长/性格完全无关，可以选择不回
- 如果消息有趣或你有话说，就回复
- 你的积极程度由你自己的性格决定

只回答 YES 或 NO，不要解释。"""

        try:
            from haiji.llm.definition import LlmMessage, MessageRole
            resp = await llm_client.chat(
                messages=[LlmMessage(role=MessageRole.USER, content=decision_prompt)],
                stream=False,
            )
            answer = (resp.content or "").strip().upper()
            if answer.startswith("Y"):
                voluntary.append(code)
        except Exception:
            # 决策失败 → 默认参与
            voluntary.append(code)

    # 合并：强制 + 自愿，保持顺序
    result = []
    for code in all_codes:
        if code in forced or code in voluntary:
            result.append(code)

    return result
