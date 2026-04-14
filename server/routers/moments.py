from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from server.moment_store import (
    load_all_moments, get_moment, update_moment, create_birth_moment
)

router = APIRouter()


@router.get("/moments")
def list_moments(limit: int = 50):
    moments = load_all_moments(limit=limit)
    return [
        {
            "id": m.id,
            "agent_code": m.agent_code,
            "agent_name": m.agent_name,
            "content": m.content,
            "created_at": m.created_at,
            "likes": m.likes,
            "comments": m.comments,
        }
        for m in moments
    ]


class CommentRequest(BaseModel):
    author: str = "用户"
    content: str
    author_code: str = ""


@router.post("/moments/{moment_id}/like")
def like_moment(moment_id: str):
    m = get_moment(moment_id)
    if not m:
        raise HTTPException(status_code=404, detail="Moment not found")
    m.likes += 1
    update_moment(m)
    return {"ok": True, "likes": m.likes}


@router.post("/moments/{moment_id}/comment")
def comment_moment(moment_id: str, req: CommentRequest):
    m = get_moment(moment_id)
    if not m:
        raise HTTPException(status_code=404, detail="Moment not found")
    m.comments.append({"author": req.author, "content": req.content, "author_code": req.author_code})
    update_moment(m)
    return {"ok": True, "comments": m.comments}
