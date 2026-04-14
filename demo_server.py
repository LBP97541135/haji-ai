"""
haji-ai Demo Server
在浏览器里直接测试框架各模块的功能
"""
import asyncio
import json
import time
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="haji-ai Demo", version="0.1.0")

# ── 各模块演示 ──────────────────────────────────────────────

def demo_config():
    from haiji.config import HaijiConfig, get_config, set_config, reset_config
    cfg = HaijiConfig(llm_model="gpt-4o", api_key="sk-demo-key", llm_timeout=30)
    set_config(cfg)
    c = get_config()
    reset_config()
    return {"llm_model": c.llm_model, "llm_timeout": c.llm_timeout, "api_key_set": bool(c.api_key)}

def demo_tool():
    from haiji.tool import tool, get_tool_registry
    registry = get_tool_registry()

    @tool(description="两数相加", code="demo_add")
    async def add(a: int, b: int) -> str:
        return str(a + b)

    entry = registry.get("demo_add")
    return {
        "registered": bool(entry),
        "tool_code": entry.tool_code if entry else None,
        "description": entry.description if entry else None,
        "parameters_schema": entry._schema if entry else None,
    }

async def demo_skill():
    from haiji.skill import skill, get_skill_registry, SkillSearcher

    @skill(code="math_skill", name="数学工具", description="提供基础数学计算能力", prompt_fragment="你擅长数学计算，可以做加减乘除。")
    class MathSkill:
        pass

    @skill(code="search_skill", name="搜索工具", description="提供网络信息检索能力", prompt_fragment="你可以搜索网络上的实时信息。")
    class SearchSkill:
        pass

    registry = get_skill_registry()
    searcher = SkillSearcher()
    await searcher.index(registry.all())
    results = await searcher.search("数学", top_k=5)
    return {
        "total_skills": len(registry.all()),
        "search_result": [{"name": e.definition.name, "score": round(score, 3)} for e, score in results],
    }

def demo_memory():
    from haiji.memory import SessionMemoryManager
    mgr = SessionMemoryManager(max_history=10)
    sid = "demo-session"
    mgr.add_user_message(sid, "你好！")
    mgr.add_assistant_message(sid, "你好，有什么可以帮你的？")
    mgr.add_user_message(sid, "今天天气怎么样？")
    history = mgr.get_history(sid)
    return {
        "session_id": sid,
        "message_count": len(history),
        "messages": [{"role": m.role, "content": m.content} for m in history],
    }

def demo_context():
    import uuid
    from haiji.context import ExecutionContext, ToolCallContext
    sid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    ctx = ExecutionContext(session_id=sid, agent_code="demo_agent", trace_id=tid, user_id="user_001")
    tool_ctx = ToolCallContext(
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        agent_code=ctx.agent_code,
        trace_id=ctx.trace_id,
    )
    return {
        "session_id": ctx.session_id[:16] + "...",
        "trace_id": ctx.trace_id[:16] + "...",
        "agent_code": ctx.agent_code,
        "user_id": ctx.user_id,
    }

def demo_sse():
    from haiji.sse import SseEventEmitter, SseEvent, SseEventType
    emitter = SseEventEmitter()
    emitter.emit(SseEvent.token("Hello"))
    emitter.emit(SseEvent.token(", "))
    emitter.emit(SseEvent.token("World!"))
    emitter.emit(SseEvent.done())
    events = []
    while True:
        try:
            ev = emitter._queue.get_nowait()
            events.append({"type": ev.type, "content": ev.content})
        except Exception:
            break
    return {"events": events, "total": len(events)}

def demo_prompt():
    from haiji.prompt import PromptRenderer, PromptTemplate, get_template_registry
    renderer = PromptRenderer()
    registry = get_template_registry()
    tpl = PromptTemplate(
        name="greeting",
        template="你好，{{ name }}！今天是 {{ date }}，有什么我可以帮你的吗？",
        variables=["name", "date"],
        description="问候模板",
    )
    registry.register(tpl)
    result = renderer.render(tpl, {"name": "祎晗", "date": "2026-04-14"})
    registry.clear()
    return {"rendered": result.content, "template_name": result.template_name}

async def demo_workspace():
    from haiji.workspace import AgentWorkspace
    ws = AgentWorkspace("/tmp/haiji_demo_ws", "demo_agent", "test_session")
    await ws.write("hello", "Hello, haji-ai!")
    await ws.write("counter", "42")
    value = await ws.read("hello")
    keys = await ws.list_keys()
    info = await ws.info()
    return {
        "read_value": value,
        "all_keys": keys,
        "entry_count": info.entry_count,
    }

def demo_observer():
    import asyncio
    from haiji.observer import get_observer, reset_observer, TokenUsage, LlmCallSpan, ToolCallSpan
    reset_observer()
    obs = get_observer()
    trace_id = "trace-demo-001"
    obs.start_trace(trace_id, "demo_agent", "session-001")
    llm_span = LlmCallSpan(
        trace_id=trace_id,
        agent_code="demo_agent",
        model="gpt-4o",
        usage=TokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        latency_ms=432.5,
    )
    obs.record_llm_call(trace_id, llm_span)
    tool_span = ToolCallSpan(
        trace_id=trace_id,
        agent_code="demo_agent",
        tool_code="search_web",
        latency_ms=220.0,
        success=True,
    )
    obs.record_tool_call(trace_id, tool_span)
    record = obs.finish_trace(trace_id)
    return {
        "trace_id": record.trace_id,
        "total_tokens": record.total_tokens.total_tokens,
        "llm_spans": len(record.llm_spans),
        "tool_spans": len(record.tool_spans),
        "llm_latency_ms": record.llm_spans[0].latency_ms,
    }

async def demo_knowledge():
    from haiji.knowledge import TextChunker, ChunkConfig, KnowledgeDocument, InMemoryKnowledgeStore, MockEmbedder
    text = "人工智能（AI）是计算机科学的一个分支。\n\n机器学习是AI的核心技术之一，通过数据训练模型。\n\n深度学习使用神经网络，在图像识别和自然语言处理中取得了突破。"
    doc = KnowledgeDocument(doc_id="doc-001", source="demo", content=text)
    chunker = TextChunker(ChunkConfig(chunk_size=100, overlap=20))
    chunks = chunker.chunk(doc)
    embedder = MockEmbedder(dim=8)
    # 为每个 chunk 生成 embedding
    chunks_with_embeddings = []
    for c in chunks:
        c.embedding = await embedder.embed(c.content)
        chunks_with_embeddings.append(c)
    store = InMemoryKnowledgeStore()
    store.add_document(doc, chunks_with_embeddings)
    query_vec = await embedder.embed("机器学习")
    results = store.search(query_vec, top_k=2)
    return {
        "total_chunks": len(chunks),
        "search_results": len(results),
        "top_chunk_preview": results[0].content[:50] if results else "",
    }

def demo_sandbox():
    from haiji.sandbox import CodeValidator, RestrictedExecutor, get_default_policy, CodeArtifact
    policy = get_default_policy()
    validator = CodeValidator()
    executor = RestrictedExecutor()

    safe_code = "result = sum([1, 2, 3, 4, 5])\nprint(f'Sum = {result}')"
    unsafe_code = "import os\nos.system('rm -rf /')"

    safe_artifact = CodeArtifact(code=safe_code, artifact_type="expression")
    unsafe_artifact = CodeArtifact(code=unsafe_code, artifact_type="expression")

    safe_result = validator.validate(safe_artifact, policy)
    unsafe_result = validator.validate(unsafe_artifact, policy)

    exec_result = executor.execute(safe_code, policy=policy)
    return {
        "safe_code_valid": safe_result.success,
        "unsafe_code_valid": unsafe_result.success,
        "unsafe_error": unsafe_result.error,
        "execution_output": exec_result.output.strip() if exec_result.success else exec_result.error,
        "execution_success": exec_result.success,
    }

def demo_workflow():
    from haiji.workflow import WorkflowDefinition, WorkflowStep, StepKind, WorkflowRegistry, get_workflow_registry
    registry = get_workflow_registry()
    wf = WorkflowDefinition(
        workflow_id="demo_wf",
        name="演示工作流",
        steps=[
            WorkflowStep(step_id="step1", kind=StepKind.AGENT, agent_code="agent_a", message_template="分析需求：{{input}}"),
            WorkflowStep(step_id="step2", kind=StepKind.AGENT, agent_code="agent_b", message_template="基于分析结果处理：{{step_step1_result}}"),
        ],
        entry_step_id="step1",
    )
    registry.register(wf)
    all_ids = registry.all_workflow_ids()
    registry.clear()
    return {
        "workflow_id": wf.workflow_id,
        "step_count": len(wf.steps),
        "registered": "demo_wf" in all_ids,
        "entry_step": wf.entry_step_id,
    }

def demo_startup():
    from haiji.startup import StartupScheduler, StartupConfig, TriggerConfig, TriggerKind
    scheduler = StartupScheduler()
    cfg = StartupConfig(
        agent_code="daily_report_agent",
        trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 9 * * 1-5"),
        initial_message_template="请生成今日日报",
        enabled=True,
    )
    scheduler.register(cfg)
    all_cfgs = scheduler.all_configs()
    return {
        "registered_agents": [c.agent_code for c in all_cfgs],
        "trigger_kind": all_cfgs[0].trigger.kind if all_cfgs else None,
        "cron_expr": all_cfgs[0].trigger.cron_expr if all_cfgs else None,
    }

# ── API Endpoints ──────────────────────────────────────────

MODULES = {
    "config": ("配置中心", "环境变量读取、全局单例、类型安全", demo_config),
    "tool": ("Tool 层", "@tool 装饰器、JSON Schema 自动生成、注册表", demo_tool),
    "skill": ("Skill 层", "Tool 组合、向量检索、Prompt 片段生成", demo_skill),
    "memory": ("Memory 模块", "多会话隔离历史、最大长度裁剪", demo_memory),
    "context": ("Context 模块", "执行上下文、trace_id 自动生成", demo_context),
    "sse": ("SSE 流式", "异步事件发射器、token/tool/done 事件", demo_sse),
    "prompt": ("Prompt 模板", "Jinja2 渲染、变量注入、模板注册表", demo_prompt),
    "workspace": ("Workspace 模块", "Agent 工作区文件系统、路径隔离", demo_workspace),
    "observer": ("Observer 可观测性", "链路追踪、Token 统计、耗时记录", demo_observer),
    "knowledge": ("Knowledge 知识库", "文档切片、向量化、相似度检索", demo_knowledge),
    "sandbox": ("Sandbox 沙箱", "AST 静态分析、受限执行环境、安全策略", demo_sandbox),
    "workflow": ("Workflow 工作流", "多 Agent 协作、条件分支、并行执行", demo_workflow),
    "startup": ("Startup 触发器", "Cron/事件/Webhook 触发 Agent", demo_startup),
}

@app.get("/api/modules")
def list_modules():
    return [{"id": k, "name": v[0], "desc": v[1]} for k, v in MODULES.items()]

@app.get("/api/demo/{module_id}")
async def run_demo(module_id: str):
    if module_id not in MODULES:
        return {"error": f"未知模块: {module_id}"}
    name, desc, fn = MODULES[module_id]
    start = time.time()
    try:
        if asyncio.iscoroutinefunction(fn):
            result = await fn()
        else:
            result = fn()
        elapsed = round((time.time() - start) * 1000, 1)
        return {"module": name, "desc": desc, "result": result, "elapsed_ms": elapsed, "ok": True}
    except Exception as e:
        return {"module": name, "desc": desc, "error": str(e), "ok": False}

@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>haji-ai 框架演示</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
  header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 24px 32px; border-bottom: 1px solid #2a2a4a; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 1.6rem; font-weight: 700; background: linear-gradient(90deg, #7c3aed, #06b6d4); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  header p { font-size: 0.85rem; color: #888; margin-top: 4px; }
  .badge { background: #7c3aed22; color: #a78bfa; border: 1px solid #7c3aed55; border-radius: 20px; padding: 3px 12px; font-size: 0.75rem; }
  .layout { display: grid; grid-template-columns: 280px 1fr; height: calc(100vh - 81px); }
  .sidebar { background: #12121f; border-right: 1px solid #2a2a4a; overflow-y: auto; padding: 16px 0; }
  .sidebar-title { font-size: 0.7rem; color: #555; text-transform: uppercase; letter-spacing: 1px; padding: 8px 20px; }
  .module-btn { width: 100%; text-align: left; background: none; border: none; cursor: pointer; padding: 10px 20px; color: #ccc; font-size: 0.88rem; transition: all 0.15s; border-left: 3px solid transparent; display: block; }
  .module-btn:hover { background: #1e1e35; color: #fff; }
  .module-btn.active { background: #1e1e35; color: #a78bfa; border-left-color: #7c3aed; }
  .module-btn .name { font-weight: 600; }
  .module-btn .desc { font-size: 0.75rem; color: #666; margin-top: 2px; line-height: 1.3; }
  .module-btn.active .desc { color: #888; }
  .main { padding: 32px; overflow-y: auto; }
  .welcome { text-align: center; padding: 80px 40px; color: #555; }
  .welcome h2 { font-size: 2rem; color: #333; margin-bottom: 12px; }
  .welcome p { font-size: 1rem; }
  .panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
  .panel-title { font-size: 1.3rem; font-weight: 700; color: #fff; }
  .panel-desc { font-size: 0.85rem; color: #888; margin-top: 4px; }
  .run-btn { background: linear-gradient(135deg, #7c3aed, #06b6d4); color: #fff; border: none; border-radius: 8px; padding: 10px 24px; font-size: 0.9rem; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }
  .run-btn:hover { opacity: 0.85; }
  .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .result-box { background: #12121f; border: 1px solid #2a2a4a; border-radius: 12px; padding: 24px; min-height: 200px; position: relative; }
  .result-box pre { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.82rem; line-height: 1.6; color: #c9d1d9; white-space: pre-wrap; word-break: break-all; }
  .status-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #555; }
  .status-dot.ok { background: #22c55e; box-shadow: 0 0 6px #22c55e88; }
  .status-dot.err { background: #ef4444; }
  .status-dot.loading { background: #f59e0b; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .elapsed { font-size: 0.78rem; color: #666; }
  .all-btn { background: #1e1e35; color: #a78bfa; border: 1px solid #2a2a4a; border-radius: 8px; padding: 8px 18px; font-size: 0.82rem; cursor: pointer; transition: all 0.2s; }
  .all-btn:hover { background: #2a2a4a; }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 28px; }
  .stat-card { background: #12121f; border: 1px solid #2a2a4a; border-radius: 10px; padding: 16px 20px; }
  .stat-num { font-size: 2rem; font-weight: 800; background: linear-gradient(90deg, #7c3aed, #06b6d4); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .stat-label { font-size: 0.78rem; color: #666; margin-top: 4px; }
  .json-key { color: #79c0ff; }
  .json-str { color: #a5d6ff; }
  .json-num { color: #f0883e; }
  .json-bool { color: #ff7b72; }
</style>
</head>
<body>
<header>
  <div>
    <h1>🦐 haji-ai 框架演示</h1>
    <p>Multi-Agent Framework — 点击左侧模块，实时查看运行结果</p>
  </div>
  <span class="badge">v0.1.0-dev · 479 tests passing</span>
</header>
<div class="layout">
  <nav class="sidebar" id="sidebar">
    <div class="sidebar-title">核心模块</div>
  </nav>
  <main class="main">
    <div class="stats">
      <div class="stat-card"><div class="stat-num">13</div><div class="stat-label">已完成模块</div></div>
      <div class="stat-card"><div class="stat-num">479</div><div class="stat-label">单元测试通过</div></div>
      <div class="stat-card"><div class="stat-num">20/31</div><div class="stat-label">任务进度</div></div>
    </div>
    <div id="content">
      <div class="welcome">
        <h2>🦐</h2>
        <p>从左侧选择一个模块，点击「运行演示」查看实时效果</p>
      </div>
    </div>
  </main>
</div>
<script>
let modules = [];
let current = null;

async function loadModules() {
  const res = await fetch('/api/modules');
  modules = await res.json();
  const sidebar = document.getElementById('sidebar');
  modules.forEach(m => {
    const btn = document.createElement('button');
    btn.className = 'module-btn';
    btn.id = 'btn-' + m.id;
    btn.innerHTML = `<div class="name">${m.name}</div><div class="desc">${m.desc}</div>`;
    btn.onclick = () => selectModule(m.id);
    sidebar.appendChild(btn);
  });
}

function selectModule(id) {
  current = id;
  document.querySelectorAll('.module-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + id).classList.add('active');
  const m = modules.find(x => x.id === id);
  document.getElementById('content').innerHTML = `
    <div class="panel-header">
      <div>
        <div class="panel-title">${m.name}</div>
        <div class="panel-desc">${m.desc}</div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="all-btn" onclick="runAll()">运行全部</button>
        <button class="run-btn" id="runBtn" onclick="runDemo('${id}')">▶ 运行演示</button>
      </div>
    </div>
    <div class="status-bar">
      <div class="status-dot" id="dot"></div>
      <span id="status-text" style="font-size:0.85rem;color:#666">点击「运行演示」执行</span>
      <span class="elapsed" id="elapsed"></span>
    </div>
    <div class="result-box"><pre id="output">等待运行...</pre></div>
  `;
}

function syntaxHighlight(json) {
  return json
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, match => {
      if (/^"/.test(match)) {
        if (/:$/.test(match)) return `<span class="json-key">${match}</span>`;
        return `<span class="json-str">${match}</span>`;
      }
      if (/true|false/.test(match)) return `<span class="json-bool">${match}</span>`;
      if (/null/.test(match)) return `<span class="json-bool">${match}</span>`;
      return `<span class="json-num">${match}</span>`;
    });
}

async function runDemo(id) {
  const dot = document.getElementById('dot');
  const status = document.getElementById('status-text');
  const elapsed = document.getElementById('elapsed');
  const output = document.getElementById('output');
  const btn = document.getElementById('runBtn');
  dot.className = 'status-dot loading';
  status.textContent = '运行中...';
  elapsed.textContent = '';
  output.innerHTML = '运行中...';
  btn.disabled = true;
  const start = Date.now();
  try {
    const res = await fetch('/api/demo/' + id);
    const data = await res.json();
    const ms = Date.now() - start;
    dot.className = 'status-dot ' + (data.ok ? 'ok' : 'err');
    status.textContent = data.ok ? '运行成功' : '运行失败: ' + data.error;
    elapsed.textContent = `${ms}ms`;
    output.innerHTML = syntaxHighlight(JSON.stringify(data.result || data, null, 2));
  } catch(e) {
    dot.className = 'status-dot err';
    status.textContent = '请求失败: ' + e.message;
    output.textContent = e.toString();
  }
  btn.disabled = false;
}

async function runAll() {
  for (const m of modules) {
    selectModule(m.id);
    await runDemo(m.id);
    await new Promise(r => setTimeout(r, 300));
  }
}

loadModules();
</script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
