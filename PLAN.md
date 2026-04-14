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

- **状态：** ✅ 已完成
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

- **状态：** ✅ 已完成
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

- **状态：** ✅ 已完成
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

- **状态：** ✅ 已完成
- **完成时间：** 2026-04-13 21:08
- **依赖：** TASK-007
- **目标：** Skill 的定义、注册和动态加载
- **具体任务：**
  - [x] `XSkillDef`：Skill 定义（code、name、description、tool_codes、prompt_fragment）
  - [x] `@skill` 装饰器（支持装饰函数和类，自动从 class.prompt 读取 prompt_fragment）
  - [x] `SkillRegistry`：注册表，支持按 code 查找
  - [x] `SkillEntry`：完整 Skill 信息（definition + skill_class 引用）
  - [x] `SkillSearcher`：向量相似度检索 + 关键词匹配降级；top_k 上限 20（性能规范）
  - [x] `build_prompt_fragment(skills)`：将激活的 Skill 拼成 system prompt 片段
  - [x] 纯 Python 余弦相似度实现（`_cosine_similarity`，无 numpy 依赖）
- **测试：** 37 个测试全通过，覆盖率 95%（skill 层 100%）
- **产出：** `haiji/skill/` 模块可用

---

#### TASK-009 agent 核心模块

- **状态：** ✅ 已完成
- **完成时间：** 2026-04-13 22:08
- **依赖：** TASK-006、TASK-007、TASK-008、TASK-004
- **目标：** Agent 基类 + 三种执行模式
- **下一次执行说明：**
  在 `haiji/agent/` 下实现以下文件：

  1. **`definition.py`**：
     - `AgentMode` 枚举：`DIRECT` / `REACT` / `PLAN_AND_EXECUTE`
     - `SubAgentContextStrategy` 枚举：`FRESH` / `FORK` / `FORK_LAST`
     - `AgentDefinition`（Pydantic）：`code`, `name`, `mode: AgentMode`, `system_prompt`, `required_skill_codes: list[str]`, `required_tool_codes: list[str]`, `max_rounds: int = 10`（性能规范）, `llm_config_override: Optional[dict]`
     - `AgentCallFrame`：多 Agent 互调时的调用帧（agent_code, session_id），用于防循环

  2. **`registry.py`**：
     - `AgentRegistry`：按 code 注册/查找 Agent 类；`register_class(cls)` / `get(code)` / `all_codes()`
     - `get_agent_registry()` 单例

  3. **`base.py`**：
     - `BaseAgent` 抽象基类（不需要 ABC，用 Pydantic 或普通类均可）
     - `prepare_execution(ctx: ExecutionContext, memory: SessionMemoryManager)` → 从 SkillRegistry 加载 Skill，收集 FunctionDef（LlmTool 列表），渲染 system_prompt（拼 build_prompt_fragment）
     - `stream_chat(user_message: str, ctx: ExecutionContext, emitter: SseEventEmitter)` → async，主入口
     - `execute_tool(tool_call: ToolCall, ctx: ToolCallContext, call_stack: list[AgentCallFrame])` → 调用 ToolRegistry；若 tool_code 与 AgentRegistry 中某 Agent 的 code 匹配，则走 Multi-Agent 互调路径（先检查 call_stack 防循环）
     - `DirectExecutor`：内部类，调用 LlmClient.chat 一次，输出结果
     - `ReactLoopExecutor`：内部类，while loop，最多 max_rounds 次；每轮：LLM 思考 → 若有 tool_calls 则执行 Tool → 结果追加到 memory → 再 LLM → 直到无 tool_calls 或超轮次；**流式输出每个 token 用 emitter.emit(SseEvent.token(...))**
     - `PlanExecuteExecutor`：先让 LLM 生成执行计划（list of steps），再顺序执行每步；第一期可以只做骨架，plan 步骤本质上是 Tool 调用序列

  4. **`impl/`**：三个 Executor 可以独立成文件，也可以都放 base.py，按实际复杂度决定

  5. **`__init__.py`**：只暴露 `AgentDefinition`, `AgentMode`, `BaseAgent`, `agent`, `get_agent_registry`

  **`@agent` 装饰器**（在 base.py 或单独文件）：
  ```python
  @agent(mode="react", skills=["web_research"], max_rounds=5)
  class MyAgent(BaseAgent):
      system_prompt = "你是一个助手..."
  ```
  装饰器只做注册（到 AgentRegistry）和元数据标记，不执行任何逻辑。

  **Multi-Agent 互调防循环**：
  - `call_stack: list[AgentCallFrame]` 随着调用链传递
  - 执行 tool 前：若 tool_code 是另一个 Agent，检查 call_stack 中是否已有该 agent_code + session_id 组合，有则抛 `AgentCircularCallError`
  - **注意**：防循环检测要有测试覆盖

  **关键性能约束**（来自 RULES.md 第五章）：
  - REACT 循环必须有 max_rounds 限制（默认 10），超出时终止并 emit error 事件
  - 流式 token buffer 大小上限 4096 tokens

  **测试要求**：
  - LLM 调用全部用 AsyncMock mock，不真实调用
  - 覆盖：DIRECT/REACT 正常执行、Tool 调用流程、超轮次终止、防循环检测
  - 覆盖率 >= 80%

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

- **状态：** ✅ 已完成
- **完成时间：** 2026-04-13 23:20
- **依赖：** TASK-009
- **目标：** 验证核心链路端到端可用
- **下一次执行说明：**
  在 `examples/hello_agent/` 下实现完整的端到端示例：

  1. **`hello_agent.py`**（DIRECT 模式）：
     - 注册一个 `@tool(description="获取当前时间")` 的 `get_time` 工具
     - 定义 `@agent(mode="direct")` 的 `HelloAgent`
     - `main()` 函数：创建 `ExecutionContext` + `SessionMemoryManager` + `SseEventEmitter`
     - 实例化 `OpenAILlmClient`（从 `.env` 读取 API Key）
     - 调用 `stream_chat()`，消费 `emitter.events()` 打印 token
     - 能用 `python3 examples/hello_agent/hello_agent.py` 跑起来

  2. **`react_agent.py`**（REACT 模式 + Tool 调用）：
     - 注册 `@tool` 的 `calculate` 工具（简单算术）
     - 定义 `@agent(mode="react", tools=["calculate"])` 的 `MathAgent`
     - 演示 LLM 调用工具 → 拿结果 → 最终回答的完整流程

  3. **`multi_agent.py`**（Multi-Agent 互调）：
     - 定义 `SubAgent`（DIRECT 模式，简单回答）
     - 定义 `MainAgent`（REACT 模式，将 `SubAgent` 作为 tool 调用）
     - 注意：`MainAgent` 的 `required_tool_codes` 中引用 `SubAgent` 的 code
     - 验证防循环检测（在 call_stack 里预置帧，调用时应 emit error）

  4. **`__init__.py`**：空文件

  注意事项：
  - 示例文件顶部加注释说明用法：`# Usage: python3 examples/hello_agent/hello_agent.py`
  - 示例不依赖真实 LLM Key 也能通过 mock 跑单测
  - 不需要额外单元测试（现有测试已覆盖），但要能手动验证可用
  - 如果 OpenAI Key 未配置，gracefully 提示用户设置 `HAIJI_API_KEY`

- **具体任务：**
  - [x] 写一个最简单的 Agent：接收问题，调用 Tool，流式输出答案（`hello_agent.py`，DIRECT 模式）
  - [x] 写一个 REACT 模式示例：MathAgent + calculate 工具（`react_agent.py`）
  - [x] 写一个 Multi-Agent 例子：MainAgent → SubAgent 互调（`multi_agent.py`）
  - [x] 验证防循环检测有效（demo_circular_detection，实测通过）
  - [x] 验证流式输出正常（导入测试 + 98 个单元测试全通过）
  - [x] 现有 98 个测试全部通过，无 regression
- **产出：** `examples/hello_agent/` 可运行示例（3 个脚本）
- **实际工时：** 约 1.5h（第一期核心链路已完备，示例接口直接可用）

---

### 第二期：能力完整

> 第一期完成后开始规划，任务详情待补充。

- **TASK-011** prompt 模块（模板加载、Jinja2 渲染、变量注入）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 00:20
  - **实现内容：**
    - `definition.py`：`PromptTemplate`（Pydantic, name/template/variables/description）、`PromptRenderResult`（content/template_name/variables_used）
    - `base.py`：`PromptRenderer`（Jinja2 StrictUndefined，变量缺失抛 PromptRenderError）、`PromptLoader`（异步加载 `.jinja2`/`.txt`，run_in_executor 异步化）、`TemplateRegistry`（注册/查找/批量注册/clear/len，全局单例 get/reset）
    - `__init__.py`：导出所有公共接口
  - **测试：** `tests/test_prompt.py`，34 个测试全通过，覆盖率 **98%**
  - **注意：** 需要 `pip install jinja2`（已在本机安装；pyproject.toml 已包含 jinja2>=3.1 依赖）
- **TASK-012** workspace 模块（Agent 工作区文件系统）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 01:20
  - **实现内容：**
    - `definition.py`：`WorkspaceEntry`（Pydantic, key/value/created_at/updated_at）、`WorkspaceInfo`（agent_code/session_id/base_path/entry_count）
    - `base.py`：`AgentWorkspace`（write/read/delete/list_keys/exists/info/get_entry），全异步（run_in_executor），key 格式正则校验（`^[a-zA-Z0-9_-]+$`），路径穿越防护（resolve + relative_to 双重检查），目录自动创建，多 workspace 隔离（agent_code + session_id 路径隔离）
    - `WorkspaceKeyNotFoundError`、`WorkspacePathTraversalError`、`WorkspaceError` 异常类
    - `__init__.py`：导出所有公共接口
  - **测试：** `tests/test_workspace.py`，27 个测试全通过，覆盖率 **98%**
  - **全套测试：** 159 个（含新增 27 个），全部通过，无 regression
- **TASK-013** knowledge 模块（文档导入、切片、向量化）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 02:08
  - **实现内容：**
    - `definition.py`：`DocumentChunk`、`KnowledgeDocument`、`ChunkConfig`、`KnowledgeStoreInfo` 四个 Pydantic 模型
    - `chunker.py`：`TextChunker`（按段落优先 + 字符上限合并/拆分 + overlap 重叠，纯 Python 实现）
    - `embedder.py`：`BaseEmbedder` 抽象基类、`OpenAIEmbedder`（openai SDK，批量一次请求，按 index 排序）、`MockEmbedder`（确定性随机单位向量，用于测试）
    - `store.py`：`InMemoryKnowledgeStore`（余弦相似度检索，纯 Python，支持增删查，重复 doc_id 自动覆盖）
    - `loader.py`：`KnowledgeLoader`（load_text / load_file，支持 .txt/.md，asyncio.run_in_executor 异步化）
    - `__init__.py`：导出所有公共接口
  - **注意：** config 中 `base_url` 字段实际为 `llm_base_url`，embedder 已兼容处理；`embedding_model` 用 getattr 降级为 "text-embedding-3-small"
  - **测试：** `tests/test_knowledge.py`，**64 个测试全通过**，覆盖率 **92.5%**（chunker 97% / store 100% / loader 93%）
  - **全套测试：** 223 个（含新增 64 个），全部通过，无 regression
- **TASK-014** rag 模块（检索增强执行流程）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 03:08
  - **依赖：** TASK-013（knowledge）、TASK-009（agent）、TASK-003（llm）
  - **目标：** 在 Agent 执行流程中集成知识库检索，将相关知识片段注入 system prompt 或用户消息
  - **实现内容：**
    - `definition.py`：`RagConfig`（Pydantic，top_k/score_threshold/inject_mode/max_inject_chars）、`RagResult`（chunks + injected_text）
    - `retriever.py`：`RagRetriever`（embed query → store.search → score_threshold 过滤 → 格式化并截断），全异步，可独立使用不依赖 Agent
    - `__init__.py`：导出 `RagConfig`, `RagResult`, `RagRetriever`
  - **测试：** `tests/test_rag.py`，**25 个测试全通过**，覆盖率 **97.67%**
  - **全套测试：** 248 个（含新增 25 个），全部通过，无 regression
- **TASK-014b** RAG 重构（可插拔知识库 + Agent 级别 RAG 集成）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 11:45
  - **依赖：** TASK-014（原始 RAG）、TASK-013（knowledge）
  - **目标：** 重构 RAG 模块，实现可插拔知识库 + Agent 级别 RAG 集成。核心原则：流程先跑通，但架构预留扩展空间（后期要支持关键词/向量混合检索、父子检索、同类检索等，所有扩展点用抽象接口隔离，不要写死）
  - **实现内容：**
    - `knowledge/base_kb.py`：新增 `KBResult`（内外知识库统一返回格式，含 score/doc_id/chunk_id/metadata）、`BaseKnowledgeBase`（可插拔抽象基类，含 search/on_before_search/on_after_search 钩子，预留混合检索/父子检索扩展点）
    - `knowledge/embedder.py`：新增 `QwenEmbedder`（qwen3-embedding-8b，通过 MaaS 平台调用，支持 batch_size 分批，维度 4096）
    - `knowledge/knowledge_base.py`：新增 `KnowledgeBase`（内置知识库实现，继承 BaseKnowledgeBase，当前为向量检索，预留混合检索注释，含 load_text/load_file/search/delete_doc/info 方法）
    - `knowledge/__init__.py`：导出新增类 `KBResult`, `BaseKnowledgeBase`, `KnowledgeBase`, `QwenEmbedder`
    - `rag/definition.py`：`RagResult.chunks` → `RagResult.results: list[KBResult]`（不再依赖 DocumentChunk）
    - `rag/retriever.py`：重构 `RagRetriever`，改为接受 `BaseKnowledgeBase` 而不是 `InMemoryKnowledgeStore + embedder`，内部直接调用 `kb.search`
    - `agent/base.py`：`@agent` 装饰器新增 `rag` 和 `rag_config` 参数；`BaseAgent.__init__` 创建 `_rag_retriever`；`_prepare_execution` 改为 async，支持 RAG 注入（inject_mode=system_suffix/user_prefix）；`_rag_retriever` 为 None 时完全走原路径
  - **测试：** `tests/test_rag.py` 重写（25 个测试，使用 MockKnowledgeBase 适配新 API）；`tests/test_knowledge.py` 新增 `TestKBResult`/`TestBaseKnowledgeBase`/`TestKnowledgeBase`/`TestQwenEmbedder`（29 个测试）；`tests/test_agent.py` 新增 RAG 集成测试（7 个测试）；**全套测试：530 个全部通过**
  - **关键设计：**
    - 外部知识库只需继承 `BaseKnowledgeBase` 并实现 `search` 方法即可无缝接入
    - `on_before_search`/`on_after_search` 钩子默认 no-op，便于后期扩展（query 改写、rerank 等）
    - `KnowledgeBase.search` 内部调用钩子 → embed → store.search → 重算 score → 过滤 → 钩子，流程清晰
    - Agent RAG 集成最小侵入：`_rag_retriever` 为 None 时零开销，原有代码路径完全不变
- **TASK-015** api 模块（外部 API 适配 + 框架自身 HTTP 导出）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 04:08
  - **依赖：** TASK-009（agent）、TASK-004（sse）
  - **目标：** 让 haiji 框架可以作为 HTTP 服务暴露，外部客户端可通过 REST / SSE 与 Agent 对话
  - **实现内容：**
    - `definition.py`：`ChatRequest`（session_id/user_id/agent_code/message/stream）、`ChatResponse`（session_id/content/usage）、`ApiError`（code/message，含 4 个静态工厂方法）
    - `server.py`：`HaijiServer` 类，`__init__(agent_registry, llm_client)` 外部注入，`create_app() → FastAPI`；三个路由：`GET /health`（健康检查）、`POST /chat`（非流式，asyncio.gather 并发收 token）、`POST /chat/stream`（SSE 流式，asyncio.create_task + async generator）；SSE 格式：`data: {json}\n\n`，每个事件含 type/content/tool_name 等字段；错误统一 `ApiError` 格式返回
    - `__init__.py`：导出 `ChatRequest`, `ChatResponse`, `ApiError`, `HaijiServer`
    - **依赖新增：** pyproject.toml 已添加 `fastapi>=0.100`, `httpx>=0.24`
  - **测试：** `tests/test_api.py`，**17 个测试全通过**，api 模块覆盖率 **89%**
  - **全套测试：** 265 个（含新增 17 个），全部通过，无 regression
- **TASK-016** observer 模块（链路追踪、token 统计）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 05:08
  - **依赖：** TASK-009（agent）、TASK-003（llm）
  - **目标：** 给 Agent 执行链路提供可观测性：每次 LLM 调用的 token 统计、每次 Tool 调用的耗时、完整的链路追踪（trace_id 贯穿全局）
  - **实现内容：**
    - `definition.py`：`TokenUsage`（prompt/completion/total tokens + add 累加方法）、`LlmCallSpan`（trace_id/agent_code/model/usage/latency_ms/error）、`ToolCallSpan`（trace_id/agent_code/tool_code/latency_ms/success/error）、`TraceRecord`（trace_id/agent_code/session_id/llm_spans/tool_spans，`total_tokens` 为计算属性对所有 LlmCallSpan.usage 求和）
    - `base.py`：`Observer` 类（start_trace/record_llm_call/record_tool_call/finish_trace/get_trace/all_traces/clear），全局单例 `get_observer()` / `reset_observer()`；`_LlmSpanContext`（async context manager，进入计时，退出记录 LlmCallSpan，set_usage 设置 token 用量）；`_ToolSpanContext`（async context manager，自动记录 success/error）；工厂函数 `llm_span_ctx()` / `tool_span_ctx()`
    - `__init__.py`：导出所有公共接口
  - **测试：** `tests/test_observer.py`，**37 个测试全通过**，覆盖率 **100%**
  - **全套测试：** 302 个（含新增 37 个），全部通过，无 regression
  - **下一次执行说明（已归入下一任务）：** 见 TASK-017
    在 `haiji/observer/` 下实现以下文件：
    1. **`definition.py`**（Pydantic 数据结构）：
       - `TokenUsage`：`prompt_tokens: int`、`completion_tokens: int`、`total_tokens: int`；`add(other)` 方法用于累加
       - `LlmCallSpan`：单次 LLM 调用的追踪记录，`span_id`（uuid）、`trace_id`、`agent_code`、`model`、`usage: TokenUsage`、`latency_ms: float`、`started_at: datetime`、`error: Optional[str]`
       - `ToolCallSpan`：单次 Tool 调用的追踪记录，`span_id`、`trace_id`、`agent_code`、`tool_code`、`latency_ms: float`、`started_at: datetime`、`success: bool`、`error: Optional[str]`
       - `TraceRecord`：一次完整 Agent 执行的汇总，`trace_id`、`agent_code`、`session_id`、`llm_spans: list[LlmCallSpan]`、`tool_spans: list[ToolCallSpan]`、`total_tokens: TokenUsage`（计算属性，对所有 LlmCallSpan.usage 求和）、`total_latency_ms: float`

    2. **`base.py`**（Observer 核心）：
       - `Observer` 类（不依赖任何上层模块）：
         - `start_trace(trace_id, agent_code, session_id) → TraceRecord`：开启一条新 trace，内存中记录
         - `record_llm_call(trace_id, span: LlmCallSpan) → None`：追加 LLM span 到对应 trace
         - `record_tool_call(trace_id, span: ToolCallSpan) → None`：追加 Tool span 到对应 trace
         - `finish_trace(trace_id) → TraceRecord`：标记 trace 结束，返回完整记录
         - `get_trace(trace_id) → Optional[TraceRecord]`：查询 trace
         - `all_traces() → list[TraceRecord]`：返回所有 trace（按时间倒序）
         - `clear() → None`：清空（测试用）
       - `get_observer() → Observer`：全局单例，`reset_observer()` 用于测试重置

       - **上下文管理器辅助类（都在 base.py）：**
         - `llm_span_ctx(observer, trace_id, agent_code, model)`：async context manager，进入时记时，退出时根据有无 exception 记录 LlmCallSpan（usage 由调用方传入 `set_usage(usage)` 设置）
         - `tool_span_ctx(observer, trace_id, agent_code, tool_code)`：async context manager，同上，自动记录 success/error

    3. **`__init__.py`**：导出 `Observer`, `get_observer`, `reset_observer`, `TokenUsage`, `LlmCallSpan`, `ToolCallSpan`, `TraceRecord`, `llm_span_ctx`, `tool_span_ctx`

    **设计要点：**
    - Observer 纯内存存储，不做 I/O（第一期不需要持久化）
    - 所有方法同步（不需要 async），因为只是写内存字典
    - `total_tokens` 是 `TraceRecord` 的计算属性（@property），不冗余存储
    - 上下文管理器用 `time.monotonic()` 计时（而不是 asyncio.sleep，避免阻塞热路径）
    - **不要** 在 observer 模块里 import agent/llm/tool 的任何东西，保持最底层无上层依赖

    **测试要求（`tests/test_observer.py`）：**
    - 覆盖：start_trace / record_llm_call / record_tool_call / finish_trace / get_trace / all_traces / clear
    - 覆盖：TokenUsage.add 累加、TraceRecord.total_tokens 计算属性
    - 覆盖：llm_span_ctx 正常退出 + 异常退出（error 字段是否正确）
    - 覆盖：tool_span_ctx 正常退出 + 异常退出
    - 覆盖：多 trace 并发（两个 trace_id 互不干扰）
    - 覆盖率 >= 80%
- **TASK-017** 第二期集成测试
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 06:08
  - **依赖：** TASK-011 ～ TASK-016（全部第二期模块）
  - **目标：** 验证第二期所有模块端到端联动可用：prompt → agent（with RAG + workspace + observer） → api 对外暴露
  - **实现内容：** 在 `examples/full_agent/` 下实现三个集成示例：
    1. **`rag_agent.py`**：RAG + workspace + observer 联动（MockEmbedder 建知识库 → query_kb Tool → REACT Agent → Observer 追踪 → AgentWorkspace 持久化），全部通过
    2. **`api_server.py`**：FastAPI HTTP 服务验证（GET /health、POST /chat 非流式、POST /chat/stream SSE 流式、404 错误处理），全部通过
    3. **`prompt_agent.py`**：Prompt 模板渲染验证（2 个 Jinja2 模板注册 → 含可选块渲染 → 变量缺失抛 PromptRenderError → 渲染结果注入 Agent），全部通过
  - **关键修复：** REACT 模式用 `chat_with_tools`（不是 `chat`）；DIRECT 模式用 `stream_chat` async generator；Jinja2 StrictUndefined 下可选变量需显式传 None
  - **全套测试：** 302 个测试全部通过，无 regression

---

### 第三期：差异化亮点

> 第二期完成后开始规划，任务详情待补充。

- **TASK-018** startup 模块（触发器引擎：定时/事件/Webhook/条件触发）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 07:08
  - **依赖：** TASK-009（agent）、TASK-004（sse）
  - **目标：** 让 Agent 可以被定时任务、外部事件、Webhook 或条件自动触发，无需人工发消息
  - **实现内容：**
    - `definition.py`：`TriggerKind`（str enum，CRON/EVENT/WEBHOOK/CONDITION）、`TriggerConfig`（Pydantic，含 condition_fn 支持）、`StartupConfig`（agent_code/trigger/session_id_factory/initial_message_template/enabled）、`TriggerEvent`（event_id/trigger_kind/event_name/payload/triggered_at）、`StartupResult`（含 duration_ms 计算属性）
    - `base.py`：`CronRunner`（纯 Python，支持 `*`/数字/`*/n`/枚举 四种格式，5 字段 cron 表达式，含周一到周日正确映射）；`StartupScheduler`（register/unregister/all_configs/fire_event 并发/fire_webhook/start/stop/get_results/clear_results/_check_cron_triggers/_check_condition_triggers/_execute）；`get_startup_scheduler()`/`reset_startup_scheduler()` 全局单例
    - `__init__.py`：导出所有公共接口
  - **测试：** `tests/test_startup.py`，**67 个测试全通过**，覆盖率 **91.11%**（definition 100% / base 89%）
  - **全套测试：** 369 个（含新增 67 个），全部通过，无 regression

- **TASK-019** workflow 模块（工作流引擎，支持 YAML 描述多 Agent 协作）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 08:08
  - **依赖：** TASK-009（agent）、TASK-018（startup 选用）
  - **目标：** 让多个 Agent 可以通过 Python 描述协作关系，按顺序或条件执行
  - **实现内容：**
    - `definition.py`：`StepKind`（str enum，AGENT/CONDITION/PARALLEL）、`WorkflowStep`（Pydantic，支持 agent_code/message_template/condition_expr/parallel_steps/next_step_id/else_step_id，递归自引用 model_rebuild）、`WorkflowDefinition`（Pydantic，workflow_id/name/steps/entry_step_id/max_total_steps=50，get_step 方法）、`WorkflowResult`（Pydantic，duration_ms 计算属性）
    - `base.py`：`WorkflowEngine`（run/异步执行/三种步骤处理）、线性流（next_step_id 链）、CONDITION（安全 eval，黑名单检查 import/__/exec/eval/open/os/sys/subprocess，受限 globals）、PARALLEL（asyncio.gather 并发子步骤）、消息模板渲染（`{{step_xxx_result}}` 替换，未找到则保留原始）、防死循环（max_total_steps 计数）；`WorkflowRegistry`（register/get/all_workflow_ids/clear/len，含 register 覆盖警告）；`get_workflow_registry()`/`reset_workflow_registry()` 全局单例；`@workflow` 装饰器（支持装饰实例和函数，类型校验）
    - `__init__.py`：导出所有公共接口
  - **测试：** `tests/test_workflow.py`，**52 个测试全通过**，覆盖率 **98.54%**（base.py 98% / definition.py 100% / __init__.py 100%）
  - **全套测试：** 421 个（含新增 52 个），全部通过，无 regression
- **TASK-020** sandbox 模块（设计产物安全验证执行环境）
  - **状态：** ✅ 已完成
  - **完成时间：** 2026-04-14 09:20
  - **依赖：** TASK-009（agent）
  - **目标：** 为 AI Designer 生成的代码/Agent 定义提供安全验证和隔离执行环境，禁止直接 exec()
  - **实现内容：**
    - `definition.py`：`SandboxResult`（success/output/error/executed_at/started_at/finished_at，duration_ms 计算属性）、`CodeArtifact`（code/artifact_type/description）、`SandboxPolicy`（allowed_imports/max_execution_ms/allow_network/allow_file_io）
    - `base.py`：`_ImportVisitor` + `_DangerousCallVisitor`（AST 访问器）；`CodeValidator`（纯 AST 静态分析，检查 import 白名单、危险调用 exec/eval/__import__/compile/open、危险属性 __builtins__/__class__ 等、原型链攻击，不执行任何代码）；`RestrictedExecutor`（先 validate 再 exec，安全 builtins 白名单，threading.Thread + join(timeout) 超时截断，daemon=True 不阻塞进程）；`get_default_policy()`（允许 json/re/datetime/math/random/collections/itertools 等安全模块）
    - `__init__.py`：导出所有公共接口
  - **关键修复：** `__builtins__` 作为 bare Name 节点需要 `visit_Name` 处理；`RestrictedExecutor` 需保留安全 builtins（print/len/range 等），不能用空 dict
  - **测试：** `tests/test_sandbox.py`，**58 个测试全通过**，覆盖率 **98.77%**（base.py 98% / definition.py 100% / __init__.py 100%）
  - **全套测试：** 479 个（含新增 58 个），全部通过，无 regression
- **TASK-021** designer 模块（AI 设计器，自然语言 → Agent/工作流定义）
  - **状态：** ⬜ 未开始
  - **依赖：** TASK-020（sandbox）、TASK-019（workflow）、TASK-009（agent）
  - **目标：** 让用户用自然语言描述需求，AI 自动生成 AgentDefinition / WorkflowDefinition Python 代码，并经过 sandbox 验证后返回可用的定义
  - **下一次执行说明：**
    在 `haiji/designer/` 下实现以下文件：

    1. **`definition.py`**（Pydantic 数据结构）：
       - `DesignRequest`：`user_message: str`（用户自然语言描述）、`design_type: str`（"agent" / "workflow"）、`context: Optional[str]`（已有代码或上下文）
       - `DesignResult`：`success: bool`、`generated_code: Optional[str]`（生成的 Python 代码）、`artifact_type: str`、`error: Optional[str]`、`sandbox_result: Optional[SandboxResult]`（沙箱验证结果）、`design_type: str`
       - `DesignerConfig`：`max_retries: int = 3`（验证失败后最多重试几次）、`model: Optional[str]`（可覆盖全局 LLM 模型）

    2. **`base.py`**（Designer 核心）：
       - `AgentDesigner` 类：
         - `__init__(llm_client: LlmClient, policy: Optional[SandboxPolicy] = None)`
         - `async design(request: DesignRequest, config: Optional[DesignerConfig] = None) → DesignResult`
         - 内部流程：
           1. 构造 system prompt（说明代码生成规范：必须用 `@agent` 或 `@workflow` 装饰器，禁止 import 非白名单模块）
           2. 调用 `LlmClient.chat()` 生成代码
           3. 提取代码块（```python ... ``` 之间的内容）
           4. 用 `CodeValidator.validate()` 验证
           5. 验证失败且 retries 未用完：将错误信息拼入下一轮 prompt 重试
           6. 返回 `DesignResult`
       - `_extract_code_block(text: str) → Optional[str]`：从 LLM 输出中提取 ```python ... ``` 代码块（正则提取）
       - 注意：Designer 本身不执行生成的代码（不调用 RestrictedExecutor），只做验证；调用者负责决定是否执行

    3. **`prompt.py`**（设计器 Prompt 模板，可选独立文件）：
       - `AGENT_DESIGN_SYSTEM_PROMPT`：告诉 LLM 如何生成合法的 Agent 代码
       - `WORKFLOW_DESIGN_SYSTEM_PROMPT`：告诉 LLM 如何生成合法的 Workflow 代码
       - Prompt 要包含：可用的 import 白名单、@agent/@workflow 装饰器使用示例、输出格式要求（```python 代码块```）

    4. **`__init__.py`**：导出 `DesignRequest`, `DesignResult`, `DesignerConfig`, `AgentDesigner`

    **依赖层级（严格遵守 RULES.md）：**
    - designer 依赖 sandbox（下层）、llm（下层）→ 合法
    - designer 不得 import agent/workflow 的具体类（只能用字符串生成代码，不实例化）

    **测试要求（`tests/test_designer.py`）：**
    - LLM 调用全部用 AsyncMock mock
    - 覆盖：成功生成代码 → 验证通过 → 返回 DesignResult.success=True
    - 覆盖：LLM 生成违规代码 → 验证失败 → 自动重试 → 重试成功
    - 覆盖：连续失败超过 max_retries → DesignResult.success=False
    - 覆盖：LLM 输出中没有代码块 → 优雅处理
    - 覆盖：_extract_code_block 提取正确
    - 覆盖率 >= 80%
- **TASK-022** cli 模块（命令行工具，`haiji run / create`）
- **TASK-023** 示例：分销商诊断 Agent（复刻 AgentX distributor demo）
- **TASK-024** 第三期集成测试 + 文档完善

### 第四期：前端 UI

> 第三期完成后开始规划，任务详情待补充。

- **TASK-025** FastAPI 桥接层（连接 haiji 核心框架与前端）✅ 已完成 2026-04-14
  - server/ 目录，独立 FastAPI 应用，CORS 全开，静态文件服务
  - GET /api/agents, POST /api/chat/stream (SSE), POST /api/chat, POST /api/designer/create
  - 内置两个 Demo Agent（哈基助手 + 代码助手），端口 8766
- **TASK-026** UI 基础架构（React + Tailwind + Vite 项目初始化，Tab 导航框架）✅ 已完成 2026-04-14
  - ui/ 目录，React + TypeScript + Tailwind CSS v4 + lucide-react
  - 微信风格三 Tab 导航（会话/联系人/我的），SSE 流式聊天，Agent 气泡
- **TASK-026b** AgentDefinition 扩展（soul/bio/avatar/tags）✅ 已完成 2026-04-14
  - AgentDefinition 新增 avatar/bio/soul/tags 字段
  - @agent 装饰器新增对应参数，soul 自动注入 system_prompt 最前面
- **TASK-021** Designer 模块（自然语言 → Agent 三步生成）✅ 已完成 2026-04-14
  - haiji/designer/：Generator + Validator + Registrar + Designer 门面类
  - 27 个测试，557 总测试全通过
  - 用法：result = await designer.design("我想要一个懂投资的朋友")
- **TASK-014b** RAG 重构（可插拔知识库）✅ 已完成 2026-04-14
  - BaseKnowledgeBase 抽象基类 + KnowledgeBase 内置实现 + QwenEmbedder
  - @agent(rag=kb) 一行开启 RAG，on_before/after_search 预留扩展钩子
- **TASK-027** 会话页面完善（think 过滤、时间戳、打字光标）🔄 进行中
- **TASK-028** 联系人页面（搜索、详情卡片、删除、Designer 入口）🔄 进行中
- **TASK-029** 我的页面（profile API、LLM 配置展示）🔄 进行中
- **TASK-030** 朋友圈页面（Agent 发圈、时间流、点赞/评论）🔄 进行中
- **TASK-025b** Agent 持久化（workspace/agents/JSON，重启不丢）🔄 进行中
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

- **当前阶段：** 第四期前端 UI 进行中
- **当前任务：** TASK-027~031 前端完善 + Agent 持久化
- **已完成任务数：** 26 / 36
- **第一期完成情况：** TASK-001 ～ TASK-010 全部 ✅，98 个测试通过
- **第二期完成情况：** TASK-011~017 全部 ✅，总测试数 363 个
- **第三期完成情况：** TASK-018~020 ✅（startup/workflow/sandbox），TASK-021 ✅（Designer），TASK-014b ✅（RAG重构），总测试数 557 个
- **第四期完成情况：** TASK-025 ✅（FastAPI桥接）；TASK-026 ✅（React前端基础）；TASK-026b ✅（AgentDefinition扩展）；进行中：TASK-027~031
- **最后更新：** 2026-04-14 12:00

### 第二期推进顺序（更新）

1. ✅ TASK-012 workspace 模块（已完成）
2. ✅ TASK-013 knowledge 模块（已完成）
3. ✅ TASK-014 rag 模块（已完成）
4. ✅ TASK-015 api 模块（已完成）
5. ✅ TASK-016 observer 模块（已完成）
6. **TASK-017 第二期集成测试**（下一个）：多模块联动端到端验证（RAG + workspace + observer + api）
