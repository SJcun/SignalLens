"""采集 API 的最小回归测试。"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

TEST_DB = Path(__file__).with_name("test.db")
TEST_BOOTSTRAP = Path(__file__).with_name("initial-admin-password.txt")
os.environ["SIGNALLENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SIGNALLENS_BOOTSTRAP_PASSWORD_FILE"] = str(TEST_BOOTSTRAP)

from fastapi.testclient import TestClient

import signallens.main as main_module
import signallens.worker as worker_module
from signallens.analysis.schemas import (
    AnalyzeContent,
    ContentSection,
    EvaluateForUser,
    ReadingPlanItem,
    TriageContent,
)
from signallens.database import engine
from signallens.main import _calibration_suggestions, app
from signallens.translation import TranslatedBlock, TranslationBatch
from signallens.worker import _load_user_profile, process_next_job, process_next_translation


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


class FailingProvider:
    """模拟模型服务拒绝请求，用于验证失败任务重试。"""

    model = "failing-test-model"

    def complete(self, *, system_prompt, user_prompt, output_model):
        """始终返回可诊断的模型错误。"""

        raise RuntimeError("模拟模型接口错误")


class GuidedFlowProvider(FakeProvider):
    """返回带来源引用的完整章节摘要与选择性阅读计划。"""

    model = "guided-test-model"

    def complete(self, *, system_prompt, user_prompt, output_model):
        """在固定结果基础上补齐章节引用，模拟启用了引导流的模型输出。"""

        if output_model is AnalyzeContent:
            result = super().complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=output_model,
            )
            return result.model_copy(
                update={
                    "content_map": [
                        ContentSection(section_ref="sec-001", title="第一章", summary="第一章摘要"),
                        ContentSection(section_ref="sec-002", title="第二章", summary="第二章摘要"),
                        ContentSection(section_ref="sec-003", title="第三章", summary="第三章摘要"),
                    ]
                }
            )
        if output_model is EvaluateForUser:
            result = super().complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=output_model,
            )
            return result.model_copy(
                update={
                    "reading_plan": [
                        ReadingPlanItem(
                            section_ref="sec-001",
                            section="第一章",
                            action="skip",
                            reason="背景介绍可跳过",
                        ),
                        ReadingPlanItem(
                            section_ref="sec-002",
                            section="第二章",
                            action="read",
                            reason="核心内容建议阅读",
                        ),
                        ReadingPlanItem(
                            section_ref="sec-003",
                            section="第三章",
                            action="deep_read",
                            reason="关键结论需要精读",
                        ),
                    ]
                }
            )
        return super().complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
        )


class FakeTranslationProvider:
    """按块返回结构保持译文，用于翻译任务 API 回归。"""

    model = "fake-translation-model"

    def complete(self, *, system_prompt, user_prompt, output_model):
        """保留 Markdown 和链接，只翻译固定测试文本。"""

        assert output_model is TranslationBatch
        payload = json.loads(user_prompt)
        return TranslationBatch(
            translations=[
                TranslatedBlock(
                    id=block["id"],
                    translated_markdown=block["markdown"]
                    .replace("English article", "英文文章")
                    .replace("Read the guide", "阅读指南"),
                )
                for block in payload["blocks"]
            ]
        )


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


def test_health_and_idempotent_capture(monkeypatch) -> None:
    """同一网页的不同提交只保留一条内容，并返回北京时间可解析的时间。"""

    fixed_now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(main_module, "utc_now", lambda: fixed_now)
    monkeypatch.setattr(worker_module, "utc_now", lambda: fixed_now)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/api/v1/profile").status_code == 401
        initial_password = next(
            line.removeprefix("password=")
            for line in TEST_BOOTSTRAP.read_text(encoding="utf-8").splitlines()
            if line.startswith("password=")
        )
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "错误密码"},
        ).status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": initial_password},
        )
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        assert client.get("/api/v1/auth/me").json()["username"] == "admin"

        empty_profile = client.get("/api/v1/profile")
        assert empty_profile.status_code == 200
        assert empty_profile.json()["questionnaire_completed"] is False
        profile = client.put(
            "/api/v1/profile",
            json={
                "focus_topics": ["AI 工程", "软件架构"],
                "known_topics": [{"topic": "Python", "level": "advanced"}],
                "reading_goals": ["solve_problems", "explore"],
                "preferred_depth": "balanced",
                "time_budget_minutes": 25,
                "exploration_level": "high",
                "evaluation_mode": True,
            },
        )
        assert profile.status_code == 200
        assert profile.json()["questionnaire_completed"] is True
        assert profile.json()["evaluation_mode"] is True
        worker_profile = _load_user_profile()
        assert worker_profile.focus_topics == ["AI 工程", "软件架构"]
        assert worker_profile.known_topics == ["Python（advanced）"]

        default_schedule = client.get("/api/v1/analysis-schedule")
        assert default_schedule.status_code == 200
        assert default_schedule.json()["enabled"] is False
        assert default_schedule.json()["currently_allowed"] is True
        assert client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": True, "windows": [{"start": "08:00", "end": "08:00"}]},
        ).status_code == 422
        enabled_schedule = client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": True, "windows": [{"start": "00:00", "end": "08:00"}]},
        )
        assert enabled_schedule.status_code == 200
        assert enabled_schedule.json()["currently_allowed"] is False
        assert enabled_schedule.json()["next_window_start"] == "2026-08-14T16:00:00Z"

        admin_authorization = client.headers["Authorization"]
        first_key = client.post("/api/v1/plugin-key")
        assert first_key.status_code == 200
        assert first_key.json()["api_key"].startswith("sk-sl-")
        key_status = client.get("/api/v1/plugin-key")
        assert key_status.json()["configured"] is True
        assert key_status.json()["key_prefix"] == first_key.json()["key_prefix"]

        # 单用户阶段只保留一个插件 Key，重新生成后旧 Key 立即失效。
        second_key = client.post("/api/v1/plugin-key").json()["api_key"]
        client.headers["Authorization"] = f"Bearer {first_key.json()['api_key']}"
        assert client.get("/api/v1/profile").status_code == 401
        assert client.post("/api/v1/captures", json=capture_payload()).status_code == 401
        client.headers["Authorization"] = f"Bearer {second_key}"
        assert client.get("/api/v1/analysis-schedule").status_code == 401
        first = client.post("/api/v1/captures", json=capture_payload())
        client.headers["Authorization"] = admin_authorization
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
        assert detail.json()["queue"]["waiting_for_schedule"] is True

        # 时段外普通任务不会调用模型；立即整理标记持久化且接口幂等。
        assert process_next_job(FakeProvider()) is False
        immediate = client.post(
            f"/api/v1/analyses/{first.json()['analysis_id']}/run-now"
        )
        assert immediate.status_code == 202
        assert immediate.json()["queue"]["execution_mode"] == "immediate"
        assert client.post(
            f"/api/v1/analyses/{first.json()['analysis_id']}/run-now"
        ).status_code == 202

        # 即使测试模型建议忽略，手动采集仍必须继续完成三阶段分析。
        assert process_next_job(FakeProvider()) is True
        completed = client.get(f"/api/v1/contents/{first.json()['content_id']}")
        assert completed.status_code == 200
        assert completed.json()["analysis_status"] == "completed"
        assert completed.json()["triage"]["decision"] == "continue"
        assert completed.json()["one_sentence_summary"] == "文章介绍了一个值得验证的新方法。"
        assert completed.json()["recommendation"] == "selective_read"
        assert completed.json()["ai_recommendation"] == "selective_read"
        assert completed.json()["user_recommendation"] is None
        assert completed.json()["feedback"] is None

        # 一键关闭定时模式后恢复提交即分析，同时保留原窗口配置。
        disabled_schedule = client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": False, "windows": [{"start": "00:00", "end": "08:00"}]},
        )
        assert disabled_schedule.status_code == 200
        assert disabled_schedule.json()["currently_allowed"] is True

        feedback = client.put(
            f"/api/v1/analyses/{first.json()['analysis_id']}/feedback",
            json={
                "preferred_recommendation": "selective_read",
                "time_worthwhile": "yes",
                "new_knowledge": "some",
                "summary_quality": "omission",
                "key_takeaway": "AI 遗漏了文章对实施成本的讨论。",
            },
        )
        assert feedback.status_code == 200
        assert feedback.json()["ai_recommendation"] == "selective_read"
        assert feedback.json()["preferred_recommendation"] == "selective_read"
        assert feedback.json()["recommendation_accuracy"] == "accurate"
        assert feedback.json()["model"] == "fake-test-model"

        stats = client.get("/api/v1/calibration/stats")
        assert stats.status_code == 200
        assert stats.json()["feedback_count"] == 1
        assert stats.json()["accuracy_rate"] == 100.0
        assert stats.json()["summary_issue_count"] == 1

        updated_feedback = client.put(
            f"/api/v1/analyses/{first.json()['analysis_id']}/feedback",
            json={
                "preferred_recommendation": "deep_read",
                "time_worthwhile": "yes",
                "new_knowledge": "much",
                "summary_quality": "accurate",
                "key_takeaway": "更新后的评价。",
            },
        )
        assert updated_feedback.status_code == 200
        assert updated_feedback.json()["recommendation_accuracy"] == "too_low"
        assert client.get("/api/v1/calibration/stats").json()["feedback_count"] == 1

        corrected_feedback = client.put(
            f"/api/v1/analyses/{first.json()['analysis_id']}/feedback",
            json={
                "preferred_recommendation": "summary_enough",
                "time_worthwhile": "partly",
                "new_knowledge": "some",
                "summary_quality": "accurate",
                "key_takeaway": "摘要已经足够。",
            },
        )
        assert corrected_feedback.status_code == 200
        assert corrected_feedback.json()["recommendation_accuracy"] == "too_high"
        corrected_content = client.get(f"/api/v1/contents/{first.json()['content_id']}")
        assert corrected_content.json()["recommendation"] == "summary_enough"
        assert corrected_content.json()["ai_recommendation"] == "selective_read"
        assert corrected_content.json()["user_recommendation"] == "summary_enough"
        corrected_list_item = client.get("/api/v1/contents").json()[0]
        assert corrected_list_item["recommendation"] == "summary_enough"

        corrected_stats = client.get("/api/v1/calibration/stats").json()
        assert corrected_stats["feedback_needed"] == 19
        assert corrected_stats["confusion_matrix"] == [
            {
                "ai_recommendation": "selective_read",
                "user_recommendation": "summary_enough",
                "count": 1,
            }
        ]
        assert corrected_stats["adjacent_error_count"] == 1
        assert corrected_stats["major_error_count"] == 0
        assert corrected_stats["suggestions"] == []

        # 三阶段之间重新检查窗口；关闭后保留初筛结果并从正文分析继续。
        client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": True, "windows": [{"start": "00:00", "end": "08:00"}]},
        )
        staged_payload = capture_payload()
        staged_payload["capture_id"] = "capture-test-stage-pause"
        staged_payload["source"]["url"] = "https://example.com/stage-pause"
        staged = client.post("/api/v1/captures", json=staged_payload)
        stage_times = iter(
            [
                datetime(2026, 8, 13, 17, 0, tzinfo=UTC),
                datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
            ]
        )
        with monkeypatch.context() as stage_patch:
            stage_patch.setattr(worker_module, "utc_now", lambda: next(stage_times))
            assert process_next_job(FakeProvider()) is True
        staged_detail = client.get(
            f"/api/v1/contents/{staged.json()['content_id']}"
        ).json()
        assert staged_detail["analysis_status"] == "running"
        assert staged_detail["triage"] is not None
        assert staged_detail["content_analysis"] is None
        assert staged_detail["queue"]["stage"] == "analyze"
        assert staged_detail["queue"]["waiting_for_schedule"] is True
        assert client.post(
            f"/api/v1/analyses/{staged.json()['analysis_id']}/run-now"
        ).status_code == 202
        assert process_next_job(FakeProvider()) is True
        assert client.get(
            f"/api/v1/analyses/{staged.json()['analysis_id']}"
        ).json()["status"] == "completed"
        released_payload = capture_payload()
        released_payload["capture_id"] = "capture-test-switch-release"
        released_payload["source"]["url"] = "https://example.com/switch-release"
        released = client.post("/api/v1/captures", json=released_payload)
        assert released.status_code == 202
        assert process_next_job(FakeProvider()) is False
        switched_off = client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": False, "windows": [{"start": "00:00", "end": "08:00"}]},
        )
        assert switched_off.json()["currently_allowed"] is True
        assert process_next_job(FakeProvider()) is True
        assert client.get(
            f"/api/v1/analyses/{released.json()['analysis_id']}"
        ).json()["status"] == "completed"

        # 自动采集若被 AI 忽略，但用户认为值得读，应计入高价值漏判。
        ignored_payload = capture_payload()
        ignored_payload["capture_id"] = "capture-test-ignored"
        ignored_payload["source"]["url"] = "https://example.com/ignored-article"
        ignored_payload["capture"]["mode"] = "automatic"
        ignored = client.post("/api/v1/captures", json=ignored_payload)
        assert ignored.status_code == 202
        assert process_next_job(FakeProvider()) is True
        ignored_feedback = client.put(
            f"/api/v1/analyses/{ignored.json()['analysis_id']}/feedback",
            json={
                "preferred_recommendation": "selective_read",
                "time_worthwhile": "yes",
                "new_knowledge": "much",
                "summary_quality": "not_sure",
                "key_takeaway": "这篇内容不应被直接忽略。",
            },
        )
        assert ignored_feedback.status_code == 200
        assert ignored_feedback.json()["ai_recommendation"] == "ignore"
        assert ignored_feedback.json()["recommendation_accuracy"] == "too_low"
        ignored_stats = client.get("/api/v1/calibration/stats").json()
        assert ignored_stats["feedback_count"] == 2
        assert ignored_stats["high_value_miss_count"] == 1

        # 引导阅读流：带来源引用的完整章节计划启用顺序式引导。
        guided_payload = capture_payload()
        guided_payload["capture_id"] = "capture-test-guided"
        guided_payload["source"]["url"] = "https://example.com/guided-article"
        guided_payload["source"]["title"] = "引导流测试文章"
        guided_payload["document"]["text"] = (
            "# 引导流测试文章\n\n导语。\n"
            "## 第一章\n内容。\n## 第二章\n内容。\n## 第三章\n内容。\n"
        )
        guided = client.post("/api/v1/captures", json=guided_payload)
        assert guided.status_code == 202
        assert process_next_job(GuidedFlowProvider()) is True
        guided_detail = client.get(f"/api/v1/contents/{guided.json()['content_id']}").json()
        assert guided_detail["analysis_status"] == "completed"
        assert guided_detail["section_index"]["primary_heading_level"] == 2
        assert len(guided_detail["section_index"]["sections"]) == 3
        assert guided_detail["section_index"]["sections"][0]["section_ref"] == "sec-001"
        assert guided_detail["guided_flow_available"] is True
        assert (
            guided_detail["personal_evaluation"]["reading_plan"][0]["section_ref"]
            == "sec-001"
        )

        # 用户把文章级建议修正为其他动作后，旧章节计划不再自动应用。
        client.put(
            f"/api/v1/analyses/{guided.json()['analysis_id']}/feedback",
            json={
                "preferred_recommendation": "deep_read",
                "time_worthwhile": "yes",
                "new_knowledge": "much",
                "summary_quality": "accurate",
                "key_takeaway": "全文都值得精读。",
            },
        )
        corrected_guided = client.get(
            f"/api/v1/contents/{guided.json()['content_id']}"
        ).json()
        assert corrected_guided["guided_flow_available"] is False
        assert corrected_guided["section_index"] is not None

        # 同一 URL 重新采集更新正文后，旧章节清单立即失效并退回完整原文。
        updated_guided = guided_payload.copy()
        updated_guided["capture_id"] = "capture-test-guided-updated"
        updated_guided["document"]["text"] = (
            "# 引导流测试文章\n\n正文已完全改变。\n## 唯一章节\n内容。"
        )
        assert client.post("/api/v1/captures", json=updated_guided).status_code == 202
        stale_detail = client.get(f"/api/v1/contents/{guided.json()['content_id']}").json()
        assert stale_detail["section_index"] is None
        assert stale_detail["guided_flow_available"] is False

        # 分析期间正文更新：旧阶段结果与新快照不能混用，任务从头重新分析。
        client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": True, "windows": [{"start": "00:00", "end": "08:00"}]},
        )
        paused_payload = capture_payload()
        paused_payload["capture_id"] = "capture-test-guided-pause"
        paused_payload["source"]["url"] = "https://example.com/guided-pause"
        paused_payload["source"]["title"] = "暂停测试文章"
        paused_payload["document"]["text"] = (
            "# 暂停测试文章\n\n## 第一章\n内容。\n## 第二章\n内容。"
        )
        paused = client.post("/api/v1/captures", json=paused_payload)
        assert paused.status_code == 202
        pause_times = iter(
            [
                datetime(2026, 8, 13, 17, 0, tzinfo=UTC),  # 北京时间 01:00，窗口内
                datetime(2026, 8, 14, 0, 0, tzinfo=UTC),  # 北京时间 08:00，窗口外
            ]
        )
        with monkeypatch.context() as pause_patch:
            pause_patch.setattr(worker_module, "utc_now", lambda: next(pause_times))
            assert process_next_job(GuidedFlowProvider()) is True
        paused_detail = client.get(
            f"/api/v1/contents/{paused.json()['content_id']}"
        ).json()
        assert paused_detail["analysis_status"] == "running"
        assert paused_detail["triage"] is not None
        assert paused_detail["queue"]["stage"] == "analyze"
        assert paused_detail["section_index"] is not None

        updated_paused = paused_payload.copy()
        updated_paused["capture_id"] = "capture-test-guided-pause-updated"
        updated_paused["document"]["text"] = (
            "# 暂停测试文章\n\n"
            "## 新章节一\n内容。\n## 新章节二\n内容。\n## 新章节三\n内容。"
        )
        assert client.post("/api/v1/captures", json=updated_paused).status_code == 202
        with monkeypatch.context() as resume_patch:
            resume_patch.setattr(
                worker_module,
                "utc_now",
                lambda: datetime(2026, 8, 13, 18, 0, tzinfo=UTC),
            )
            assert process_next_job(GuidedFlowProvider()) is True
        resumed_detail = client.get(
            f"/api/v1/contents/{paused.json()['content_id']}"
        ).json()
        assert resumed_detail["analysis_status"] == "completed"
        assert len(resumed_detail["section_index"]["sections"]) == 3
        assert resumed_detail["guided_flow_available"] is True

        # 恢复提交即分析，避免后续失败重试测试受窗口限制。
        client.put(
            "/api/v1/analysis-schedule",
            json={"enabled": False, "windows": [{"start": "00:00", "end": "08:00"}]},
        )

        completed_retry_attempt = client.post(
            f"/api/v1/analyses/{first.json()['analysis_id']}/retry"
        )
        assert completed_retry_attempt.status_code == 409
        assert client.post(
            f"/api/v1/analyses/{first.json()['analysis_id']}/run-now"
        ).status_code == 409

        failed_payload = capture_payload()
        failed_payload["capture_id"] = "capture-test-failed"
        failed_payload["source"]["url"] = "https://example.com/failed-article"
        failed = client.post("/api/v1/captures", json=failed_payload)
        assert failed.status_code == 202
        assert process_next_job(FailingProvider()) is True
        failed_analysis = client.get(f"/api/v1/analyses/{failed.json()['analysis_id']}")
        assert failed_analysis.json()["status"] == "failed"

        retried = client.post(f"/api/v1/analyses/{failed.json()['analysis_id']}/retry")
        assert retried.status_code == 202
        assert retried.json()["status"] == "pending"
        assert process_next_job(FakeProvider()) is True
        completed_retry = client.get(f"/api/v1/analyses/{failed.json()['analysis_id']}")
        assert completed_retry.json()["status"] == "completed"
        assert process_next_job(FakeProvider()) is False

        # 英文正文由用户主动触发翻译；重复点击复用任务，代码和图片不重复翻译。
        english_payload = capture_payload()
        english_payload["capture_id"] = "capture-test-english"
        english_payload["source"]["url"] = "https://example.com/english-article"
        english_payload["source"]["title"] = "English article"
        english_payload["document"]["text"] = """---
language: "en"
---

# English article

Read the [guide](https://example.com/guide).

```python
print("keep English code")
```

![chart](https://example.com/chart.png)
"""
        english = client.post("/api/v1/captures", json=english_payload)
        assert english.status_code == 202
        translation_url = f"/api/v1/contents/{english.json()['content_id']}/translation"
        created_translation = client.post(translation_url)
        repeated_translation = client.post(translation_url)
        assert created_translation.status_code == 202
        assert created_translation.json()["id"] == repeated_translation.json()["id"]
        assert created_translation.json()["total_blocks"] == 2

        assert process_next_translation(FailingProvider()) is True
        failed_translation = client.get(
            f"/api/v1/contents/{english.json()['content_id']}"
        ).json()["translation"]
        assert failed_translation["status"] == "failed"
        assert client.post(translation_url).json()["status"] == "pending"
        assert process_next_translation(FakeTranslationProvider()) is True
        translated_detail = client.get(
            f"/api/v1/contents/{english.json()['content_id']}"
        ).json()
        assert translated_detail["source_language"] == "en"
        assert translated_detail["translation"]["status"] == "completed"
        assert translated_detail["translation"]["completed_blocks"] == 2
        translated_blocks = translated_detail["translation"]["blocks"]
        assert translated_blocks[0]["translated_markdown"] == "# 英文文章"
        assert translated_blocks[2]["kind"] == "code"
        assert translated_blocks[2]["shared"] is True
        assert translated_blocks[2]["translated_markdown"] is None

        # 同一 URL 的新正文使旧译文失效；重新触发仍复用记录但从新快照开始。
        updated_english = english_payload.copy()
        updated_english["capture_id"] = "capture-test-english-updated"
        updated_english["document"] = {
            "format": "markdown",
            "text": "---\nlanguage: en\n---\n\n# English article updated",
            "units": [],
        }
        assert client.post("/api/v1/captures", json=updated_english).status_code == 202
        assert client.get(
            f"/api/v1/contents/{english.json()['content_id']}"
        ).json()["translation"] is None
        refreshed_translation = client.post(translation_url)
        assert refreshed_translation.json()["id"] == created_translation.json()["id"]
        assert refreshed_translation.json()["status"] == "pending"
        assert refreshed_translation.json()["completed_blocks"] == 0
        assert process_next_translation(FakeTranslationProvider()) is True

        assert client.delete("/api/v1/plugin-key").status_code == 200
        client.headers["Authorization"] = f"Bearer {second_key}"
        revoked_payload = capture_payload()
        revoked_payload["capture_id"] = "capture-test-revoked-key"
        revoked_payload["source"]["url"] = "https://example.com/revoked-key"
        assert client.post("/api/v1/captures", json=revoked_payload).status_code == 401
        client.headers["Authorization"] = admin_authorization

        changed = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": initial_password,
                "new_password": "new-test-password-2026",
            },
        )
        assert changed.status_code == 200
        assert not TEST_BOOTSTRAP.exists()
        assert client.get("/api/v1/profile").status_code == 401
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": initial_password},
        ).status_code == 401
        new_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "new-test-password-2026"},
        )
        assert new_login.status_code == 200
        client.headers.update({"Authorization": f"Bearer {new_login.json()['access_token']}"})
        assert client.post("/api/v1/auth/logout").status_code == 200
        assert client.get("/api/v1/profile").status_code == 401


def test_calibration_suggestions_require_enough_evidence() -> None:
    """候选规则必须达到样本门槛，并保留用户的确认状态。"""

    feedbacks = [
        SimpleNamespace(
            ai_recommendation="selective_read",
            preferred_recommendation="summary_enough",
            recommendation_accuracy="too_high",
            summary_quality="accurate",
        )
        for _ in range(20)
    ]
    assert _calibration_suggestions(feedbacks[:19], {}) == []

    suggestions = _calibration_suggestions(feedbacks, {})
    assert [item.id for item in suggestions] == ["reduce_over_recommendation"]
    assert suggestions[0].status == "pending"
    accepted = _calibration_suggestions(feedbacks, {"reduce_over_recommendation": "accepted"})
    assert accepted[0].status == "accepted"


def teardown_module() -> None:
    """删除测试产生的临时 SQLite 文件。"""

    # Windows 需要先显式释放连接池，才能删除数据库文件。
    engine.dispose()
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{TEST_DB}{suffix}")
        if path.exists():
            path.unlink()
    TEST_BOOTSTRAP.unlink(missing_ok=True)
    TEST_BOOTSTRAP.with_suffix(".txt.tmp").unlink(missing_ok=True)
