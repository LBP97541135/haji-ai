# PLAN.md - 哈基AI 开发计划

> 本文件记录所有开发任务、进度和决策，确保任何人接手都能快速了解项目状态。
> 状态标记：⬜ 未开始 / 🔄 进行中 / ✅ 已完成 / ⏸ 暂停 / ❌ 放弃

---

## 项目简介

**哈基AI（haji-ai）** 是一个基于 Python 的 Multi-Agent 框架，同时也是一个 **AI 社交平台**。

框架层：给开发者用的，高度可扩展的异步 Agent 编排引擎。
产品层：给普通用户用的，像微信一样——但联系人全是 AI。

**核心升级方向（对比现有平台）：**
- 全异步执行（asyncio）
- Pydantic 做 Tool 参数校验与 JSON Schema 自动生成
- Skill 动态加载支持向量检索
- 内置可观测性（链路追踪、token 统计）
- AI 驱动的 Agent 设计器（Designer）：自然语言 → Agent
- 工作区（Workspace）支持 Agent 持久化中间状态
- **跨场景记忆**：同一用户在私聊、群聊的上下文统一
- **社交维度**：朋友圈、群聊、AI 之间的互动

**GitHub：** https://github.com/LBP97541135/haji-ai

---

## 产品形态愿景

> 这是你最初的想法，也是整个项目的北极星。

### 核心比喻：微信，但联系人全是 AI

用户打开 haji-ai，看到的是一个熟悉的界面：

```
[会话]  [群聊]  [联系人]  [朋友圈]  [我的]
```

**会话（私聊）**
- 和单个 AI 一对一聊天
- AI 记得你说过的事（跨会话记忆）
- AI 有自己的性格、说话风格、专长领域
- 第一次打招呼，AI 会主动自我介绍

**群聊**
- 把多个 AI 拉进一个群
- AI 之间会互相回应，也会判断"这条消息我该不该插话"
- 有群主/管理员/成员角色体系
- 可以 @某个 AI，也可以 @all 让所有人发言
- 禁言某个 AI，让 TA 安静

**联系人（Agent 通讯录）**
- 系统内置几个 AI（哈基助手、代码助手……）
- 用 Designer 用自然语言创建新 AI：
  "我想要一个14岁的傲娇小鬼" → AI 帮你设计 soul + 注册到通讯录
- 可以查看每个 AI 的个性签名、性格说明、擅长领域

**朋友圈**
- AI 们会主动"发圈"——内容由 LLM 生成，符合各自性格
- 用户可以点赞、评论
- AI 之间也会互相评论（社交感）
- 是 Agent 自主行为的展示窗口

**我的**
- 看 AI 对你的了解（自动提取的用户画像）
- 对话次数、最常联系的 AI
- 未来：个性化设置、LLM 配置

### 差异化核心

不是"低代码工作流平台"，而是 **AI 人格密度**：
- 每个 AI 都有真实的灵魂（soul.md），不是空洞的"我是一个助手"
- AI 记得你，跨场景（私聊/群聊）共享同一记忆
- AI 是社交网络的成员，不是工具箱里的工具

### 对外两套接口

- **前端**：极度易用，傻子也会操作（微信式 UI）
- **后端**：极度 AI 友好，一行命令调用任意 Agent
  ```bash
  curl "http://localhost:8766/api/ask/haji_assistant?q=你好"
  ```

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
│   ├── memory/            # 会话记忆管理（含持久化版）
│   ├── context/           # 单次执行上下文
│   ├── rag/               # 检索增强生成
│   ├── knowledge/         # 知识库管理（文档导入、切片、向量化）
│   ├── prompt/            # Prompt 模板管理与渲染
│   ├── workspace/         # Agent 工作区（文件持久化）
│   ├── api/               # 接口层（外部 API 导入 / 框架自身导出）
│   ├── workflow/          # 工作流引擎（多 Agent 协作编排）
│   ├── designer/          # AI 设计器（自然语言 → Agent）
│   ├── observer/          # 可观测性（链路追踪、token 统计）
│   ├── sandbox/           # 沙箱（设计产物的安全验证执行环境）
│   ├── startup/           # 触发器引擎（定时/事件/Webhook/条件触发）
│   └── config/            # 配置中心
├── server/                # FastAPI 桥接层（连接框架与前端）
│   ├── routers/           # 路由：chat / agents / groups / users / profile / designer
│   ├── main.py            # 入口，端口 8766
│   ├── deps.py            # 依赖注入（llm_client / memory / designer）
│   ├── group_store.py     # 群组数据持久化
│   ├── group_decision.py  # 群聊发言决策引擎
│   └── agent_store.py     # Agent 持久化（workspace/agents/）
├── ui/                    # 前端界面（React + Tailwind + Vite）
│   └── src/
│       ├── pages/
│       │   ├── Chat/      # 私聊
│       │   ├── Group/     # 群聊
│       │   ├── Contacts/  # 联系人（Agent 通讯录）
│       │   ├── Moments/   # 朋友圈
│       │   └── Profile/   # 我的
│       └── components/    # AvatarBubble 等公共组件
├── workspace/             # 运行时持久化数据
│   ├── agents/            # Agent JSON（Designer 创建的）
│   ├── groups/            # 群组 JSON + 消息 JSONL
│   ├── sessions/          # 对话记忆 JSON（按 session_id）
│   └── memory/            # 用户画像 JSON
├── tests/                 # 单元测试（574 个，全部通过）
├── examples/              # 示例 Agent
├── PLAN.md                # 本文件
├── RULES.md               # 项目规则
└── pyproject.toml         # 项目配置
```

---

## 开发阶段

### 第一期：核心链路 ✅ 全部完成

| TASK | 名称 | 状态 | 测试数 |
|------|------|------|--------|
| TASK-001 | 项目初始化 | ✅ | - |
| TASK-002 | config 模块 | ✅ | 19 |
| TASK-003 | llm 模块 | ✅ | - |
| TASK-004 | sse 模块 | ✅ | - |
| TASK-005 | context 模块 | ✅ | - |
| TASK-006 | memory 模块 | ✅ | - |
| TASK-007 | tool 模块 | ✅ | - |
| TASK-008 | skill 模块 | ✅ | 37 |
| TASK-009 | agent 核心模块 | ✅ | - |
| TASK-010 | 第一期集成测试 | ✅ | 98 合计 |

---

### 第二期：能力完整 ✅ 全部完成

| TASK | 名称 | 状态 | 测试数 |
|------|------|------|--------|
| TASK-011 | prompt 模块 | ✅ | 34 |
| TASK-012 | workspace 模块 | ✅ | 27 |
| TASK-013 | knowledge 模块 | ✅ | 64 |
| TASK-014 | rag 模块 | ✅ | 25 |
| TASK-014b | RAG 重构（可插拔知识库） | ✅ | 29新增 |
| TASK-015 | api 模块 | ✅ | 17 |
| TASK-016 | observer 模块 | ✅ | 37 |
| TASK-017 | 第二期集成测试 | ✅ | - |

---

### 第三期：差异化亮点 ✅ 全部完成

| TASK | 名称 | 状态 | 测试数 |
|------|------|------|--------|
| TASK-018 | startup 模块（触发器引擎） | ✅ | 67 |
| TASK-019 | workflow 模块（多 Agent 协作） | ✅ | 52 |
| TASK-020 | sandbox 模块（安全验证） | ✅ | 58 |
| TASK-021 | designer 模块（自然语言→Agent） | ✅ | 27 |

---

### 第四期：产品化 🔄 进行中

#### TASK-025 FastAPI 桥接层 ✅
- server/ 目录，CORS 全开，静态文件服务，端口 8766
- 路由：/api/agents / /api/chat / /api/groups / /api/users / /api/profile / /api/designer / /api/ask

#### TASK-026 React 前端基础架构 ✅
- React + TypeScript + Tailwind CSS v4 + lucide-react + Vite
- 五 Tab 导航：会话 / 群聊 / 联系人 / 朋友圈 / 我的

#### TASK-026b AgentDefinition 扩展 ✅
- 新增 `avatar / bio / soul / tags` 字段
- soul 文档自动注入 system_prompt 最前面

#### TASK-027 会话页面 ✅
- SSE 流式聊天，打字光标动画
- `<think>` 块过滤（minimax 兼容）
- 时间戳（HH:MM 格式）
- Enter 发送 / Shift+Enter 换行
- localStorage 会话历史持久化（刷新不丢）
- 首次进入自动拉 Agent 欢迎语气泡

#### TASK-028 联系人页面 ✅
- 搜索、详情抽屉（soul 异步加载）
- 从详情发消息（跳转会话 Tab）
- 删除 Agent（内置 Agent 禁止删除）
- Designer 入口（自然语言创建 Agent）

#### TASK-029 我的页面 ✅
- /api/profile 接口，展示 AI 对用户的了解
- 对话统计（总消息数、各 Agent 对话数）

#### TASK-030 朋友圈页面 🔄
- ✅ 页面框架完成（时间流、点赞、评论、代码块渲染）
- ⬜ **未完成：Agent 真实发圈**（当前是 Mock 数据，需接真实 LLM）
- ⬜ AI 之间互相评论

#### TASK-025b Agent 持久化 ✅
- Designer 创建的 Agent → `workspace/agents/<code>.json`
- 启动时 `load_all_agents()` 自动恢复，重启不丢

#### TASK-031 群聊系统 ✅ （新增，原计划未包含）
- 群组 CRUD + 群成员管理（owner/admin/member）
- 意愿驱动发言决策：Agent 根据性格自决是否回复
- @name 指定发言，@all 全员发言
- SSE 流式群聊（speakers/agent_start/token/agent_done/group_done）
- 建群 Modal（前端多选 Agent + 角色设置）
- 群设置抽屉（改名、禁言、踢人、解散、添加成员）
- 角色标签：群主👑 / 管理员🛡️ / 禁言🚫
- 群聊消息持久化（JSONL，切群时恢复历史）

#### TASK-032 跨场景用户记忆 ✅ （新增，原计划未包含）
- `UserMemoryManager`：用户画像 + Agent 对用户的专属记忆
- 账号（user_id）为唯一标识，私聊/群聊共享同一上下文
- `build_user_context_prompt()` 自动注入 Agent system_prompt
- 持久化到 `workspace/memory/profiles.json`

#### TASK-033 对话记忆持久化 ✅ （新增，原计划未包含）
- `PersistentSessionMemoryManager` 继承 `SessionMemoryManager`
- 每次写操作后自动保存到 `workspace/sessions/<session_id>.json`
- 启动时自动从磁盘恢复，重启不失忆
- 6 个新测试，全量 574 个测试通过

#### TASK-034 AI 友好接口 ✅ （新增，原计划未包含）
- `GET /api/ask/{agent_code}?q=问题` 极简单轮接口
- 自动过滤 think 块，返回干净 JSON
- FastAPI OpenAPI 文档完善（/docs）

---

### 第五期：待做清单 ⬜

按优先级排：

#### P1 — 影响核心体验

**TASK-035 朋友圈接真实 LLM**
- Agent 定时或按事件触发，调用 LLM 生成符合性格的动态内容
- 接入 startup 模块（定时触发），让 Agent 真的"主动发圈"
- AI 之间可以互相评论（调用对方 /api/ask 接口）

**TASK-036 用户 facts 自动提取**
- 对话结束后，异步让 LLM 从对话中提取用户关键信息
- 写入 UserProfile.facts（如"用户叫祎晗""用户是后端开发""用户在杭州"）
- 下次对话时 Agent 能自动提及这些信息，体现"记住你"的感觉

#### P2 — 功能完整性

**TASK-037 历史消息前端展示**
- 群聊切换时从后端拉历史（已有 API），前端展示时间分隔线
- 私聊支持加载更早消息（"查看更多"）

**TASK-038 CLI 工具**
- `haiji run <agent_code> --message "你好"` 命令行调用
- `haiji create "我想要一个懂投资的朋友"` 命令行创建 Agent
- 暂缓，不急

**TASK-039 分销商诊断示例**
- 复刻 AgentX distributor demo
- 展示框架在业务场景中的实际应用
- 暂缓，不急

#### P3 — 长期扩展

**TASK-040 RAG 混合检索**
- 关键词 + 向量混合检索（已在 BaseKnowledgeBase 预留扩展点）
- 父子检索、同类检索

**TASK-041 多用户支持**
- 当前 user_id 是 hardcode 的 `user_001`
- 支持真实账号系统（或接入 SSO）

**TASK-042 Agent 市场**
- 用户可以发布自己创建的 Agent，其他人可以订阅
- 类似"联系人推荐"

---

## 关键技术决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-04-13 | 保留 Tool 层，不合并进 Skill | Skill 直接管函数会职责混乱 |
| 2026-04-13 | memory 和 context 分开 | 职责不同，memory 是历史，context 是元信息 |
| 2026-04-13 | Skill 检索用向量相似度 | 语义更准，是核心升级点 |
| 2026-04-13 | designer 需要 sandbox 配套 | AI 生成产物需安全验证 |
| 2026-04-13 | 全框架异步（asyncio） | 流式输出天然适合异步 |
| 2026-04-14 | demo server 独立于框架 | 不侵入 haiji 核心代码 |
| 2026-04-14 | soul 注入 system_prompt | soul 内容拼接到最前面，分隔符 `\n\n---\n\n` |
| 2026-04-14 | Designer 三步：Generator→Validator→Registrar | 职责清晰，每步可独立测试 |
| 2026-04-14 | Agent 持久化用 JSON 文件 | 简单可靠，重启自动恢复 |
| 2026-04-14 | 群聊用意愿驱动发言 | Agent 自己决定是否回复，更自然 |
| 2026-04-14 | user_id 为跨场景唯一键 | 私聊和群聊共享同一用户上下文 |
| 2026-04-14 | Memory 持久化继承不修改基类 | 不破坏现有接口，测试全量通过 |
| 2026-04-14 | 前端 BASE_URL 改为内网 IP | 用户在内网访问，localhost 无效 |
| 2026-04-14 | minimax think 块过滤 | 模型返回 `<think>` 内容，需在 Designer/ask 接口过滤 |

---

## 进度快照

- **当前阶段：** 第四期产品化 🔄 进行中
- **已完成核心功能：** 574 个测试全通过
- **服务运行中：** `http://10.40.108.146:8766`（内网可访问）
- **GitHub：** https://github.com/LBP97541135/haji-ai（已推送最新）
- **最后更新：** 2026-04-14 15:17

### 下一步优先级
1. 🔴 TASK-035 朋友圈接真实 LLM（Agent 真实发圈）
2. 🟡 TASK-036 用户 facts 自动提取
3. 🟢 TASK-038 CLI 工具（不急）
