"""知识库管理接口（文档 RAG 入库 / 检索）。

放到 app/api/v1/knowledge.py。

- POST /api/v1/knowledge        贴一段文本入库
- POST /api/v1/knowledge/file   上传 .txt/.md 文件入库
- GET  /api/v1/knowledge/search?q=...  直接测检索
都需要登录（复用 auth 的 get_current_user）。
"""

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field

from app.api.v1.auth import get_current_user
from app.core.logging import logger
from app.models.user import User
from app.services import rag

router = APIRouter()


class KnowledgeAddRequest(BaseModel):
    """文本入库请求。"""

    content: str = Field(..., min_length=1, description="要入库的文本内容")
    source: str = Field(default="api-text", max_length=200, description="来源标注")


@router.post("")
async def add_knowledge(req: KnowledgeAddRequest, user: User = Depends(get_current_user)):
    """把一段文本切块、向量化后写入知识库。"""
    try:
        n = rag.add_document(req.content, source=req.source)
    except Exception as e:
        logger.exception("knowledge_add_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    return {"chunks_added": n, "source": req.source}


@router.post("/file")
async def add_knowledge_file(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """上传一个 .txt / .md 文件入库。"""
    data = await file.read()
    text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(status_code=400, detail="文件为空或无法解码为文本")
    try:
        n = rag.add_document(text, source=file.filename or "upload")
    except Exception as e:
        logger.exception("knowledge_file_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    return {"chunks_added": n, "source": file.filename}


@router.get("/search")
async def search_knowledge(q: str, user: User = Depends(get_current_user)):
    """直接测检索效果（调试用）。"""
    try:
        return {"results": rag.search(q)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))