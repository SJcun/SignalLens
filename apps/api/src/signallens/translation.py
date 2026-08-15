"""Markdown 正文分块与结构保持翻译。"""

import json
import re
from collections.abc import Iterable
from hashlib import sha256

from pydantic import BaseModel, Field, model_validator

from .analysis.pipeline import StructuredOutputProvider

TRANSLATION_PROMPT_VERSION = "translation-v0.2"
TRANSLATION_BATCH_MAX_CHARS = 6000
TRANSLATION_BATCH_MAX_BLOCKS = 12

FRONTMATTER_PATTERN = re.compile(
    r"^---\r?\n(?P<body>[\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)"
)
LANGUAGE_PATTERN = re.compile(r'^language\s*:\s*["\']?([^"\'\s]+)', re.MULTILINE)
IMAGE_PATTERN = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$", re.DOTALL)
THEMATIC_BREAK_PATTERN = re.compile(r"^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")

TRANSLATION_SYSTEM_PROMPT = """你是 SignalLens 的专业技术文章翻译器。
把每个 Markdown 块从原语言翻译为简体中文，并严格保持原有 Markdown 结构。
不得总结、删减、补充或合并内容；保留标题级别、列表层级、引用、表格列数、链接地址和行内代码。
产品名、变量名、命令、文件路径和 URL 不翻译。只返回给定 JSON Schema 要求的结果。
每个输入 id 必须且只能返回一次，顺序与输入一致。
行内代码中的注释（以 //、# 或 /* 开头）可以翻译为中文，但必须保留注释标记和反引号。"""


class TranslatedBlock(BaseModel):
    """模型返回的单个 Markdown 块译文。"""

    id: str = Field(min_length=1, max_length=32)
    translated_markdown: str = Field(min_length=1)


class TranslationBatch(BaseModel):
    """一次模型调用返回的有序译文集合。"""

    translations: list[TranslatedBlock] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "TranslationBatch":
        """拒绝重复块 ID，防止译文覆盖错误的原文。"""

        ids = [item.id for item in self.translations]
        if len(ids) != len(set(ids)):
            raise ValueError("翻译结果包含重复块 ID")
        return self


def content_source_hash(markdown: str) -> str:
    """计算正文快照哈希，用于判断缓存译文是否仍然有效。"""

    return sha256(markdown.encode("utf-8")).hexdigest()


def detect_source_language(markdown: str) -> str:
    """以正文强特征为准，frontmatter 只在正文特征不足时作为提示。"""

    body = strip_frontmatter(markdown)
    visible_text = _visible_language_text(body)
    chinese_count = len(re.findall(r"[\u3400-\u9fff]", visible_text))
    latin_count = len(re.findall(r"[A-Za-z]", visible_text))

    # 聚合站的页面语言可能来自中文界面而非文章正文。先排除代码、URL 和图片，
    # 只有正文证据足够强时才覆盖元数据，避免中文技术文章被英文术语误判。
    if latin_count >= 200 and latin_count > chinese_count * 4:
        return "en"
    if chinese_count >= 50 and chinese_count >= latin_count / 2:
        return "zh-CN"

    frontmatter = FRONTMATTER_PATTERN.match(markdown)
    if frontmatter:
        language = LANGUAGE_PATTERN.search(frontmatter.group("body"))
        if language:
            return language.group(1).replace("_", "-").lower()

    if chinese_count >= 20 and chinese_count >= latin_count / 2:
        return "zh-CN"
    if latin_count >= 40 and latin_count > chinese_count * 2:
        return "en"
    return "unknown"


def _visible_language_text(markdown: str) -> str:
    """移除不代表正文语言的代码、图片地址、URL 和行内代码。"""

    result = re.sub(r"```[\s\S]*?```|~~~[\s\S]*?~~~", " ", markdown)
    result = re.sub(r"`[^`\n]+`", " ", result)
    result = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", result)
    return re.sub(r"https?://[^\s)>\]]+", " ", result)


def strip_frontmatter(markdown: str) -> str:
    """移除采集元数据，避免把内部 frontmatter 送入翻译或正文对照。"""

    match = FRONTMATTER_PATTERN.match(markdown)
    return markdown[match.end() :] if match else markdown


def split_markdown_blocks(markdown: str) -> list[dict]:
    """按空行和代码围栏拆分 Markdown，生成可持久化的稳定内容块。"""

    lines = strip_frontmatter(markdown).strip().splitlines()
    blocks: list[dict] = []
    index = 0
    line_index = 0
    while line_index < len(lines):
        if not lines[line_index].strip():
            line_index += 1
            continue

        start = line_index
        fence = _fence_marker(lines[line_index])
        if fence:
            line_index += 1
            while line_index < len(lines):
                if lines[line_index].lstrip().startswith(fence):
                    line_index += 1
                    break
                line_index += 1
        else:
            line_index += 1
            while line_index < len(lines) and lines[line_index].strip():
                line_index += 1

        source = "\n".join(lines[start:line_index]).strip()
        kind, translatable = _classify_block(source, bool(fence))
        blocks.append(
            {
                "id": f"b{index + 1}",
                "kind": kind,
                "source_markdown": source,
                "translated_markdown": None,
                "translatable": translatable,
            }
        )
        index += 1
    return blocks


def translation_batches(blocks: list[dict]) -> Iterable[list[dict]]:
    """按字符和块数限制分批，避免长文章一次模型调用被截断。"""

    batch: list[dict] = []
    char_count = 0
    for block in blocks:
        if not block["translatable"] or block.get("translated_markdown"):
            continue
        block_length = len(block["source_markdown"])
        if batch and (
            len(batch) >= TRANSLATION_BATCH_MAX_BLOCKS
            or char_count + block_length > TRANSLATION_BATCH_MAX_CHARS
        ):
            yield batch
            batch = []
            char_count = 0
        batch.append(block)
        char_count += block_length
    if batch:
        yield batch


def run_translation_batch(
    provider: StructuredOutputProvider,
    blocks: list[dict],
) -> TranslationBatch:
    """翻译一批 Markdown 块，并验证返回 ID 与输入完全一致。"""

    prompt_blocks = [
        {"id": block["id"], "markdown": block["source_markdown"]} for block in blocks
    ]
    result = provider.complete(
        system_prompt=TRANSLATION_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {"target_language": "zh-CN", "blocks": prompt_blocks},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        output_model=TranslationBatch,
    )
    expected_ids = [block["id"] for block in blocks]
    actual_ids = [item.id for item in result.translations]
    if actual_ids != expected_ids:
        raise ValueError(f"翻译块 ID 不匹配：期望 {expected_ids}，实际 {actual_ids}")
    for source, translated in zip(blocks, result.translations, strict=True):
        protected = _protected_tokens(source["source_markdown"])
        missing = protected - _protected_tokens(translated.translated_markdown)
        if missing:
            raise ValueError(f"翻译块 {source['id']} 修改了受保护内容：{sorted(missing)}")
    return result


def _fence_marker(line: str) -> str | None:
    """识别 Markdown 代码围栏的起始标记。"""

    stripped = line.lstrip()
    if stripped.startswith("```"):
        return "```"
    if stripped.startswith("~~~"):
        return "~~~"
    return None


def _classify_block(source: str, fenced: bool) -> tuple[str, bool]:
    """判断展示类型；代码、图片和分隔线作为无需翻译的共享块。"""

    first_line = source.splitlines()[0].lstrip()
    if fenced:
        return "code", False
    if IMAGE_PATTERN.fullmatch(source):
        return "image", False
    if THEMATIC_BREAK_PATTERN.fullmatch(source):
        return "separator", False
    if re.match(r"^#{1,6}\s", first_line):
        return "heading", True
    if first_line.startswith(">"):
        return "quote", True
    if re.match(r"^(?:[-+*]|\d+[.)])\s", first_line):
        return "list", True
    if "|" in first_line and "\n" in source:
        return "table", True
    return "paragraph", True


def _protected_tokens(markdown: str) -> set[str]:
    """提取译文中必须原样保留的 URL 和行内代码。

    注释类行内代码（//、#、/* 开头）是自然语言，允许翻译成中文，
    但必须保留注释标记本身；其余行内代码（变量名、命令）和 URL 仍逐字符保护。
    """

    urls = re.findall(r"https?://[^\s)>\]]+", markdown)
    inline_code = re.findall(r"(?<!`)`[^`\n]+`(?!`)", markdown)
    protected = set(urls)
    for token in inline_code:
        marker = _comment_marker(token)
        if marker is None:
            protected.add(token)
        else:
            protected.add(marker)
    return protected


def _comment_marker(token: str) -> str | None:
    """返回行内代码的注释标记（//、#、/*），非注释返回 None。

    `#` 后紧跟字母的是 C 预处理指令（#include、#define），按代码保护；
    只有 `#` 后跟空白或到行尾才视为注释。
    """

    content = token.strip("`").lstrip()
    if content.startswith("//"):
        return "//"
    if content.startswith("/*"):
        return "/*"
    if content.startswith("#"):
        rest = content[1:]
        if not rest or rest[0].isspace():
            return "#"
    return None
