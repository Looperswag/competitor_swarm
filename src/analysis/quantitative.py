"""定量数据验证模块。

提供从文本中提取数字、单位、指标并进行交叉验证的功能。
用于提升 Signal 置信度的准确性。
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    """验证状态枚举。"""

    UNVERIFIED = "unverified"
    SINGLE_SOURCE = "single_source"
    CROSS_VALIDATED = "cross_validated"
    DISPUTED = "disputed"


@dataclass(frozen=True)
class QuantitativeEvidence:
    """定量证据。

    表示一个定量的度量数据。
    """

    metric_name: str
    value: str
    unit: str
    source_url: str
    extracted_at: str
    confidence: float


@dataclass
class ExtractedNumber:
    """从文本提取的数字。

    包含原始文本、数值、单位和上下文信息。
    """

    text: str
    value: float
    unit: str
    context: str
    confidence: float


@dataclass
class ValidationResult:
    """验证结果。

    包含跨来源验证的结果和置信度调整建议。
    """

    metric_name: str
    values: list[ExtractedNumber]
    consensus_value: str | None
    status: VerificationStatus
    confidence_adjustment: float


class QuantitativeExtractor:
    """定量数据提取器。

    从文本中提取数字、单位和指标信息。
    """

    # 中文数字单位映射
    CHINESE_NUMBERS = {
        "亿": 100000000,
        "万": 10000,
        "千": 1000,
        "百": 100,
    }

    # 中文常见后缀字符（用于边界检测）
    CHINESE_SUFFIX = r"[^\w\u4e00-\u9fff\s￥$%]*"  # 非单词字符、数字、下划线、$、%、￥

    # 常见指标模式
    METRIC_PATTERNS = [
        r"(MAU|月活跃|月活|monthly\s+active)",
        r"(DAU|日活跃|日活|daily\s+active)",
        r"(ARPU|平均每用户收入|arpu)",
        r"(ARR|年度经常性收入|年度\s+revenue)",
        r"(市场份额|market\s+share)",
        r"(营收|收入|revenue)",
        r"(GMV|交易总额|gmv)",
    ]

    # 单位模式
    UNIT_PATTERNS = [
        r"%",
        r"万元?",
        r"亿美元?",
        r"M?",  # Million
        r"B?",  # Billion
        r"K?",  # Thousand
        r"用户?",
        r"人?",
    ]

    def __init__(self) -> None:
        """初始化提取器。"""
        pass

    def extract_numbers(self, text: str) -> list[ExtractedNumber]:
        """从文本中提取数字。

        Args:
            text: 输入文本

        Returns:
            提取的数字列表
        """
        if not text or not text.strip():
            return []

        results: list[ExtractedNumber] = []

        # 1. 中文数字单位（亿、万）
        for cn_num, multiplier in self.CHINESE_NUMBERS.items():
            # 匹配数字+单位，后跟中文后缀或空白
            pattern = rf"(\d+(?:\.\d+)?)\s*{cn_num}{self.CHINESE_SUFFIX}"
            for match in re.finditer(pattern, text):
                try:
                    value = float(match.group(1)) * multiplier
                    unit = cn_num
                    metric = self._detect_context(text, match.start())
                    confidence = self._calculate_confidence(text, match.group())
                    results.append(ExtractedNumber(
                        text=match.group(),
                        value=value,
                        unit=unit,
                        context=metric,
                        confidence=confidence,
                    ))
                except (ValueError, IndexError):
                    continue

        # 2. M/B/K 单位
        for unit, multiplier in [("K", 1000), ("M", 1000000), ("B", 1000000000)]:
            # 匹配数字+单位，后跟中文后缀或空白
            pattern = rf"(\d+(?:\.\d+)?)\s*{unit}{self.CHINESE_SUFFIX}"
            for match in re.finditer(pattern, text):
                try:
                    value = float(match.group(1)) * multiplier
                    metric = self._detect_context(text, match.start())
                    confidence = self._calculate_confidence(text, match.group())
                    results.append(ExtractedNumber(
                        text=match.group(),
                        value=value,
                        unit=unit,
                        context=metric,
                        confidence=confidence,
                    ))
                except (ValueError, IndexError):
                    continue

        # 3. 百分比
        for match in re.finditer(rf"(\d+(?:\.\d*)?)\s*%{self.CHINESE_SUFFIX}", text):
            try:
                value = float(match.group(1))
                unit = "%"
                metric = self._detect_context(text, match.start())
                confidence = self._calculate_confidence(text, match.group())
                results.append(ExtractedNumber(
                    text=match.group(),
                        value=value,
                        unit=unit,
                        context=metric,
                        confidence=confidence,
                    ))
            except ValueError:
                continue

        return results

    def _detect_context(self, text: str, pos: int) -> str:
        """检测数字周围的上下文（指标名称）。

        Returns:
            指标名称，如 "MAU", "DAU", "unknown"
        """
        # 只搜索数字之后的文本（更准确匹配相关指标）
        lookbehind = 30  # 向前最多看30个字符
        lookahead = 50  # 向后最多看50个字符
        start = max(0, pos - lookbehind)
        end = min(len(text), pos + lookahead)
        post_number_text = text[pos:end]  # 只看数字后的文本

        # 检测指标类型
        metric = "unknown"

        # 在数字后的文本中查找指标
        for pattern in self.METRIC_PATTERNS:
            match = re.search(pattern, post_number_text, re.IGNORECASE)
            if match:
                # 计算匹配位置在原文本中的位置
                match_start_in_text = match.start()
                # 转换为在 post_number_text 中的相对位置
                match_start_relative = match_start_in_text - pos
                # 只选择紧跟数字的指标（距离为0最优先）
                if match_start_relative == 0:
                    metric = match.group(1)
                    break

        return metric

    def _calculate_confidence(self, text: str, number_text: str) -> float:
        """计算提取置信度。

        基于以下因素：
        - 是否有明确的数据来源标记
        - 数字格式的规范性
        - 上下文的完整性
        """
        confidence = 0.5  # 基础置信度

        # 检查来源标记
        source_indicators = ["官方", "发布", "财报", "数据显示", "据"]
        if any(indicator in text for indicator in source_indicators):
            confidence += 0.20

        # 检查数字格式
        if re.match(r"^\d+\.\d+$", number_text):
            confidence += 0.10  # 小数格式更精确

        # 检查上下文长度
        if len(text) > 20:
            confidence += 0.05

        # 检查是否有单位
        if any(search in number_text for search in ["%", "K", "M", "B", "万", "亿"]):
            confidence += 0.10

        return min(1.0, confidence)


class QuantitativeValidator:
    """定量数据验证器。

    执行跨来源交叉验证，检测数值冲突。
    """

    def __init__(self, tolerance_threshold: float = 0.2) -> None:
        """初始化验证器。

        Args:
            tolerance_threshold: 相对容忍阈值，默认 20%
        """
        self._tolerance_threshold = tolerance_threshold

    def cross_validate(
        self,
        numbers: list[ExtractedNumber],
        sources: list[str],
    ) -> ValidationResult:
        """跨来源交叉验证数字。

        Args:
            numbers: 提取的数字列表
            sources: 来源 URL 列表

        Returns:
            验证结果
        """
        if not numbers:
            return ValidationResult(
                metric_name="unknown",
                values=[],
                consensus_value=None,
                status=VerificationStatus.UNVERIFIED,
                confidence_adjustment=0.0,
            )

        # 推断指标名称
        metric_name = self._infer_metric_name(numbers)

        # 根据来源数量确定状态
        if len(sources) == 0:
            status = VerificationStatus.UNVERIFIED
            consensus = None
            adjustment = -0.10  # 无来源，降低置信度
        elif len(sources) == 1:
            status = VerificationStatus.SINGLE_SOURCE
            # 清理共识值：移除来源前缀
            consensus = self._clean_consensus_value(numbers[0].text)
            adjustment = 0.0
        else:
            # 多来源：检查一致性
            is_consistent, consensus = self._check_consistency(numbers)
            if is_consistent:
                status = VerificationStatus.CROSS_VALIDATED
                adjustment = 0.05  # 交叉验证成功，提升置信度
            else:
                status = VerificationStatus.DISPUTED
                consensus = None
                adjustment = -0.15  # 冲突，降低置信度

        return ValidationResult(
            metric_name=metric_name,
            values=numbers,
            consensus_value=consensus,
            status=status,
            confidence_adjustment=adjustment,
        )

    def _clean_consensus_value(self, text: str) -> str:
        """清理共识值，移除来源前缀。

        例如: "来源A：100万" -> "100万"
        """
        # 更简单直接的清理方式
        # 1. 移除常见的来源前缀关键词
        prefixes_to_remove = ["来源", "据"]
        cleaned = text

        for prefix in prefixes_to_remove:
            # 检查是否以该前缀开头（支持中英文冒号）
            if cleaned.startswith(prefix):
                # 跳过前缀，查找冒号位置
                after_prefix = cleaned[len(prefix):]
                # 查找第一个冒号（中英文）
                colon_pos = -1
                for i, char in enumerate(after_prefix):
                    if char in [":", "："]:
                        colon_pos = i
                        break
                if colon_pos >= 0:
                    cleaned = after_prefix[colon_pos + 1:]
                    break

        return cleaned.strip()

    def _infer_metric_name(self, numbers: list[ExtractedNumber]) -> str:
        """从提取的数字推断指标名称。"""
        if not numbers:
            return "unknown"

        # 使用第一个数字的上下文
        first_context = numbers[0].context or "unknown"
        return first_context

    def _check_consistency(self, numbers: list[ExtractedNumber]) -> tuple[bool, str | None]:
        """检查数字是否一致。

        Returns:
            (是否一致, 共识值文本)
        """
        if len(numbers) < 2:
            return True, numbers[0].text if numbers else None

        # 计算相对差异
        values = [n.value for n in numbers]
        min_val = min(values)
        max_val = max(values)

        if min_val == 0:
            return False, None

        relative_diff = (max_val - min_val) / min_val

        if relative_diff <= self._tolerance_threshold:
            # 一致：使用平均值或中位数
            avg_val = sum(values) / len(values)
            return True, f"{avg_val:,.0f}"
        else:
            return False, None


# 导出符号
__all__ = [
    "VerificationStatus",
    "QuantitativeEvidence",
    "ExtractedNumber",
    "ValidationResult",
    "QuantitativeExtractor",
    "QuantitativeValidator",
]
