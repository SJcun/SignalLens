"""Markdown 分块和结构保持翻译的单元测试。"""

import json

import pytest

from signallens.translation import (
    TranslatedBlock,
    TranslationBatch,
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
