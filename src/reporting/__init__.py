"""报告增强模块。

提供引用管理、章节生成、格式化和可视化功能。
"""

from src.reporting.citations import Citation, CitationManager
from src.reporting.sections import SectionGenerator
from src.reporting.formatters import Formatters
from src.reporting.visualizer import HTMLReportGenerator, get_html_generator, reset_html_generator

__all__ = [
    "Citation",
    "CitationManager",
    "SectionGenerator",
    "Formatters",
    "HTMLReportGenerator",
    "get_html_generator",
    "reset_html_generator",
]
