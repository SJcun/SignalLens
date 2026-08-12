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
    """同一网页的不同提交只保留一条内容，并返回北京时间可解析的时间。"""

    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        first = client.post("/api/v1/captures", json=capture_payload())
        repeated_payload = capture_payload()
        repeated_payload["capture_id"] = "capture-test-0002"
        repeated_payload["source"]["url"] = (
            "https://example.com/article/?utm_source=test&from=inbox#section"
        )
        repeated_payload["document"]["text"] = "# 测试\n\n更新后的正文。"
        second = client.post("/api/v1/captures", json=repeated_payload)
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["content_id"] == second.json()["content_id"]
        assert first.json()["analysis_id"] == second.json()["analysis_id"]

        contents = client.get("/api/v1/contents")
        assert contents.status_code == 200
        assert len(contents.json()) == 1
        assert contents.json()[0]["title"] == "测试文章"
        assert contents.json()[0]["analysis_status"] == "pending"
        created_at = contents.json()[0]["created_at"]
        assert created_at.endswith(("Z", "+00:00"))

        detail = client.get(f"/api/v1/contents/{first.json()['content_id']}")
        assert detail.status_code == 200
        assert detail.json()["markdown"] == "# 测试\n\n更新后的正文。"


def teardown_module() -> None:
    """删除测试产生的临时 SQLite 文件。"""

    # Windows 需要先显式释放连接池，才能删除数据库文件。
    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{TEST_DB}{suffix}")
        if path.exists():
            path.unlink()
