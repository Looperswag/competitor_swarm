#!/usr/bin/env python3
"""CompetitorSwarm 主程序入口。

竞品分析 Swarm 智能系统 - 使用多 Agent 协作进行深度竞品分析。
"""

import logging
import sys

import click

from src.cli import cli


def setup_logging() -> None:
    """配置日志系统。"""
    # 设置根日志级别
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
        ],
    )

    # 降低 httpx 的日志级别，避免干扰进度条显示
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    """主入口函数。"""
    setup_logging()

    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n\n操作已取消", err=True)
        sys.exit(130)
    except Exception as e:
        logging.exception("程序异常退出")
        click.echo(f"\n✗ 错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
