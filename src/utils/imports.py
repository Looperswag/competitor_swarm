"""统一的导入工具模块。

集中管理可选依赖的导入，提供优雅的降级支持。
"""

# Signal 相关导入（所有 Agent 共用）
try:
    from src.schemas.signals import (
        Signal,
        SignalType,
        Sentiment,
        Actionability,
        Dimension,
        SignalFilter,
    )
    SIGNALS_AVAILABLE = True
except ImportError:
    SIGNALS_AVAILABLE = False


__all__ = [
    "SIGNALS_AVAILABLE",
    "Signal",
    "SignalType",
    "Sentiment",
    "Actionability",
    "Dimension",
    "SignalFilter",
]
