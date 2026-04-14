"""
designer/generator.py - Agent 草稿生成器

职责：调用 LLM，根据用户自然语言描述生成 DesignDraft（Agent 草稿 JSON）。

关键特性：
1. 将当前系统已注册的 tools 和 skills 注入 prompt，LLM 只能从中选用
2. LLM 必须返回纯 JSON（无 markdown fence）
3. 解析失败时自动重试，最多重试 2 次
4. soul 字段由 LLM 生成，Markdown 格式，包含性格、说话风格、禁止项
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from haiji.designer.definition import DesignDraft, DesignRequest
from haiji.llm.base import LlmClient
from haiji.llm.definition import LlmMessage, LlmRequest
from haiji.skill.base import get_skill_registry
from haiji.tool.base import get_tool_registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt 模板
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
你是一个 AI Agent 设计师。用户会描述他想要的 AI 助手，你需要输出一个 JSON 结构来定义这个 Agent。

## 可用工具列表
{available_tools}

## 可用技能列表
{available_skills}

## 输出格式（严格 JSON，不要加 markdown fence）
{{
  "name": "Agent名称，简洁有辨识度",
  "avatar": "一个合适的 emoji",
  "bio": "个性签名，15字以内，一句话说清楚他是谁",
  "soul": "# 性格\\n...\\n# 说话风格\\n...\\n# 禁止\\n...",
  "mode": "direct 或 react（有工具调用选 react，否则 direct）",
  "tool_codes": ["只从可用工具列表中选，不存在的不要填"],
  "skill_codes": ["只从可用技能列表中选"],
  "tags": ["2-4个分类标签"],
  "rag_enabled": false,
  "reasoning": "你的设计理由，简短说明"
}}

## 规则
- tool_codes 和 skill_codes 必须从可用列表中选，不能凭空创造
- 如果没有合适的工具，tool_codes 填空列表，mode 用 direct
- soul 要有个性，不能千篇一律
- bio 不超过 15 字\
"""

# 最大重试次数（不含第一次）
_MAX_RETRIES = 2


class DesignerGenerator:
    """
    Agent 草稿生成器。

    使用 LLM 将用户自然语言描述转换为结构化的 DesignDraft。
    生成前会自动收集系统中已注册的 tools 和 skills，注入 prompt。

    示例::

        llm_client = MyLlmClient()
        generator = DesignerGenerator(llm_client)
        draft = await generator.generate(DesignRequest(description="一个懂投资的朋友"))
        print(draft.name)
    """

    def __init__(self, llm_client: LlmClient) -> None:
        """
        初始化生成器。

        Args:
            llm_client: LLM 客户端实例，需实现 LlmClient 抽象接口。
        """
        self._llm = llm_client

    async def generate(self, request: DesignRequest) -> DesignDraft:
        """
        根据用户设计请求生成 Agent 草稿。

        1. 收集已注册的 tools 和 skills
        2. 构造包含可用资源的 system prompt
        3. 调用 LLM（非流式 chat()）
        4. 解析 JSON → DesignDraft
        5. 解析失败则重试，最多 _MAX_RETRIES 次

        Args:
            request: 用户设计请求

        Returns:
            DesignDraft: LLM 生成的 Agent 草稿

        Raises:
            ValueError: 超过最大重试次数仍无法解析有效 JSON 时抛出
        """
        # Step 1: 收集可用 tools 和 skills
        available_tools = self._collect_tools()
        available_skills = self._collect_skills()

        # Step 2: 构造 system prompt
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            available_tools=available_tools,
            available_skills=available_skills,
        )

        # Step 3 & 4: 调用 LLM，重试解析
        user_content = request.description
        if request.preferred_mode:
            user_content += f"\n\n（偏好执行模式：{request.preferred_mode}）"

        last_error: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                logger.warning(
                    "[DesignerGenerator] 第 %d 次重试（上次错误：%s）",
                    attempt,
                    last_error,
                )

            messages = [
                LlmMessage.system(system_prompt),
                LlmMessage.user(user_content),
            ]

            # 若重试，追加错误提示让 LLM 修正
            if attempt > 0 and last_error is not None:
                messages.append(
                    LlmMessage.user(
                        f"上一次输出无法解析为 JSON，请重新输出，只输出纯 JSON，不要加 markdown fence。"
                        f"错误：{last_error}"
                    )
                )

            llm_request = LlmRequest(
                messages=messages,
                stream=False,
            )

            try:
                response = await self._llm.chat(llm_request)
                raw_content = response.content or ""
                draft = self._parse_draft(raw_content)
                logger.info(
                    "[DesignerGenerator] 成功生成草稿：name=%r mode=%r（第 %d 次尝试）",
                    draft.name,
                    draft.mode,
                    attempt + 1,
                )
                return draft
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                last_error = exc
                logger.warning(
                    "[DesignerGenerator] JSON 解析失败（第 %d 次）: %s",
                    attempt + 1,
                    exc,
                )

        raise ValueError(
            f"DesignerGenerator：超过最大重试次数 {_MAX_RETRIES}，"
            f"无法从 LLM 响应中解析出有效 DesignDraft。最后错误：{last_error}"
        )

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _collect_tools(self) -> str:
        """
        收集全局 ToolRegistry 中已注册的所有 tool codes。

        Returns:
            str: 格式化的 tool 列表字符串，注入 prompt。
                 空注册表时返回 "（暂无可用工具）"。
        """
        tool_registry = get_tool_registry()
        codes = tool_registry.all_codes()
        if not codes:
            return "（暂无可用工具）"
        lines = []
        for code in codes:
            tool = tool_registry.get(code)
            desc = tool.description if tool and hasattr(tool, "description") else ""
            lines.append(f"- {code}: {desc}" if desc else f"- {code}")
        return "\n".join(lines)

    def _collect_skills(self) -> str:
        """
        收集全局 SkillRegistry 中已注册的所有 skill codes。

        Returns:
            str: 格式化的 skill 列表字符串，注入 prompt。
                 空注册表时返回 "（暂无可用技能）"。
        """
        skill_registry = get_skill_registry()
        codes = skill_registry.all_codes()
        if not codes:
            return "（暂无可用技能）"
        lines = []
        for code in codes:
            entry = skill_registry.get(code)
            desc = entry.definition.description if entry else ""
            lines.append(f"- {code}: {desc}" if desc else f"- {code}")
        return "\n".join(lines)

    def _parse_draft(self, raw: str) -> DesignDraft:
        """
        将 LLM 原始输出解析为 DesignDraft。

        支持带/不带 markdown fence 的 JSON。

        Args:
            raw: LLM 返回的原始字符串

        Returns:
            DesignDraft: 解析后的草稿

        Raises:
            json.JSONDecodeError: JSON 格式无效时抛出
            ValueError: 内容为空时抛出
        """
        content = raw.strip()
        if not content:
            raise ValueError("LLM 返回空内容")

        # 过滤 <think>...</think> 块（minimax 等模型的思维链输出）
        import re as _re
        content = _re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        if not content:
            raise ValueError("LLM 返回空内容（过滤 think 块后）")

        # 尝试剥除 markdown fence（防御性处理）
        if content.startswith("```"):
            lines = content.splitlines()
            # 去掉第一行（```json 或 ```）和最后一行（```）
            inner_lines = lines[1:]
            if inner_lines and inner_lines[-1].strip() == "```":
                inner_lines = inner_lines[:-1]
            content = "\n".join(inner_lines).strip()

        data = json.loads(content)
        return DesignDraft(**{k: v for k, v in data.items() if k in DesignDraft.model_fields})
