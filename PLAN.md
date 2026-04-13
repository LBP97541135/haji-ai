# PLAN.md - 哈基AI 开发计划

> 本文件记录所有开发任务、进度和决策，确保任何人接手都能快速了解项目状态。
> 状态标记：⬜ 未开始 / 🔄 进行中 / ✅ 已完成 / ⏸ 暂停 / ❌ 放弃

---

## 项目简介

**哈基AI（haji-ai）** 是一个基于 Python 的 Multi-Agent 框架，灵感来源于小红书内部 AgentX 平台，并在以下方向进行了升级：

- 全异步执行（asyncio）
- Pydantic 做 Tool 参数校验与 JSON Schema 自动生成
- Skill 动态加载支持向量检索
- 内置可观测性（链路追踪、token 统计）
- AI 驱动的 Agent 和工作流设计器（Designer）
- 工作区（Workspace）支持 Agent 持久化中间状态

**目标：** 易于调用，支持通过 AI 进行 Agent 设计和工作流设计。

**GitHub：** 待创建

---

## 整体架构

```
haji-ai/
├── haiji/                 # 核心框架包
│   ├── tool/              # Tool 层：最小执行单元
│   ├── skill/             # Skill 层：Tool 组合 + 使用规则
│   ├── agent/             # Agent 执行引擎（DIRECT / REACT / PLAN_AND_EXECUTE）
│   ├── llm/               # 大模型客户端（OpenAI 等）
│   ├── sse/               # 流式输出（SSE 事件发射器）
│   ├── memory/            # 会话记忆管理
│   ├── context/           # 单次执行上下文
│   ├── rag/               # 检索增强生成
│   ├── knowledge/         # 知识库管理（文档导入、切片、向量化）
│   ├── prompt/            # Prompt 模板管理与渲染
│   ├── workspace/         # Agent 工作区（文件持久化）
│   ├── api/               # 接口层（外部 API 导入 / 框架自身导出）
│   ├── workflow/          # 工作流引擎（多 Agent 协作编排）
│   ├── designer/          # AI 设计器（自然语言 → Agent/工作流）
│   ├── observer/          # 可观测性（链路追踪、token 统计、Inspector）
│   ├── sandbox/           # 沙箱（设计产物的安全验证执行环境）
│   ├── startup/           # 触发器引擎（定时/事件/Webhook/条件触发）
│   └── config/            # 配置中心
├── ui/                    # 前端界面（React + Tailwind + Vite）
│   ├── src/
│   │   ├── pages/
│   │   │   ├── chat/      # 会话（单聊 + 群聊）
│   │   │   ├── contacts/  # 联系人（Agent 管理）
│   │   │   ├── profile/   # 我的（个人配置）
│   │   │   └── moments/   # 朋友圈（Agent 社交）
│   │   └── components/    # 公共组件
│   └── package.json
├── cli/                   # 命令行工具
├── examples/              # 示例 Agent
│   └── distributor/       # 分销商诊断 Agent（参考 AgentX demo）
├── tests/                 # 单元测试
├── PLAN.md                # 本文件
├── RULES.md               # 项目规则
└── pyproject.toml         # 项目配置
```

---

## 开发阶段

### 第一期：核心链路（能跑起来）

目标：实现一个最简单的 REACT Agent，能调用 Tool，能流式输出。

---

#### TASK-001 项目初始化

- **状态：** ✅ 已完成
- **目标：** 建立项目骨架，配置开发环境
- **具体任务：**
  - [ ] 创建完整目录结构
  - [ ] 初始化 `pyproject.toml`（依赖：pydantic, openai, aiohttp, asyncio）
  - [ ] 创建各模块 `__init__.py`
  - [ ] 配置 `.gitignore`
  - [ ] 初始化 git 仓库
- **产出：** 可以 `pip install -e .` 安装的空框架
- **预计工时：** 1h

---

#### TASK-002 config 模块

- **状态：** ✅ 已完成
- **完成时间：** 2026-04-13 20:25
- **依赖：** TASK-001
- **目标：** 统一配置入口，所有模块从这里读取配置
- **具体任务：**
  - [x] `HaijiConfig` 数据类（Pydantic BaseSettings）
  - [x] 支持环境变量读取（`HAIJI_LLM_MODEL`、`HAIJI_API_KEY` 等，前缀 `HAIJI_`）
  - [x] 支持 `.env` 文件
  - [x] 全局单例访问 `get_config()`，以及 `set_config()` / `reset_config()` 用于测试
- **关键设计：**
  ```python
  from haiji import HaijiConfig, get_config
  config = get_config()                                    # 从环境变量 / .env 自动读取
  config = HaijiConfig(llm_model="gpt-4o", api_key="sk-xxx")  # 显式传参
  ```
- **产出：** `haiji/config/` 模块可用，测试 19 个全通过，覆盖率 100%

---

#### TASK-003 llm 模块

- **状态：** ✅ 已完成
- **下一次执行说明：** 在 haiji/llm/ 下实现以下文件：
  1. `definition.py`：定义 LlmMessage（role: system/user/assistant/tool, content, tool_call_id）、LlmRequest（messages, tools, temperature, max_tokens, stream）、LlmResponse（content, tool_calls, usage: prompt_tokens/completion_tokens/total_tokens）、LlmUsage、ToolCall（id, function_name, arguments_json）
  2. `base.py`：定义 LlmClient 抽象基类，方法 async chat(request) -> LlmResponse 和 async def stream_chat(request) -> AsyncGenerator[str, None]（token 流）
  3. `impl/openai_client.py`：OpenAILlmClient 实现，使用 openai 官方 SDK（openai.AsyncOpenAI），三层配置合并（runtime > agent > global），LLM 调用超时从 config.llm_timeout 取；Function Calling 参数用 tools 字段（openai 新格式）
  4. `__init__.py`：只导出公共接口
  - 注意：所有 I/O 操作必须 async，LLM 调用必须设置超时（config.llm_timeout），stream_chat 返回 async generator
  - 测试：用 unittest.mock 的 AsyncMock mock 掉 openai SDK，不要真实调用，覆盖率 >= 80%
- **依赖：** TASK-002
- **目标：** 封装大模型调用，支持流式和非流式，屏蔽厂商差异
- **具体任务：**
  - [ ] `LlmClient` 抽象接口（async）
  - [ ] `LlmConfig`：model、temperature、max_tokens、base_url
  - [ ] `LlmMessage`：system / user / assistant / tool 四种角色
  - [ ] `LlmRequest` / `LlmResponse` 数据结构
  - [ ] `OpenAILlmClient` 实现（基于 openai 官方 SDK）
  - [ ] 支持 Function Calling / Tool Calling
  - [ ] 支持流式输出（async generator）
  - [ ] 三层配置合并（runtime > agent > global）
- **关键设计：**
  ```python
  client = OpenAILlmClient(config)
  async for token in client.stream_chat(messages, tools):
      print(token)
  ```
- **产出：** `haiji/llm/` 模块可用，可独立测试
- **预计工时：** 4h

---

#### TASK-004 sse 模块

- **状态：** ✅ 已完成
- **依赖：** TASK-003
- **目标：** 统一的流式事件发射器，解耦执行层和输出层
- **具体任务：**
  - [ ] `SseEvent` 数据结构（type: token / tool_call / tool_result / done / error）
  - [ ] `SseEventEmitter` 类（async，基于 asyncio.Queue）
  - [ ] 支持管道链（Pipe Chain）：token 流经过滤/变换后输出
  - [ ] 内置 `JsonBlockBufferPipe`：缓冲 JSON 代码块，完整后再输出
  - [ ] 内置 `CodeBlockBufferPipe`：缓冲代码块
- **产出：** `haiji/sse/` 模块可用
- **预计工时：** 3h

---

#### TASK-005 context 模块

- **状态：** ⬜ 未开始
- **依赖：** TASK-001
- **目标：** 封装单次 Agent 执行的上下文信息
- **具体任务：**
  - [ ] `ExecutionContext` 数据类：session_id、user_id、trace_id、agent_code
  - [ ] `ToolCallContext`：Tool 执行时的上下文
  - [ ] trace_id 自动生成
- **产出：** `haiji/context/` 模块可用
- **预计工时：** 1h

---

#### TASK-006 memory 模块

- **状态：** ⬜ 未开始
- **依赖：** TASK-003、TASK-005
- **目标：** 管理多轮对话历史
- **具体任务：**
  - [ ] `SessionMemoryManager`：按 session_id 存储消息历史
  - [ ] 内存存储实现（默认）
  - [ ] 支持最大历史长度限制（防止 context 过长）
  - [ ] `add_user_message` / `add_assistant_message` / `add_tool_result`
  - [ ] `get_history(session_id)` 返回消息列表
- **产出：** `haiji/memory/` 模块可用
- **预计工时：** 2h

---

#### TASK-007 tool 模块

- **状态：** ⬜ 未开始
- **依赖：** TASK-005
- **目标：** Tool 的定义、注册和执行
- **具体任务：**
  - [ ] `XTool` 抽象基类：`tool_code`、`description`、`execute()`
  - [ ] `@tool` 装饰器：自动从函数签名 + Pydantic 生成 JSON Schema
  - [ ] `ToolRegistry`：全局注册表，支持按 code 查找
  - [ ] `ToolParam`：参数定义（名称、类型、描述、是否必填）
  - [ ] `FunctionDef`：LLM 可识别的工具定义格式（OpenAI function calling 格式）
  - [ ] 支持 async Tool
- **关键设计（对比 Java 版更简洁）：**
  ```python
  @tool(code="search_web", description="搜索网络信息")
  async def search_web(query: str, max_results: int = 5) -> str:
      # Pydantic 自动校验参数，自动生成 JSON Schema
      ...
  ```
- **产出：** `haiji/tool/` 模块可用
- **预计工时：** 4h

---

#### TASK-008 skill 模块

- **状态：** ⬜ 未开始
- **依赖：** TASK-007
- **目标：** Skill 的定义、注册和动态加载
- **具体任务：**
  - [ ] `XSkillDef`：Skill 定义（code、name、description、tool_codes、prompt_fragment）
  - [ ] `@skill` 装饰器
  - [ ] `SkillRegistry`：注册表，支持按 code 查找
  - [ ] `SkillEntry`：完整 Skill 信息（定义 + Tool 列表）
  - [ ] `SkillSearcher`：基于向量相似度的 Skill 检索（升级点，Java 版是关键词）
  - [ ] `build_prompt_fragment(skills)`：将激活的 Skill 拼成 prompt 片段
- **产出：** `haiji/skill/` 模块可用
- **预计工时：** 5h

---

#### TASK-009 agent 核心模块

- **状态：** ⬜ 未开始
- **依赖：** TASK-006、TASK-007、TASK-008、TASK-004
- **目标：** Agent 基类 + 三种执行模式
- **具体任务：**
  - [ ] `AgentDefinition`：Agent 元数据（code、mode、prompt、required_skills、required_tools 等）
  - [ ] `@agent` 装饰器
  - [ ] `AgentRegistry`：注册表，支持 Agent 互调
  - [ ] `AgentExecutionContext`：执行前准备好的上下文
  - [ ] `BaseAgent` 抽象基类：
    - `prepare_execution()`：加载 Skill、渲染 Prompt、收集 FunctionDef
    - `execute_agent()`：按 mode 分发执行
    - `stream_chat()`：主入口
    - `execute_tool()`：Tool 执行（含 Agent 互调拦截）
  - [ ] `DirectExecutor`：DIRECT 模式
  - [ ] `ReactLoopExecutor`：REACT 循环（思考→选工具→执行→再思考）
  - [ ] `PlanExecuteExecutor`：PLAN_AND_EXECUTE 模式
  - [ ] Multi-Agent 互调：调用栈防循环检测
  - [ ] 子 Agent 上下文策略：Fresh / Fork / ForkLast
- **产出：** `haiji/agent/` 模块可用，可以跑一个完整的 REACT Agent
- **预计工时：** 10h

---

#### TASK-010 第一期集成测试

- **状态：** ⬜ 未开始
- **依赖：** TASK-009
- **目标：** 验证核心链路端到端可用
- **具体任务：**
  - [ ] 写一个最简单的 Agent：接收问题，调用 Tool，流式输出答案
  - [ ] 写一个 Multi-Agent 例子：主 Agent 调用子 Agent
  - [ ] 验证防循环检测有效
  - [ ] 验证流式输出正常
  - [ ] 补充单元测试
- **产出：** `examples/hello_agent/` 可运行示例
- **预计工时：** 4h

---

### 第二期：能力完整

> 第一期完成后开始规划，任务详情待补充。

- **TASK-011** prompt 模块（模板加载、Jinja2 渲染、变量注入）
- **TASK-012** workspace 模块（Agent 工作区文件系统）
- **TASK-013** knowledge 模块（文档导入、切片、向量化）
- **TASK-014** rag 模块（检索增强执行流程）
- **TASK-015** api 模块（外部 API 适配 + 框架自身 HTTP 导出）
- **TASK-016** observer 模块（链路追踪、token 统计）
- **TASK-017** 第二期集成测试

---

### 第三期：差异化亮点

> 第二期完成后开始规划，任务详情待补充。

- **TASK-018** startup 模块（触发器引擎：定时/事件/Webhook/条件触发）
- **TASK-019** workflow 模块（工作流引擎，支持 YAML 描述多 Agent 协作）
- **TASK-020** sandbox 模块（设计产物安全验证执行环境）
- **TASK-021** designer 模块（AI 设计器，自然语言 → Agent/工作流定义）
- **TASK-022** cli 模块（命令行工具，`haiji run / create`）
- **TASK-023** 示例：分销商诊断 Agent（复刻 AgentX distributor demo）
- **TASK-024** 第三期集成测试 + 文档完善

### 第四期：前端 UI

> 第三期完成后开始规划，任务详情待补充。

- **TASK-025** FastAPI 桥接层（连接 haiji 核心框架与前端）
- **TASK-026** UI 基础架构（React + Tailwind + Vite 项目初始化，Tab 导航框架）
- **TASK-027** 会话页面（单聊 + 群聊，流式消息渲染）
- **TASK-028** 联系人页面（Agent 列表、添加 Agent、Designer 入口）
- **TASK-029** 我的页面（API Key 配置、工作区管理、全局设置）
- **TASK-030** 朋友圈页面（Agent 发圈、时间流、点赞/评论）
- **TASK-031** 前端集成测试 + UI 打磨

---

## 关键决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-04-13 | 保留 Tool 层，不合并进 Skill | Skill 直接管函数会职责混乱，workspace/api/knowledge 都需要统一的 Tool 层来连接 Agent |
| 2026-04-13 | memory 和 context 分开 | memory 是会话历史，context 是单次执行元信息，职责不同 |
| 2026-04-13 | Skill 检索用向量相似度 | Java 版是关键词匹配，向量检索语义更准，是核心升级点之一 |
| 2026-04-13 | designer 需要 sandbox 配套 | AI 生成的产物需要安全验证环境，防止有问题的逻辑直接运行 |
| 2026-04-13 | 全框架异步（asyncio） | 流式输出场景天然适合异步，并发性能更好 |
| 2026-04-13 | UI 技术栈选 React + Tailwind + Vite | 生态成熟、开发体验好、移动端适配方便；后端桥接用 FastAPI，与 haiji 异步架构天然契合 |
| 2026-04-13 | startup 作为独立模块 | 触发器引擎职责独立（什么时候做），与 workflow（怎么做）分开，配合使用 |
| 2026-04-13 | 朋友圈设计为第四期 | 依赖前三期的 startup（定时发圈）、agent（内容生成）、api（社交互动），最后做最稳 |

---

## 进度快照

- **当前阶段：** 第一期
- **当前任务：** TASK-003（llm 模块）
- **已完成任务数：** 2 / 31
- **最后更新：** 2026-04-13 20:30
