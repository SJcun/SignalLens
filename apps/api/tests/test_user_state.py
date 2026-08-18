"""Current User State API、快照与分析关联的测试。"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

TEST_DB = Path(__file__).with_name("test.db")
TEST_BOOTSTRAP = Path(__file__).with_name("initial-admin-password.txt")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SIGNALLENS_BOOTSTRAP_PASSWORD_FILE"] = str(TEST_BOOTSTRAP)

from fastapi.testclient import TestClient

import signallens.main as main_module
import signallens.worker as worker_module
from signallens.analysis.schemas import AnalyzeContent, EvaluateForUser, TriageContent
from signallens.database import SessionLocal, create_schema, engine
from signallens.models import (
    Analysis,
    AnalysisJob,
    Content,
    CurrentUserStateRecord,
    CurrentUserStateSnapshot,
)
from signallens.worker import process_next_job


class FakeProvider:
    """为 Worker 回归测试提供确定性的三阶段结构化结果。"""

    model = "fake-test-model"

    def complete(self, *, system_prompt, user_prompt, output_model):
        """按输出模型类型返回最小有效结果。"""

        if output_model is TriageContent:
            return TriageContent(
                relevance="low",
                intrinsic_signal="low",
                novelty_signal="unknown",
                exploration_value="low",
                discovery_type="profile_match",
                decision="ignore",
                reason="测试模型的快速判断",
                why_outside_profile=None,
            )
        if output_model is AnalyzeContent:
            return AnalyzeContent(
                one_sentence_summary="文章介绍了一个值得验证的新方法。",
                summary="这是一段用于回归测试的内容分析。",
                content_profile={
                    "topics": ["测试"],
                    "content_type": "技术文章",
                    "difficulty": "introductory",
                },
                content_map=[],
                key_points=["关键点一"],
                claims=[],
                thesis=None,
                supporting_evidence=[],
                counterarguments=[],
                author_stance=None,
                limitations=[],
                unresolved_questions=[],
                unverified_claims=[],
            )
        if output_model is EvaluateForUser:
            return EvaluateForUser(
                relevance="medium",
                knowledge_overlap="low",
                known_or_redundant=False,
                novel_information=["关键点一"],
                exploration_value="medium",
                perspective_diversity="medium",
                discovery_type="adjacent",
                recommendation="selective_read",
                recommendation_reason="包含一项可快速验证的新信息",
                why_outside_profile=None,
                reading_plan=[
                    {"section": "关键点一", "action": "read", "reason": "验证新方法"}
                ],
            )
        raise AssertionError(f"未处理的输出模型：{output_model}")


def setup_module() -> None:
    """每个测试文件只建一次共享数据库结构。"""

    create_schema()


def teardown_module() -> None:
    """显式释放 SQLite 文件句柄，再删除临时数据库和凭据文件。"""

    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        Path(str(TEST_DB) + suffix).unlink(missing_ok=True)
    Path(str(TEST_BOOTSTRAP) + ".tmp").unlink(missing_ok=True)


def test_user_state_api_get_and_update() -> None:
    """当前阅读状态可以显式读取和保存。"""

    with TestClient(main_module.app) as client:
        password = next(
            line.removeprefix("password=")
            for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
            if line.startswith("password=")
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": password},
        )
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

        empty = client.get("/api/v1/user-state").json()
        assert empty["active_goals"] == []
        assert empty["available_minutes"] is None

        saved = client.put(
            "/api/v1/user-state",
            json={
                "active_goals": ["了解 Agent Memory 的可靠性设计"],
                "active_questions": ["怎样避免错误记忆被持续放大"],
                "focus_context": "正在设计 SignalLens Memory V1",
                "available_minutes": 20,
                "preferred_depth": "balanced",
                "exploration_level": "medium",
                "valid_until": "2026-09-01T00:00:00Z",
            },
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["active_goals"] == ["了解 Agent Memory 的可靠性设计"]
        assert body["available_minutes"] == 20
        assert body["updated_at"].endswith(("Z", "+00:00"))
        fetched = client.get("/api/v1/user-state").json()
        assert fetched["focus_context"] == "正在设计 SignalLens Memory V1"


def _upsert_state(**fields) -> None:
    """写入或更新单用户当前状态，容忍 API 测试已创建的行。"""

    with SessionLocal.begin() as session:
        record = session.get(CurrentUserStateRecord, "default")
        if record is None:
            record = CurrentUserStateRecord(id="default")
            session.add(record)
        for key, value in fields.items():
            setattr(record, key, value)


def _reset_state() -> None:
    """清空当前状态的全部字段，避免测试之间互相污染。"""

    _upsert_state(
        active_goals_json=[],
        active_questions_json=[],
        focus_context=None,
        available_minutes=None,
        preferred_depth=None,
        exploration_level=None,
        valid_until=None,
    )


def test_worker_creates_snapshot_before_evaluate(monkeypatch) -> None:
    """Evaluate 前创建不可变快照，并关联到 Analysis。"""

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(main_module, "utc_now", lambda: fixed_now)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    _upsert_state(active_goals_json=["设计 Memory V1"], available_minutes=30, preferred_depth="deep")

    with SessionLocal.begin() as session:
        content = Content(
            capture_id="capture-state-0001",
            source_type="web",
            source_url="https://example.com/state",
            canonical_url="https://example.com/state",
            capture_mode="manual",
            title="State 测试文章",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])

    assert process_next_job(FakeProvider()) is True

    with SessionLocal() as session:
        stored = session.get(Analysis, analysis.id)
        assert stored.status == "completed"
        assert stored.current_user_state_snapshot_id is not None
        snapshot = session.get(CurrentUserStateSnapshot, stored.current_user_state_snapshot_id)
        assert snapshot.payload_json["active_goals"] == ["设计 Memory V1"]
        assert snapshot.payload_json["available_minutes"] == 30
        assert snapshot.payload_json["preferred_depth"] == "deep"


def test_worker_reuses_snapshot_when_state_changed_afterwards(monkeypatch) -> None:
    """快照创建后修改状态，不重写历史分析使用的快照。"""

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(main_module, "utc_now", lambda: fixed_now)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    _reset_state()
    _upsert_state(active_goals_json=["旧目标"])

    with SessionLocal.begin() as session:
        content = Content(
            capture_id="capture-state-0002",
            source_type="web",
            source_url="https://example.com/state-2",
            canonical_url="https://example.com/state-2",
            capture_mode="manual",
            title="State 复用测试",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])

    assert process_next_job(FakeProvider()) is True
    snapshot_id = None
    with SessionLocal() as session:
        stored = session.get(Analysis, analysis.id)
        snapshot_id = stored.current_user_state_snapshot_id
        assert session.get(CurrentUserStateSnapshot, snapshot_id).payload_json == {
            "active_goals": ["旧目标"],
            "active_questions": [],
            "focus_context": None,
            "available_minutes": None,
            "preferred_depth": None,
            "exploration_level": None,
        }

    # 用户修改状态；历史快照与 Analysis 关联保持不变。
    with SessionLocal.begin() as session:
        record = session.get(CurrentUserStateRecord, "default")
        record.active_goals_json = ["新目标"]
        record.updated_at = fixed_now
    with SessionLocal() as session:
        stored = session.get(Analysis, analysis.id)
        assert stored.current_user_state_snapshot_id == snapshot_id


def test_expired_state_falls_back_to_conservative_defaults(monkeypatch) -> None:
    """状态过期后 Evaluate 使用空状态保守默认值，不阻止分析。"""

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(main_module, "utc_now", lambda: fixed_now)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    _reset_state()
    _upsert_state(
        active_goals_json=["已经过期的目标"],
        valid_until=fixed_now - timedelta(hours=1),
    )

    with SessionLocal.begin() as session:
        content = Content(
            capture_id="capture-state-0003",
            source_type="web",
            source_url="https://example.com/state-3",
            canonical_url="https://example.com/state-3",
            capture_mode="manual",
            title="State 过期测试",
            markdown="# 第一章\n\n正文。",
            capture_quality="good",
            capture_payload_json={},
        )
        analysis = Analysis(content=content)
        session.add_all([content, analysis, AnalysisJob(analysis=analysis)])

    assert process_next_job(FakeProvider()) is True
    with SessionLocal() as session:
        stored = session.get(Analysis, analysis.id)
        assert stored.status == "completed"
        snapshot = session.get(CurrentUserStateSnapshot, stored.current_user_state_snapshot_id)
        assert snapshot.payload_json["active_goals"] == []
