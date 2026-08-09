"""chunk_text 分块策略单元测试（不依赖外部服务，纯函数）。"""
from app.services.knowledge import _detect_category, chunk_text


def test_section_units_are_atomic():
    """章节单元（1./一、/Q1：/第X条）必须独立成块，不与其他内容合并。"""
    text = """云杉公司产品介绍

1. 标准版（定价 3999 元/年）
适用对象：10人以下的小微企业。

2. 专业版（定价 8999 元/年）
适用对象：10-50人的成长型企业。
"""
    chunks = chunk_text(text, chunk_size=500)
    # 两个版本块各自独立
    assert any("标准版" in c and "专业版" not in c for c in chunks)
    assert any("专业版" in c and "标准版" not in c for c in chunks)
    assert any("3999" in c for c in chunks)
    assert any("8999" in c for c in chunks)


def test_short_headings_merged_into_next():
    """短标题块（<20 字）应并入下一块，避免纯关键词块虚高命中。"""
    text = "一、公司简介\n云杉科技成立于2016年，专注于企业数字化服务。\n\n二、核心产品\n云杉ERP是企业管理系统。"
    chunks = chunk_text(text)
    merged = [c for c in chunks if "公司简介" in c or "核心产品" in c]
    # 标题与正文合并，不存在独立短块
    assert all(len(c) >= 20 for c in merged)


def test_long_paragraph_split_by_sentences():
    """超长块按句子切割，且保留 overlap 保证语义连续。"""
    para = "。" * 0 + "第一句内容。" * 200  # 400 字的长段
    chunks = chunk_text(para, chunk_size=200, overlap=20)
    assert len(chunks) >= 2
    assert all(len(c) <= 200 for c in chunks[:-1])
    # 相邻块存在重叠内容（overlap 生效）
    assert any(chunks[i][-20:] in chunks[i + 1] for i in range(len(chunks) - 1))


def test_blank_line_separates_blocks():
    """短段落按预算合并（正常行为）；内容完整保留。"""
    text = "段落一的内容。\n\n段落二的内容。"
    chunks = chunk_text(text)
    merged = "".join(chunks)
    assert "段落一的内容。" in merged
    assert "段落二的内容。" in merged


def test_empty_text():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_category_detection():
    """规则类片段必须被识别（防注意力稀释机制的基础）。"""
    assert _detect_category("退货必须遵循本政策规定，不得逾期") == "rule"
    assert _detect_category("Q1：忘记密码怎么办？") == "faq"
    assert _detect_category("标准版定价3999元，包含进销存功能") == "product"
