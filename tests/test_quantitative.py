"""定量数据验证模块测试。

Test-Driven Development: Tests written first, then implementation.
"""

import pytest
from src.analysis.quantitative import (
    VerificationStatus,
    QuantitativeEvidence,
    ExtractedNumber,
    ValidationResult,
    QuantitativeExtractor,
    QuantitativeValidator,
)


class TestVerificationStatus:
    """验证状态枚举测试。"""

    def test_enum_values(self) -> None:
        """验证枚举值存在。"""
        assert VerificationStatus.UNVERIFIED == "unverified"
        assert VerificationStatus.SINGLE_SOURCE == "single_source"
        assert VerificationStatus.CROSS_VALIDATED == "cross_validated"
        assert VerificationStatus.DISPUTED == "disputed"


class TestQuantitativeEvidence:
    """定量证据数据类测试。"""

    def test_create_quantitative_evidence(self) -> None:
        """验证创建定量证据。"""
        evidence = QuantitativeEvidence(
            metric_name="monthly_active_users",
            value="100M",
            unit="users",
            source_url="https://example.com",
            extracted_at="2026-02-13T10:00:00",
            confidence=0.85,
        )
        assert evidence.metric_name == "monthly_active_users"
        assert evidence.value == "100M"
        assert evidence.unit == "users"
        assert evidence.source_url == "https://example.com"
        assert evidence.confidence == 0.85


class TestExtractedNumber:
    """提取数字数据类测试。"""

    def test_create_extracted_number(self) -> None:
        """验证创建提取的数字。"""
        extracted = ExtractedNumber(
            text="月活跃用户达到 1 亿",
            value=100000000.0,
            unit="users",
            context="豆包月活跃用户",
            confidence=0.90,
        )
        assert extracted.text == "月活跃用户达到 1 亿"
        assert extracted.value == 100000000.0
        assert extracted.unit == "users"
        assert extracted.context == "豆包月活跃用户"
        assert extracted.confidence == 0.90


class TestQuantitativeExtractor:
    """定量提取器测试。"""

    def test_extract_simple_chinese_numbers(self) -> None:
        """测试提取中文数字。

        注意：中文数字可能与单位之间有空格或逗号
        """
        extractor = QuantitativeExtractor()
        text = "月活跃用户 1 亿，日活跃用户 2000 万"
        numbers = extractor.extract_numbers(text)

        # 期望：1 亿 + 2000 万 = 2个匹配
        # "1 亿" (unit=亿, value=1e8)
        # "2000 万" (unit=万, value=2e7)
        assert len(numbers) == 2, f"Expected 2 matches, got {len(numbers)}"
        assert any(n.value == 100000000.0 for n in numbers)  # 1亿
        assert any(n.value == 20000000.0 for n in numbers)  # 2000万

    def test_extract_mixed_numbers(self) -> None:
        """测试提取混合格式数字。"""
        extractor = QuantitativeExtractor()
        text = "MAU 100M, DAU 20M, revenue $5M"
        numbers = extractor.extract_numbers(text)

        assert len(numbers) >= 2
        # 检查单位识别
        units = [n.unit for n in numbers]
        assert any("M" in u or "users" in u for u in units)

    def test_extract_percentage(self) -> None:
        """测试提取百分比。"""
        extractor = QuantitativeExtractor()
        text = "市场份额达到 35%，同比增长 15%"
        numbers = extractor.extract_numbers(text)

        assert len(numbers) >= 2
        assert any(n.unit == "%" for n in numbers)

    def test_extract_with_common_metrics(self) -> None:
        """测试识别常见指标。"""
        extractor = QuantitativeExtractor()
        text = "MAU 达到 1 亿，DAU 为 2000 万，营收 500 万美元"
        numbers = extractor.extract_numbers(text)

        # 应该识别出 MAU/DAU 指标
        assert len(numbers) >= 3
        # 检查上下文包含指标名
        contexts = [n.context for n in numbers]
        assert any("MAU" in c or "月活" in c for c in contexts)
        assert any("DAU" in c or "日活" in c for c in contexts)

    def test_extract_empty_text(self) -> None:
        """测试空文本提取。"""
        extractor = QuantitativeExtractor()
        numbers = extractor.extract_numbers("没有数字的文本")
        assert len(numbers) == 0

    def test_confidence_calculation(self) -> None:
        """测试置信度计算。"""
        extractor = QuantitativeExtractor()
        text = "官方数据：100万用户"  # 应该有较高置信度
        numbers = extractor.extract_numbers(text)

        assert len(numbers) > 0
        # 带明确标记的文本应该有更高置信度
        first = numbers[0]
        assert 0.0 <= first.confidence <= 1.0


class TestQuantitativeValidator:
    """定量验证器测试。"""

    def test_cross_validate_single_source(self) -> None:
        """测试单来源验证状态。"""
        validator = QuantitativeValidator()
        numbers = [
            ExtractedNumber(
                text="来源A：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.80,
            )
        ]
        sources = ["https://example.com/a"]

        result = validator.cross_validate(numbers, sources)

        assert result.status == VerificationStatus.SINGLE_SOURCE
        assert result.metric_name == "MAU"
        # 共识值会被清理，移除来源前缀
        assert result.consensus_value == "100万"

    def test_cross_validate_multiple_agreed(self) -> None:
        """测试多来源一致验证。"""
        validator = QuantitativeValidator()
        numbers = [
            ExtractedNumber(
                text="来源A：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.80,
            ),
            ExtractedNumber(
                text="来源B：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.85,
            ),
        ]
        sources = ["https://a.com", "https://b.com"]

        result = validator.cross_validate(numbers, sources)

        assert result.status == VerificationStatus.CROSS_VALIDATED
        assert result.consensus_value is not None

    def test_cross_validate_disputed(self) -> None:
        """测试多来源冲突。"""
        validator = QuantitativeValidator()
        numbers = [
            ExtractedNumber(
                text="来源A：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.80,
            ),
            ExtractedNumber(
                text="来源B：50万",
                value=500000.0,
                unit="users",
                context="MAU",
                confidence=0.85,
            ),
        ]
        sources = ["https://a.com", "https://b.com"]

        result = validator.cross_validate(numbers, sources)

        assert result.status == VerificationStatus.DISPUTED
        assert result.consensus_value is None  # 冲突时无共识

    def test_confidence_adjustment_positive(self) -> None:
        """测试交叉验证后的置信度正向调整。"""
        validator = QuantitativeValidator()
        numbers = [
            ExtractedNumber(
                text="来源A：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.80,
            ),
            ExtractedNumber(
                text="来源B：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.85,
            ),
        ]
        sources = ["https://a.com", "https://b.com"]

        result = validator.cross_validate(numbers, sources)

        # 交叉验证成功应该增加置信度调整
        assert result.confidence_adjustment > 0

    def test_confidence_adjustment_negative(self) -> None:
        """测试冲突时的置信度负向调整。"""
        validator = QuantitativeValidator()
        numbers = [
            ExtractedNumber(
                text="来源A：100万",
                value=1000000.0,
                unit="users",
                context="MAU",
                confidence=0.80,
            ),
            ExtractedNumber(
                text="来源B：50万",
                value=500000.0,
                unit="users",
                context="MAU",
                confidence=0.85,
            ),
        ]
        sources = ["https://a.com", "https://b.com"]

        result = validator.cross_validate(numbers, sources)

        # 冲突应该降低置信度
        assert result.confidence_adjustment < 0
