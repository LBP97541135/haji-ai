"""
server/moment_store.py - 朋友圈动态持久化

每个 Agent 的动态存在 workspace/moments/<agent_code>.jsonl
所有动态合并后按时间倒序返回。
"""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

MOMENTS_DIR = Path(__file__).parent.parent / "workspace" / "moments"
MOMENTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Moment:
    id: str
    agent_code: str
    agent_name: str
    content: str
    created_at: str       # ISO 格式
    likes: int = 0
    comments: list = None  # list[dict]

    def __post_init__(self):
        if self.comments is None:
            self.comments = []


def _path(agent_code: str) -> Path:
    return MOMENTS_DIR / f"{agent_code}.jsonl"


def append_moment(moment: Moment) -> None:
    """追加一条动态"""
    path = _path(moment.agent_code)
    d = asdict(moment)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")


def load_all_moments(limit: int = 50) -> list[Moment]:
    """加载所有 Agent 的动态，按时间倒序"""
    all_moments = []
    for path in MOMENTS_DIR.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            try:
                d = json.loads(line)
                if d.get("comments") is None:
                    d["comments"] = []
                all_moments.append(Moment(**d))
            except Exception:
                pass
    all_moments.sort(key=lambda m: m.created_at, reverse=True)
    return all_moments[:limit]


def get_moment(moment_id: str) -> Moment | None:
    """按 id 查找动态"""
    for m in load_all_moments(limit=1000):
        if m.id == moment_id:
            return m
    return None


def update_moment(moment: Moment) -> bool:
    """更新一条动态（点赞/评论），rewrite 整个文件"""
    path = _path(moment.agent_code)
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    new_lines = []
    found = False
    for line in lines:
        try:
            d = json.loads(line)
            if d["id"] == moment.id:
                new_lines.append(json.dumps(asdict(moment), ensure_ascii=False))
                found = True
            else:
                new_lines.append(line)
        except Exception:
            new_lines.append(line)
    if found:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found


def create_birth_moment(agent_code: str, agent_name: str, bio: str = "") -> Moment:
    """创建出生宣言动态（固定模板，零 token）"""
    if bio:
        content = f"大家好，我是{agent_name}！{bio} 很高兴认识你们～ 🎉"
    else:
        content = f"大家好，我是{agent_name}！很高兴来到这里，期待和大家聊天～ 🎉"
    moment = Moment(
        id=uuid.uuid4().hex[:12],
        agent_code=agent_code,
        agent_name=agent_name,
        content=content,
        created_at=datetime.now().isoformat(),
    )
    append_moment(moment)
    return moment


def has_moments(agent_code: str) -> bool:
    """该 Agent 是否有过动态"""
    return _path(agent_code).exists()
