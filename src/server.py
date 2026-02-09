"""Web 服务器入口模块。

提供独立的 Web 服务器启动方式。
"""

import sys
from pathlib import Path

import click


def run_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """运行 Web 服务器。

    Args:
        host: 主机地址
        port: 端口号
        reload: 是否自动重载
    """
    try:
        import uvicorn
    except ImportError:
        click.echo("✗ 需要安装 uvicorn: pip install uvicorn[standard]", err=True)
        sys.exit(1)

    click.echo(f"🚀 启动 CompetitorSwarm Web 服务器", err=True)
    click.echo(f"   地址: http://{host}:{port}", err=True)
    click.echo(f"   文档: http://{host}:{port}/api/docs", err=True)
    click.echo("", err=True)
    click.echo("按 Ctrl+C 停止服务器", err=True)

    uvicorn.run(
        "src.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CompetitorSwarm Web 服务器")
    parser.add_argument("--host", "-h", default="127.0.0.1", help="主机地址")
    parser.add_argument("--port", "-p", type=int, default=8000, help="端口号")
    parser.add_argument("--reload", action="store_true", help="自动重载（开发模式）")

    args = parser.parse_args()

    run_server(host=args.host, port=args.port, reload=args.reload)
