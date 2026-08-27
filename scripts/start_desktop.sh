#!/bin/bash

# InterviewTutor 桌面模式一键启动
# 单进程：FastAPI 后端 + 同源前端产物 + pywebview 原生窗口

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "🖥️  InterviewTutor 桌面模式启动..."
echo "================================"

# 检测虚拟环境 tutor（与 start_all.sh 一致）
if [ -n "$VIRTUAL_ENV" ] && [[ "$VIRTUAL_ENV" == *"tutor" ]]; then
    echo "✅ 已激活虚拟环境：tutor"
elif [ -n "$CONDA_PREFIX" ] && [[ "$CONDA_PREFIX" == *"tutor" ]]; then
    echo "✅ 已激活 conda 环境：tutor"
elif [ -d "$PROJECT_DIR/tutor" ]; then
    source "$PROJECT_DIR/tutor/bin/activate"
    echo "✅ 已激活虚拟环境：tutor/"
else
    echo "❌ 未找到虚拟环境 tutor，请先参考 README 完成环境安装"
    exit 1
fi

# 检查桌面窗口依赖
if ! python -c "import webview" &> /dev/null; then
    echo "⚠️  未找到 pywebview，正在安装..."
    pip install pywebview
fi

# 前端构建产物缺失时自动构建（--skip-build 可跳过）
if [ ! -f "$PROJECT_DIR/web/dist/index.html" ] && [ "$1" != "--skip-build" ]; then
    echo "⚠️  未找到前端构建产物，正在构建 web/dist ..."
    if [ ! -d "$PROJECT_DIR/web/node_modules" ]; then
        (cd "$PROJECT_DIR/web" && npm install) || exit 1
    fi
    (cd "$PROJECT_DIR/web" && npm run build) || exit 1
fi

echo "🚀 打开桌面窗口..."
python "$PROJECT_DIR/desktop.py" "$@"
