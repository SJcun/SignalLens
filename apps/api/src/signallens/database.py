"""数据库连接与会话管理。"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings
from .urls import normalize_content_url


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


def _add_sqlite_column(table: str, column: str, definition: str) -> None:
    """为开发期 SQLite 旧表补列，并容忍 API 与 Worker 同时迁移。"""

    try:
        with engine.begin() as connection:
            columns = {item["name"] for item in inspect(connection).get_columns(table)}
            if column not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
    except OperationalError:
        with engine.connect() as connection:
            migrated_columns = {
                item["name"] for item in inspect(connection).get_columns(table)
            }
        if column not in migrated_columns:
            raise


def create_schema() -> None:
    """创建开发期数据表，并补齐现有内容的唯一身份。"""

    from .models import (
        AdminUser,
        Analysis,
        AnalysisJob,
        AnalysisSchedule,
        ArticleFeedback,
        AuthSession,
        Content,
        ContentTranslation,
        PluginApiKey,
        UserProfileRecord,
    )

    # 这些模型虽未参与下方迁移逻辑，但必须在 create_all 前导入并注册元数据。
    _ = (
        AdminUser,
        AnalysisSchedule,
        ArticleFeedback,
        AuthSession,
        ContentTranslation,
        PluginApiKey,
        UserProfileRecord,
    )

    Base.metadata.create_all(engine)
    # create_all 不会修改旧表；历史反馈保留原偏差结论，新反馈开始记录用户明确等级。
    _add_sqlite_column("article_feedback", "preferred_recommendation", "VARCHAR(32)")
    _add_sqlite_column("user_profile", "calibration_decisions_json", "JSON")
    _add_sqlite_column("analysis_jobs", "immediate_requested_at", "DATETIME")
    _add_sqlite_column("analyses", "source_hash", "VARCHAR(64)")
    _add_sqlite_column("analyses", "section_index_json", "JSON")

    with SessionLocal.begin() as session:
        # 早期版本按随机 capture_id 保存，可能为同一网页创建多条内容。
        # 迁移时保留最新快照，并手动清理重复记录关联的未执行任务。
        contents = session.scalars(select(Content).order_by(Content.created_at.desc())).all()
        keepers: dict[tuple[str, str], Content] = {}
        for content in contents:
            canonical_url = normalize_content_url(content.canonical_url or content.source_url)
            content_key = (content.source_type, canonical_url)
            keeper = keepers.get(content_key)
            if keeper is None:
                content.canonical_url = canonical_url
                keepers[content_key] = content
                continue

            analysis_ids = session.scalars(
                select(Analysis.id).where(Analysis.content_id == content.id)
            ).all()
            if analysis_ids:
                session.query(AnalysisJob).filter(
                    AnalysisJob.analysis_id.in_(analysis_ids)
                ).delete(synchronize_session=False)
                session.query(Analysis).filter(Analysis.id.in_(analysis_ids)).delete(
                    synchronize_session=False
                )
            session.query(ContentTranslation).filter(
                ContentTranslation.content_id == content.id
            ).delete(synchronize_session=False)
            session.delete(content)

    # 内容类型参与唯一身份，避免未来网页快照与同 URL 的视频转录互相覆盖。
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS uq_contents_canonical_url"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_contents_source_canonical_url "
                "ON contents(source_type, canonical_url)"
            )
        )
