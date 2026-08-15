"""来源章节解析与引导流引用校验的单元测试。"""

import pytest

from signallens.analysis.schemas import ContentSection, ReadingPlanItem
from signallens.analysis.sections import (
    SectionIndex,
    SectionRef,
    build_section_index,
    validate_guided_flow,
)


def make_index(section_count: int = 5, level: int = 2) -> SectionIndex:
    """构造一个可用的主章节清单，供校验器测试使用。"""

    return SectionIndex(
        primary_heading_level=level,
        sections=[
            SectionRef(
                section_ref=f"sec-{order:03d}",
                level=level,
                title=f"章节 {order}",
                order=order,
                start_line=10 + order * 5,
                end_line=10 + (order + 1) * 5,
            )
            for order in range(1, section_count + 1)
        ],
    )


def make_content_map(refs: list[str]) -> list[ContentSection]:
    """构造与引用清单对应的章节摘要。"""

    return [
        ContentSection(section_ref=ref, title=f"章节 {ref}", summary="本节摘要")
        for ref in refs
    ]


def make_reading_plan(refs: list[str]) -> list[ReadingPlanItem]:
    """构造与引用清单对应的章节动作，默认同时包含压缩与阅读动作。"""

    actions = ["skip", "skim", "read", "deep_read", "read"]
    return [
        ReadingPlanItem(
            section_ref=ref,
            section=f"章节 {ref}",
            action=actions[index % len(actions)],
            reason="测试原因",
        )
        for index, ref in enumerate(refs)
    ]


def test_picks_h2_when_enough_second_level_headings() -> None:
    """5 个 H2 且 H3 更多时仍优先选择较浅的 H2 层级。"""

    markdown = """# 文章标题

导语。
## 第一节
正文 A。
### 子标题 1
正文 B。
## 第二节
正文 C。
## 第三节
正文 D。
## 第四节
正文 E。
## 第五节
正文 F。
"""
    index = build_section_index(markdown, "文章标题")
    assert index is not None
    assert index.primary_heading_level == 2
    assert [item.title for item in index.sections] == [
        "第一节",
        "第二节",
        "第三节",
        "第四节",
        "第五节",
    ]
    # 主章节从标题行开始，到下一个同级标题或文章结束为止（左闭右开）。
    assert index.sections[0].start_line == 3
    assert index.sections[0].end_line == 7
    assert index.sections[-1].end_line == len(markdown.split("\n"))


def test_picks_h3_when_only_one_h2() -> None:
    """单一 H2 下存在多个 H3 时选择 H3 作为主层级。"""

    markdown = """## 总览
### 第一点
内容。
### 第二点
内容。
### 第三点
内容。
"""
    index = build_section_index(markdown, "其他标题")
    assert index is not None
    assert index.primary_heading_level == 3
    assert len(index.sections) == 3


def test_falls_back_when_too_many_headings_in_first_level() -> None:
    """首个候选层级超过 10 个标题时直接降级，不改选更深层级。"""

    markdown = "".join(f"## 章节 {order}\n" for order in range(1, 13)) + "### 深层标题"
    index = build_section_index(markdown, "文章")
    assert index is None


def test_falls_back_when_fewer_than_two_headings() -> None:
    """H1～H3 都不足 2 个标题时退回完整原文。"""

    markdown = "# 文章标题\n\n只有一段正文。\n## 唯一章节\n内容。"
    assert build_section_index(markdown, "文章标题") is None


def test_document_title_h1_excluded_from_candidates() -> None:
    """文首 H1 与采集标题归一化后一致时视为文档标题，不参与计数。"""

    markdown = """# 为什么需要选择性阅读
导语。
## 第一部分
内容。
## 第二部分
内容。
"""
    index = build_section_index(markdown, "为什么需要选择性阅读")
    assert index is not None
    assert index.primary_heading_level == 2
    # 文档标题行与第一个主章节标题行之间是上下文块。
    assert index.sections[0].start_line == 2


def test_document_title_requires_normalized_equality() -> None:
    """文首 H1 与采集标题不一致时作为普通 H1 参与候选。"""

    markdown = "# 网页自带标题\n\n## 小节\n内容。\n# 第二个 H1\n内容。"
    index = build_section_index(markdown, "采集标题")
    assert index is not None
    assert index.primary_heading_level == 1
    assert index.sections[0].title == "网页自带标题"


def test_normalization_ignores_whitespace_and_punctuation() -> None:
    """空白与标点差异不影响文档标题的归一化比较。"""

    markdown = "# 为什么需要“选择性”阅读？\n\n## 章节一\n内容。\n## 章节二\n内容。"
    index = build_section_index(markdown, "为什么需要选择性阅读")
    assert index is not None
    assert index.primary_heading_level == 2


def test_ignores_fake_headings_in_frontmatter_and_fences() -> None:
    """YAML frontmatter 与代码围栏中的伪标题不产生章节。"""

    markdown = """---
title: 文章标题
# 这不是标题
---
导语。
```python
# 这是代码注释
print('ok')
```
## 真实章节一
内容。
## 真实章节二
内容。
"""
    index = build_section_index(markdown, "文章标题")
    assert index is not None
    assert index.primary_heading_level == 2
    assert len(index.sections) == 2
    assert index.sections[0].title == "真实章节一"


def test_duplicate_titles_get_distinct_refs_and_positions() -> None:
    """同一主层级的重名标题得到不同 section_ref，且行号各自精确。"""

    markdown = """## 同题章节
甲。
## 同题章节
乙。
## 同题章节
丙。
"""
    index = build_section_index(markdown, "文章")
    assert index is not None
    refs = [item.section_ref for item in index.sections]
    assert len(refs) == len(set(refs)) == 3
    starts = [item.start_line for item in index.sections]
    assert starts == sorted(starts)


def test_deeper_headings_stay_inside_primary_sections() -> None:
    """更深标题保留在所属主章节内部，不单独产生动作边界。"""

    markdown = """## 章节一
### 内部小节
内容。
## 章节二
内容。
"""
    index = build_section_index(markdown, "文章")
    assert index is not None
    assert index.primary_heading_level == 2
    assert index.sections[0].start_line == 0
    # H3 不是主层级边界，章节一持续到章节二标题行。
    assert index.sections[0].end_line == 3


def test_validation_accepts_complete_references() -> None:
    """引用完整且动作分布合理时校验通过。"""

    index = make_index()
    refs = [item.section_ref for item in index.sections]
    assert (
        validate_guided_flow(index, make_content_map(refs), make_reading_plan(refs)) is None
    )


def test_validation_rejects_unknown_and_duplicate_refs() -> None:
    """未知、重复或缺失引用使引导流降级，但不抛异常。"""

    index = make_index()
    refs = [item.section_ref for item in index.sections]
    assert validate_guided_flow(index, make_content_map(refs + ["sec-999"]), make_reading_plan(refs)) is not None
    assert validate_guided_flow(index, make_content_map(refs + [refs[0]]), make_reading_plan(refs)) is not None
    assert validate_guided_flow(index, make_content_map(refs), make_reading_plan(refs[1:])) is not None
    assert validate_guided_flow(index, make_content_map(refs), []) is not None


def test_validation_requires_both_compressed_and_reading_actions() -> None:
    """selective_read 必须同时包含压缩与阅读动作，否则降级。"""

    index = make_index()
    refs = [item.section_ref for item in index.sections]
    all_read = [
        ReadingPlanItem(section_ref=ref, section=f"章节 {ref}", action="read", reason="原因")
        for ref in refs
    ]
    all_skip = [
        ReadingPlanItem(section_ref=ref, section=f"章节 {ref}", action="skip", reason="原因")
        for ref in refs
    ]
    assert validate_guided_flow(index, make_content_map(refs), all_read) is not None
    assert validate_guided_flow(index, make_content_map(refs), all_skip) is not None


def test_validation_handles_legacy_results_without_refs() -> None:
    """历史结果没有 section_ref 时引导流降级，但模型可正常读取。"""

    legacy_map = [ContentSection(section_ref=None, title="旧章节", summary="旧摘要")]
    legacy_plan = [
        ReadingPlanItem(section_ref=None, section="旧章节", action="read", reason="原因")
    ]
    assert validate_guided_flow(make_index(), legacy_map, legacy_plan) is not None


def test_validation_rejects_missing_section_index() -> None:
    """缺少章节清单时直接降级。"""

    assert validate_guided_flow(None, make_content_map(["sec-001"]), make_reading_plan(["sec-001"])) is not None
    assert validate_guided_flow(SectionIndex(primary_heading_level=2, sections=[]), [], []) is not None


def test_validation_rejects_out_of_range_section_count() -> None:
    """章节数量超出 2～10 时降级。"""

    index = make_index(section_count=1)
    assert validate_guided_flow(index, [], []) is not None
    oversized = make_index(section_count=11)
    assert validate_guided_flow(oversized, [], []) is not None


def test_handles_crlf_line_endings() -> None:
    """CRLF 换行的正文同样能按原始行号定位章节。"""

    markdown = "---\r\ntitle: 文章\r\n---\r\n\r\n# 文章\r\n\r\n## 甲\r\n内容。\r\n## 乙\r\n内容。\r\n"
    index = build_section_index(markdown, "文章")
    assert index is not None
    assert index.primary_heading_level == 2
    assert index.sections[0].title == "甲"
    assert index.sections[0].start_line == 6
    assert index.sections[1].start_line == 8


@pytest.mark.parametrize(
    "markdown, expected_level, expected_count",
    [
        # 方案示例：1 个 H2、6 个 H3 → 选择 H3
        ("## 总览\n" + "".join(f"### 点 {i}\n内容。\n" for i in range(6)), 3, 6),
        # 方案示例：5 个 H2、12 个 H3 → 选择 H2
        ("".join(f"## 章 {i}\n" for i in range(5)) + "".join(f"### 点 {i}\n" for i in range(12)), 2, 5),
        # 方案示例：12 个 H2 → 不启用
        ("".join(f"## 章 {i}\n" for i in range(12)), None, 0),
    ],
)
def test_document_examples(markdown, expected_level, expected_count) -> None:
    """方案中的主层级选择示例必须逐条成立。"""

    index = build_section_index(markdown, "文章")
    if expected_level is None:
        assert index is None
    else:
        assert index is not None
        assert index.primary_heading_level == expected_level
        assert len(index.sections) == expected_count
