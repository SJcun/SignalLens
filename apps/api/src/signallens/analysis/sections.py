"""来源章节解析：在模型调用前为正文建立可引用的主章节清单。

章节身份来自原始 Markdown 的行号，不由 LLM 创造。系统先定位章节，
再把清单交给 Analyze / Evaluate 引用；引用只对同一正文快照有效。
"""

import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, Field

from .schemas import ContentSection, ReadingPlanItem

# 第一版只解析 ATX 形式的一到三级标题；setext 标题与更深层级不参与。
# 行尾允许 \r，保证 CRLF 换行的正文也能准确定位。
HEADING_PATTERN = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t\r]*$")
TRAILING_HASHES = re.compile(r"[ \t]+#+[ \t\r]*$")
FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})")
SECTION_REF_PREFIX = "sec-"


class SectionRef(BaseModel):
    """当前正文快照内的一个主章节引用。"""

    section_ref: str
    level: int
    title: str
    order: int
    # 基于原始 Markdown 的零起点、左闭右开行号范围，由系统解析器生成。
    start_line: int
    end_line: int


class SectionIndex(BaseModel):
    """系统为本次正文选择的主章节层级与有序章节清单。"""

    primary_heading_level: int = Field(ge=1, le=3)
    sections: list[SectionRef]


@dataclass(frozen=True)
class _Heading:
    """扫描得到的候选标题及其原始行号。"""

    level: int
    line: int
    text: str


def build_section_index(markdown: str, article_title: str) -> SectionIndex | None:
    """从 H1～H3 中自适应选择主层级并生成有序章节清单。

    没有合适层级时返回 None，调用方保留现有分析和完整正文。
    """

    lines = markdown.split("\n")
    headings = _scan_headings(lines)
    if not headings:
        return None

    document_title_line = _document_title_line(headings, article_title)
    primary_level = _choose_primary_level(headings, document_title_line)
    if primary_level is None:
        return None

    # 主章节从自身标题开始，到下一个同级或更浅标题（含文档标题）为止。
    boundaries = [item.line for item in headings if item.level <= primary_level]
    starts = [
        item.line
        for item in headings
        if item.level == primary_level and item.line != document_title_line
    ]
    sections = [
        SectionRef(
            section_ref=f"{SECTION_REF_PREFIX}{order:03d}",
            level=primary_level,
            title=_heading_title(lines[start]),
            order=order,
            start_line=start,
            end_line=next((b for b in boundaries if b > start), len(lines)),
        )
        for order, start in enumerate(starts, start=1)
    ]
    return SectionIndex(primary_heading_level=primary_level, sections=sections)


def validate_guided_flow(
    section_index: SectionIndex | None,
    content_map: list[ContentSection] | None,
    reading_plan: list[ReadingPlanItem] | None,
) -> str | None:
    """校验选择性阅读引导流所需的引用与覆盖完整性。

    返回 None 表示引导流可启用；否则返回第一个失败原因。校验失败只降级
    为完整原文，不使三阶段分析任务失败。
    """

    if section_index is None or not section_index.sections:
        return "缺少系统章节清单"
    if not 2 <= len(section_index.sections) <= 10:
        return "主章节数量不在 2～10 范围内"
    refs = [item.section_ref for item in section_index.sections]

    if not content_map:
        return "缺少章节摘要（content_map）"
    if _invalid_references(content_map, refs, "content_map"):
        return "章节摘要引用缺失、重复或未知"
    if {item.section_ref for item in content_map} != set(refs):
        return "章节摘要未完整覆盖全部主章节"

    if not reading_plan:
        return "缺少章节阅读计划（reading_plan）"
    if _invalid_references(reading_plan, refs, "reading_plan"):
        return "章节计划引用缺失、重复或未知"
    if {item.section_ref for item in reading_plan} != set(refs):
        return "章节计划未完整覆盖全部主章节"

    actions = {item.action for item in reading_plan}
    if not actions & {"skip", "skim"}:
        return "章节计划缺少需要压缩的章节（skip/skim）"
    if not actions & {"read", "deep_read"}:
        return "章节计划缺少需要阅读的章节（read/deep_read）"
    return None


def _invalid_references(items: list, refs: list[str], label: str) -> bool:
    """检查条目引用是否都合法且唯一。"""

    seen: set[str] = set()
    for item in items:
        ref = getattr(item, "section_ref", None)
        if ref is None or ref not in refs or ref in seen:
            return True
        seen.add(ref)
    return False


def _scan_headings(lines: list[str]) -> list[_Heading]:
    """逐行扫描标题，忽略 YAML frontmatter 和代码围栏中的伪标题。"""

    frontmatter_end = _frontmatter_end_line("\n".join(lines))
    headings: list[_Heading] = []
    fence_char: str | None = None
    for line_index, line in enumerate(lines):
        if line_index < frontmatter_end:
            continue
        if fence_char is not None:
            if re.match(rf"^[ \t]*{re.escape(fence_char)}{{3,}}", line):
                fence_char = None
            continue
        fence_match = FENCE_PATTERN.match(line)
        if fence_match:
            fence_char = fence_match.group(1)[0]
            continue
        heading_match = HEADING_PATTERN.match(line)
        if heading_match:
            headings.append(
                _Heading(
                    level=len(heading_match.group(1)),
                    line=line_index,
                    text=heading_match.group(2),
                )
            )
    return headings


def _frontmatter_end_line(markdown: str) -> int:
    """返回第一个非 frontmatter 行的行号；没有 frontmatter 时返回 0。

    与翻译分块的 frontmatter 规则保持一致：首行必须是 `---`，
    并在下一个 `---` 或 `...` 行结束。
    """

    lines = markdown.split("\n")
    if not lines or lines[0].strip("\r") != "---":
        return 0
    for line_index, line in enumerate(lines[1:], start=1):
        if line.strip(" \t\r") in {"---", "..."}:
            return line_index + 1
    return 0


def _document_title_line(headings: list[_Heading], article_title: str) -> int | None:
    """文首 H1 与采集标题归一化后完全一致时，视为文档标题并排除。"""

    first = headings[0]
    if first.level == 1 and _normalize_text(first.text) == _normalize_text(article_title):
        return first.line
    return None


def _choose_primary_level(
    headings: list[_Heading], document_title_line: int | None
) -> int | None:
    """由浅到深选择首个至少包含 2 个标题的层级。

    候选层级超过 10 个标题时直接退回，不再改选更深层级。
    """

    for level in (1, 2, 3):
        count = sum(
            item.level == level and item.line != document_title_line
            for item in headings
        )
        if count >= 2:
            return level if count <= 10 else None
    return None


def _heading_title(line: str) -> str:
    """从标题行提取纯文本标题，用于展示与旧数据兼容字段。"""

    text = HEADING_PATTERN.match(line).group(2)
    text = TRAILING_HASHES.sub("", text)
    return text.strip()


def _normalize_text(text: str) -> str:
    """去除所有空白与标点后统一小写，用于标题与采集标题的比较。"""

    return "".join(
        char.lower()
        for char in text
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )
