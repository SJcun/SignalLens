"""数据库连接与会话管理。"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings


class Base(DeclarativeBase):
    """所有 SQLAlchemy 数据模型的声明基类。"""


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        """开启外键和 WAL，保证本地任务读写的正确性与并发能力。"""

        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_session() -> Generator[Session, None, None]:
    """为单次 API 请求提供数据库会话。"""

    with SessionLocal() as session:
        yield session


def create_schema() -> None:
    """创建开发期所需数据表；后续正式变更将切换到 Alembic。"""

    from . import models  # noqa: F401

    Base.metadata.create_all(engine)

