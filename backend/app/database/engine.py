from sqlalchemy.ext.asyncio import (
    create_async_engine,
)

from app.core.config import settings

# echo=False 关闭常规 SQL 输出；hide_parameters=True 进一步避免异常/日志暴露绑定参数值。
engine = create_async_engine(
    settings.database_url,
    echo=False,
    hide_parameters=True,
    pool_pre_ping=True,
)
