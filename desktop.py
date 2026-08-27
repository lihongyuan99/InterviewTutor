"""InterviewTutor 桌面模式启动器。

在同一进程内启动 FastAPI 后端（同源伺服 web/dist 前端构建产物），
并用 pywebview 打开原生桌面窗口（macOS 使用系统 WKWebView）。

用法：
    python desktop.py                 # 桌面窗口模式
    python desktop.py --server-only   # 只启动服务不开窗口（调试用）
    python desktop.py --port 8010     # 指定端口

首次运行前需要构建前端产物：
    cd web && npm install && npm run build
"""

import argparse
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
APP_ICON_PATH = PROJECT_ROOT / "assets" / "icon.png"

HOST = "127.0.0.1"
START_PORT = 8001        # 与开发模式保持一致的默认端口（8000 预留给本地 Embedding 服务）
PORT_PROBE_RANGE = 20    # 默认端口被占用时向后探测的范围
HEALTH_TIMEOUT = 180     # 后端冷启动可能较慢（首次加载模型），宽松超时
HEALTH_INTERVAL = 0.5


def find_free_port() -> int:
    """从 START_PORT 开始探测可用端口。"""
    for port in range(START_PORT, START_PORT + PORT_PROBE_RANGE):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"端口 {START_PORT}~{START_PORT + PORT_PROBE_RANGE - 1} 均被占用，"
        f"请用 --port 指定其他端口"
    )


def wait_until_ready(url: str, timeout: float = HEALTH_TIMEOUT) -> bool:
    """轮询健康检查，等待后端就绪。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        time.sleep(HEALTH_INTERVAL)
    return False


def serve_forever(server) -> None:
    """阻塞当前线程直到 Ctrl+C（server-only / 降级到浏览器模式时使用）。"""
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True


def main() -> int:
    parser = argparse.ArgumentParser(description="InterviewTutor 桌面模式启动器")
    parser.add_argument(
        "--server-only", action="store_true",
        help="只启动后端服务，不打开桌面窗口（调试用）",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=f"指定端口（默认自动探测，从 {START_PORT} 开始）",
    )
    args = parser.parse_args()

    # 后端以项目根目录为工作目录（data/、memory/ 等相对路径依赖它）
    os.chdir(PROJECT_ROOT)
    sys.path.insert(0, str(PROJECT_ROOT))

    dist_index = PROJECT_ROOT / "web" / "dist" / "index.html"
    if not dist_index.is_file():
        print("未找到前端构建产物 web/dist，请先构建：")
        print("    cd web && npm install && npm run build")
        return 1

    try:
        import uvicorn

        from app.main import app
    except ImportError as exc:
        print(f"缺少后端依赖：{exc}")
        print("请先安装：pip install -r requirements.txt")
        return 1

    port = args.port or find_free_port()
    url = f"http://{HOST}:{port}"

    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True, name="uvicorn").start()

    print(f"正在启动后端 {url} ...")
    if not wait_until_ready(url):
        print("后端启动超时，请查看上方日志排查问题。")
        return 1
    print(f"服务就绪：{url}")

    if args.server_only:
        print("server-only 模式：按 Ctrl+C 退出。")
        serve_forever(server)
        return 0

    try:
        import webview
    except ImportError:
        print("缺少桌面窗口依赖 pywebview，请安装：pip install pywebview")
        print(f"已降级为浏览器模式，请访问 {url}（Ctrl+C 退出）")
        serve_forever(server)
        return 0

    window = webview.create_window(
        "InterviewTutor",
        url,
        width=1440,
        height=900,
        min_size=(1024, 680),
    )
    # pywebview 6.x：图标参数在 start() 上（各平台 GUI 实现从全局 _state['icon'] 读取，
    # macOS 在窗口创建流程内通过 NSApplication.setApplicationIconImage_ 设置 Dock 图标）
    webview.start(
        icon=str(APP_ICON_PATH) if APP_ICON_PATH.is_file() else None,
    )

    # 窗口关闭后退出进程（torch 等库可能存在非守护线程，直接结束最可靠）
    del window
    server.should_exit = True
    time.sleep(1)
    os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
