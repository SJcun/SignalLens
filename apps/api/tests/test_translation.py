"""Markdown 分块和结构保持翻译的单元测试。"""

import json

import pytest

from signallens.translation import (
    TranslatedBlock,
    TranslationBatch,
    align_block_line_ranges,
    detect_source_language,
    run_translation_batch,
    split_markdown_blocks,
    translation_batches,
)


class EchoTranslationProvider:
    """返回可预测译文，用于验证块 ID 和结构契约。"""

    model = "translation-test-model"

    def complete(self, *, system_prompt, user_prompt, output_model):
        """保持 Markdown 标记，只替换测试中的英文文本。"""

        assert output_model is TranslationBatch
        payload = json.loads(user_prompt)
        return TranslationBatch(
            translations=[
                TranslatedBlock(
                    id=block["id"],
                    translated_markdown=block["markdown"]
                    .replace("English title", "中文标题")
                    .replace("Read the guide", "阅读指南"),
                )
                for block in payload["blocks"]
            ]
        )


class WrongOrderProvider(EchoTranslationProvider):
    """模拟模型打乱块 ID，验证错误译文不会入库。"""

    def complete(self, **kwargs):
        """反转合法结果的顺序。"""

        result = super().complete(**kwargs)
        return TranslationBatch(translations=list(reversed(result.translations)))


class CommentTranslatingProvider(EchoTranslationProvider):
    """模拟模型把行内代码注释翻译成中文，但保留注释标记。"""

    def complete(self, **kwargs):
        """替换注释内容，验证注释翻译不触发保护校验。"""

        result = super().complete(**kwargs)
        return TranslationBatch(
            translations=[
                TranslatedBlock(
                    id=item.id,
                    translated_markdown=item.translated_markdown.replace(
                        "`// Do it once!`", "`// 只做一次！`"
                    ),
                )
                for item in result.translations
            ]
        )


class CodeTranslatingProvider(EchoTranslationProvider):
    """模拟模型翻译非注释的行内代码，验证真正的代码仍受保护。"""

    def complete(self, **kwargs):
        """把变量名当普通文本翻译，应被校验拒绝。"""

        result = super().complete(**kwargs)
        return TranslationBatch(
            translations=[
                TranslatedBlock(
                    id=item.id,
                    translated_markdown=item.translated_markdown.replace(
                        "`renderLoop()`", "`渲染循环()`"
                    ),
                )
                for item in result.translations
            ]
        )


def test_markdown_blocks_preserve_structure_and_skip_shared_content() -> None:
    """frontmatter 不进入正文，代码和图片只作为共享块展示。"""

    markdown = """---
language: "en"
---

# English title

Read the [guide](https://example.com/guide).

```python
print("English code")
```

![chart](https://example.com/chart.png)
"""
    blocks = split_markdown_blocks(markdown)

    assert detect_source_language(markdown) == "en"
    assert [block["kind"] for block in blocks] == [
        "heading",
        "paragraph",
        "code",
        "image",
    ]
    assert [block["translatable"] for block in blocks] == [True, True, False, False]
    assert list(translation_batches(blocks)) == [[blocks[0], blocks[1]]]

    result = run_translation_batch(EchoTranslationProvider(), blocks[:2])
    assert result.translations[0].translated_markdown == "# 中文标题"
    assert "https://example.com/guide" in result.translations[1].translated_markdown


def test_translation_rejects_reordered_block_ids() -> None:
    """模型漏块或乱序时拒绝整批结果，避免中英文错位。"""

    blocks = split_markdown_blocks("# English title\n\nRead the guide")
    with pytest.raises(ValueError, match="翻译块 ID 不匹配"):
        run_translation_batch(WrongOrderProvider(), blocks)


def test_translation_allows_comment_translation_but_keeps_marker() -> None:
    """行内代码注释是自然语言，允许翻译成中文，但注释标记必须保留。"""

    blocks = split_markdown_blocks(
        "Respect the lifecycle with `// Do it once!` and call `renderLoop()`."
    )
    result = run_translation_batch(CommentTranslatingProvider(), blocks)
    translated = result.translations[0].translated_markdown
    assert "`// 只做一次！`" in translated
    assert "`renderLoop()`" in translated


def test_translation_rejects_translated_non_comment_code() -> None:
    """非注释行内代码（变量名、命令）被翻译时仍拒绝整批结果。"""

    blocks = split_markdown_blocks("Call `renderLoop()` once per page load.")
    with pytest.raises(ValueError, match="修改了受保护内容"):
        run_translation_batch(CodeTranslatingProvider(), blocks)


def test_body_language_overrides_misleading_page_metadata() -> None:
    """聚合站中文页面壳不能把英文正文误判为中文。"""

    english_body = " ".join(
        ["The evaluation system measures retrieval quality and production reliability."]
        * 12
    )
    misleading_english = f'---\nlanguage: "zh_CN"\n---\n\n{english_body}'
    assert detect_source_language(misleading_english) == "en"

    chinese_body = "中文技术文章讨论模型评测、Agent 架构和可靠性。" * 20
    misleading_chinese = f'---\nlanguage: "en"\n---\n\n{chinese_body}'
    assert detect_source_language(misleading_chinese) == "zh-CN"


def test_markdown_blocks_record_line_ranges_on_full_document() -> None:
    """译文块行号与章节解析共用全文口径，frontmatter 不占用正文行号。"""

    markdown = """---
language: "en"
---

# English title

Read the [guide](https://example.com/guide).

```python
print("English code")
```
"""
    blocks = split_markdown_blocks(markdown)

    # frontmatter 占 3 行；标题在第 4 行（零起点），正文段在第 6 行，代码块到第 11 行。
    assert [(block["start_line"], block["end_line"]) for block in blocks] == [
        (4, 5),
        (6, 7),
        (8, 11),
    ]
    # 与章节解析的标题定位一致：标题块从 frontmatter 之后的第一行开始。
    assert blocks[0]["start_line"] == 4
    assert blocks[0]["kind"] == "heading"


def test_align_block_line_ranges_fills_legacy_blocks() -> None:
    """旧译文块缺少行号时按位置补齐；与当前正文不一致时保持原样。"""

    markdown = "# English title\n\nRead the guide."
    legacy = split_markdown_blocks(markdown)
    for block in legacy:
        block.pop("start_line")
        block.pop("end_line")

    aligned = align_block_line_ranges(markdown, legacy)
    assert [block["start_line"] for block in aligned] == [0, 2]
    assert [block["end_line"] for block in aligned] == [1, 3]

    # 块内容与当前正文不一致（旧算法产物）时不做猜测，行号保持缺失。
    stale = [{"id": "b1", "source_markdown": "# Old title"}]
    assert align_block_line_ranges(markdown, stale) is stale
