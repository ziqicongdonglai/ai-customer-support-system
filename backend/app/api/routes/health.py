import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health"
)


# 动态读取 Alembic repository head，避免硬编码 revision；新增 migration 后旧数据库会自然变为未就绪。
def get_repository_migration_head() -> str:
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError("Repository must have exactly one migration head")
    return heads[0]

@router.get("")
def health_check():
    return {
        "status": "ok"
    }

@router.get("/db")
async def health_db(
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("SELECT 1"))

    return {
        "database": "connected"
    }


# 这里只判断 schema-aware readiness：数据库可连接且当前 Alembic revision 等于仓库唯一 head。
# 它不会执行 migration/seed，也不会检查 RAG、加载 Embedding Model 或调用 LLM。
@router.get("/ready")
async def health_ready(
    db: AsyncSession = Depends(get_db),
):
    try:
        expected_revision = get_repository_migration_head()
        current_revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
    # dependency 或 repository 检查失败统一安全降级为 503，避免泄露数据库凭据、原始 SQL 或内部异常细节。
    except Exception:
        logger.warning("event=health.readiness.failed reason=dependency_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        ) from None

    if current_revision != expected_revision:
        logger.warning("event=health.readiness.failed reason=migration_revision_mismatch")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        )

    return {"status": "ready"}
