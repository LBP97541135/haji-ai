# RULES.md - 哈基AI 项目规则

> 本文件是项目的"宪法"。所有开发者（包括 AI）在动手之前必须读完。
> 与 PLAN.md 的分工：PLAN.md 记录"做什么、做到哪了"，RULES.md 记录"怎么做、不能做什么"。

---

## 零、执行机制

规则不是摆设，以下项目由 CI 自动检查，不通过不能合并：

| 检查项 | 工具 |
|--------|------|
| 代码格式 | `black --check` |
| 类型标注 | `mypy` |
| Lint | `ruff` |
| 测试通过 | `pytest` |
| 测试覆盖率 >= 80% | `pytest-cov` |
| 无硬编码密钥 | `detect-secrets` |

其余规则依赖 Code Review 执行。

---

## 一、项目理念（方向性，不可执行）

1. **易于调用优先**：任何功能，开发者用 3 行代码能跑起来才算真的好用
2. **AI 是一等公民**：框架本身要能被 AI 使用，Designer 是核心差异化能力
3. **渐进式复杂度**：简单场景不暴露复杂概念，复杂场景才解锁高级能力
4. **模块宁缺毋滥**：没想清楚的模块先留空，不为了完整性写出职责不清的代码

---

## 二、代码规范（CI 强制）

### 语言与版本
- Python >= 3.11
- 前端：React 18 + TypeScript + Tailwind CSS + Vite

### 格式与检查
- 格式化：`black`，行宽 100
- 类型检查：`mypy`，所有公共接口必须有类型标注
- Lint：`ruff`
- 所有公共函数、类、模块必须有 docstring（私有方法建议有，不强制）

### 命名规范
- Python：变量/函数用 `snake_case`，类用 `PascalCase`，常量用 `UPPER_SNAKE_CASE`
- 前端：组件文件用 `PascalCase.tsx`，其他文件用 `kebab-case.ts`
- 内部实现类加 `_` 前缀或不在 `__init__.py` 中导出

### 异步规范
- **所有 I/O 操作必须是 async**：LLM 调用、文件读写、网络请求
- 禁止在 async 函数里调用同步阻塞操作（用 `asyncio.sleep` 不用 `time.sleep`）
- CPU 密集型操作用 `asyncio.run_in_executor` 放到线程池

### 数据结构
- 所有数据类用 **Pydantic BaseModel**，不用普通 `dataclass`
- 对外暴露的接口参数必须有 Pydantic 校验
- Tool 的入参出参自动生成 JSON Schema，禁止手写

### 错误处理
- 禁止裸 `except Exception`，必须捕获具体异常类型
- 每个模块定义自己的异常类，继承自 `HaijiBaseException`
- 错误信息必须对用户友好，堆栈只打日志，不暴露给用户

---

## 三、模块规范（Code Review 执行）

### 模块独立性
- 每个模块必须可以独立测试，不依赖其他模块的具体实现
- 模块间通过**抽象基类**通信，不直接依赖具体实现类
- 禁止循环依赖

### 依赖方向（严格遵守，下层禁止 import 上层）
```
ui / cli
    ↓
api（FastAPI 桥接层）
    ↓
startup / workflow / designer
    ↓
agent
    ↓
skill / tool / memory / rag / knowledge / prompt / workspace
    ↓
llm / sse / context / observer / sandbox
    ↓
config
```

### 每个模块的文件结构
```
haiji/
└── {module}/
    ├── __init__.py      # 只暴露公共接口
    ├── base.py          # 抽象基类 / 接口定义
    ├── definition.py    # 数据结构（Pydantic Model）
    ├── registry.py      # 注册表（如果需要）
    └── impl/            # 具体实现
```

---

## 四、装饰器规范

框架核心交互方式是装饰器，必须简洁：

```python
# Tool：自动从函数签名生成 JSON Schema
@tool(description="搜索网络信息")
async def search_web(query: str, max_results: int = 5) -> str:
    ...

# Skill：关联 Tool + prompt 片段
@skill(code="web_research", tools=[search_web], description="网络调研能力")
class WebResearchSkill:
    prompt = "当用户需要查找信息时，使用 search_web..."

# Agent：最简洁的用法
@agent(mode="react", skills=[WebResearchSkill])
class ResearchAgent(BaseAgent):
    pass
```

- code 默认用函数/类名，不需要每次都写
- 装饰器不能有副作用，只做注册和元数据标记
- 装饰器参数越少越好，能推断的就推断

---

## 五、性能规范

- LLM 调用必须设置超时，默认 60s，最长不超过 300s
- REACT 循环必须有最大轮次限制（`max_rounds`），默认 10，防止死循环
- 流式输出的 token buffer 大小必须有上限，默认 4096 tokens
- Skill 动态加载的候选池大小有上限，默认 20 个，防止 context 撑爆
- 禁止在热路径（每次请求都会执行的代码）里做同步文件 I/O

---

## 六、日志规范

- 用 Python 标准 `logging`，**禁止用 `print` 调试**
- 每个模块用自己的 logger：`logger = logging.getLogger(__name__)`
- 日志级别规范：
  - `DEBUG`：详细执行过程（Tool 入参出参、LLM 完整请求）
  - `INFO`：关键节点（Agent 启动、Tool 调用、Skill 加载）
  - `WARNING`：非预期但可恢复的情况（循环调用检测、降级逻辑）
  - `ERROR`：需要关注的错误（LLM 调用失败、Tool 执行异常）
- **禁止将以下内容打进日志**：API Key、用户隐私数据、完整的 LLM 响应（生产环境）
- 长文本截断后再打日志，默认截断到 200 字符

---

## 七、安全规范

- API Key 等敏感信息只从**环境变量**或 `.env` 文件读取，**禁止硬编码**
- `.env` 文件加入 `.gitignore`，**禁止提交到 Git**
- Designer 生成的代码必须经过 sandbox 验证才能执行，禁止直接 `exec()`
- workspace 模块的文件操作必须限制在指定目录内，禁止路径穿越（`../` 攻击）
- 对外暴露的 API 必须有认证，禁止裸露的无认证接口

---

## 八、测试规范

- 测试框架：`pytest` + `pytest-asyncio`
- 每个模块必须有对应测试文件：`tests/test_{module}.py`
- 公共接口覆盖率 >= 80%（CI 强制）
- **LLM 调用在测试中必须 Mock**，不能真实调用（节省费用、保证稳定）
- 测试命名：`test_{功能描述}`，看名字就知道测什么

```python
# 好的测试命名
async def test_react_agent_stops_after_max_rounds():
    ...
async def test_agent_registry_prevents_circular_calls():
    ...

# 不好的测试命名
async def test_agent():  # 不知道测什么
    ...
```

---

## 九、Git 规范

### 分支策略
- `main`：随时可发布的稳定版本，**禁止直接 push**
- `dev`：日常开发主分支
- `feat/{task-id}-{简短描述}`：功能分支，如 `feat/task-007-tool-module`
- `fix/{简短描述}`：Bug 修复分支

### Commit 格式
```
{type}: {简短描述}

{可选的详细说明}
```
type 取值：`feat` / `fix` / `refactor` / `test` / `docs` / `chore`

### PR 规范
- 每个 PR 对应一个 TASK，描述里注明 TASK 编号
- 合并前必须通过所有 CI 检查
- 合并后立即更新 PLAN.md 中对应任务状态为 ✅

---

## 十、版本管理规范

遵循[语义化版本](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`

| 版本号 | 触发条件 | 示例 |
|--------|---------|------|
| MAJOR | 破坏性变更，公共 API 不兼容 | 装饰器参数改变 |
| MINOR | 新增功能，向下兼容 | 新增模块/新增参数 |
| PATCH | Bug 修复，向下兼容 | 修复执行异常 |

- 每次发版必须更新 `CHANGELOG.md`
- 第一期完成后发布 `0.1.0`，正式稳定后升到 `1.0.0`
- `0.x.x` 阶段不保证 API 稳定性，可自由破坏性变更

---

## 十一、文档规范

- 每个模块的 `__init__.py` 顶部写模块说明
- 公共接口必须有 docstring，包含：功能描述、参数说明、返回值、示例
- **PLAN.md**：记录任务进度、架构决策，完成任务立即更新
- **RULES.md**：记录开发规范，有新共识立即更新
- **CHANGELOG.md**：记录每个版本的变更，发版时更新
- 三个文件职责不重叠，不要把决策写进 RULES，不要把规范写进 PLAN

---

## 十二、贡献指南

### 新人入手顺序
1. 读完本文件
2. 读完 PLAN.md，了解当前进度
3. 从第一期未完成的任务中挑一个
4. 建 `feat/{task-id}-xxx` 分支开始开发
5. 写完测试，跑通 CI，提 PR

### 开发环境搭建
```bash
git clone https://github.com/xxx/haji-ai
cd haji-ai
pip install -e ".[dev]"   # 安装开发依赖
cp .env.example .env      # 填入你的 API Key
pytest                    # 跑测试确认环境正常
```

### 有问题找哪里
- 架构疑问：看 PLAN.md 的「关键决策记录」
- 规范疑问：看本文件对应章节
- 都没有：开 Issue 讨论，达成共识后更新到对应文件

---

## 红线（违反即打回，不讨论）

- 🚫 API Key 硬编码进代码
- 🚫 `.env` 文件提交到 Git
- 🚫 下层模块 import 上层模块
- 🚫 公司内部代码直接复制粘贴
- 🚫 Designer 生成的代码不经 sandbox 直接 `exec()`

---

---

## 附：用大白话讲，这份文档写了什么

**第零章：谁来检查规则**
不是靠人自觉，代码提交时电脑自动跑检查，格式不对、测试没过，直接不让合并。

**第一章：为什么做这个项目**
四句话的方向：好用、AI 能用、从简单到复杂、不确定就先不做。

**第二章：代码怎么写**
用什么版本的 Python、代码格式统一用工具自动处理、所有涉及网络文件的操作要用异步写法、数据结构统一用 Pydantic、报错要让用户看得懂。

**第三章：模块怎么组织**
每个模块独立可单独测试，模块之间有严格上下层关系，下层不能调用上层，就像地基不能依赖楼层。

**第四章：装饰器怎么用**
框架核心用法是三个装饰器 `@tool`、`@skill`、`@agent`，参数越少越好。

**第五章：性能底线**
调大模型最多等 60 秒，Agent 思考循环最多转 10 圈，不能让一个请求把内存撑爆。

**第六章：日志怎么打**
不用 print 用 logging，用户隐私和 API Key 不能出现在日志里，日志要分级别。

**第七章：安全底线**
API Key 不能写死在代码里，AI 生成的代码不能直接运行要先检查，文件操作不能越界访问。

**第八章：测试怎么写**
每个功能都要有测试，测试大模型时用假数据不要真调接口花钱，测试名字要一眼看出在测什么。

**第九章：Git 怎么用**
分支怎么命名、提交信息怎么写、合并代码之前要做什么。

**第十章：版本号怎么定**
大改动升第一位，新功能升第二位，修 bug 升第三位，每次发版要写清楚改了什么。

**第十一章：文档怎么维护**
三个文件各司其职：PLAN.md 记录做什么做到哪，RULES.md 记录怎么做，CHANGELOG.md 记录每个版本改了什么。

**第十二章：新人怎么上手**
第一次参与项目从哪里读、怎么搭环境、遇到问题找哪里。

**红线：五件绝对不能做的事**
API Key 不能硬编码、.env 不能提交、下层不能调上层、不能复制公司代码、AI 生成代码不能直接运行。

---

## 现阶段真正需要遵守的规则（项目初期）

其他规则等项目有雏形、有人协作时再认真执行。现在只需要记住这五条：

1. 代码格式用 `black` 自动处理，不用手动管缩进
2. 涉及网络和文件的操作都用 `async/await`
3. 数据结构用 Pydantic，不用普通 dict
4. API Key 放 `.env` 文件，绝对不写死在代码里
5. 完成一个任务，立即更新 PLAN.md 的状态

---

*最后更新：2026-04-13*
