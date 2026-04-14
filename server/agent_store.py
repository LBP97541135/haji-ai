"""
agent_store.py - Agent 持久化存储

将 AgentDefinition 序列化为 JSON 文件，存放在 workspace/agents/ 目录下。
Server 启动时自动扫描并恢复所有已存储的 Agent。
"""
import json
import os
from pathlib import Path
from haiji.agent.base import BaseAgent
from haiji.agent.definition import AgentDefinition, AgentMode
from haiji.agent.registry import get_agent_registry

STORE_DIR = Path(__file__).parent.parent / "workspace" / "agents"


def save_agent(definition: AgentDefinition) -> None:
    """将 AgentDefinition 序列化为 JSON 文件保存"""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / f"{definition.code}.json"
    data = definition.model_dump()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all_agents() -> int:
    """扫描 STORE_DIR，恢复所有已存储的 Agent，返回恢复数量"""
    if not STORE_DIR.exists():
        return 0
    registry = get_agent_registry()
    count = 0
    for path in STORE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            definition = AgentDefinition(**data)
            # 动态创建 Agent 类
            DynamicAgent = type(
                f"StoredAgent_{definition.code}",
                (BaseAgent,),
                {
                    "system_prompt": definition.system_prompt,
                    "_agent_definition": definition,
                    "_rag_kb": None,
                    "_rag_config": None,
                }
            )
            registry.register_class(DynamicAgent)
            count += 1
        except Exception as e:
            print(f"[agent_store] 恢复 {path.name} 失败: {e}")
    return count


def delete_agent(agent_code: str) -> bool:
    """删除持久化文件，返回是否成功"""
    path = STORE_DIR / f"{agent_code}.json"
    if path.exists():
        path.unlink()
        return True
    return False
