"""采集 API 的最小回归测试。"""

import os
from pathlib import Path

TEST_DB = Path(__file__).with_name("test.db")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"

from fastapi.testclient import TestClient

from signallens.database import engine
from signallens.main import app


def capture_payload() -> dict:
    """构造来自网页插件的有效采集请求。"""

    return {
        "schema_version": "signallens.capture.v1",
        "capture_id": "capture-test-0001",
        "source": {
            "type": "web",
            "url": "https://example.com/article",
            "title": "测试文章",
        },
        "document": {"format": "markdown", "text": "# 测试\n\n正文内容。", "units": []},
        "capture": {
            "mode": "manual",
            "producer": "pagesift-web",
            "producer_version": "0.3.1",
            "quality": {"level": "good", "warnings": []},
            "extraction_engine": "readability",
        },
    }


def test_health_and_idempotent_capture() -> None:
    """健康检查可用，重复 capture_id 返回同一任务。"""

    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        first = client.post("/api/v1/captures", json=capture_payload())
        second = client.post("/api/v1/captures", json=capture_payload())
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["analysis_id"] == second.json()["analysis_id"]


def teardown_module() -> None:
    """删除测试产生的临时 SQLite 文件。"""

    # Windows 需要先显式释放连接池，才能删除数据库文件。
    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{TEST_DB}{suffix}")
        if path.exists():
            path.unlink()
