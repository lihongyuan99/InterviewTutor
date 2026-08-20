#!/bin/bash

# InterviewTutor 一键启动所有服务
# 同时启动后端和前端

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🚀 InterviewTutor 一键启动..."
echo "========================"
echo ""

# 检查虚拟环境 tutor
# 检测顺序：1) VIRTUAL_ENV 包含 tutor  2) CONDA_PREFIX 包含 tutor  3) 项目目录有 tutor
if [ -n "$VIRTUAL_ENV" ] && [[ "$VIRTUAL_ENV" == *"tutor" ]]; then
    echo "✅ 已激活虚拟环境：tutor"
elif [ -n "$CONDA_PREFIX" ] && [[ "$CONDA_PREFIX" == *"tutor" ]]; then
    echo "✅ 已激活 conda 环境：tutor"
elif [ -d "$PROJECT_DIR/tutor" ]; then
    VENV_DIR="$PROJECT_DIR/tutor"
    echo "✅ 找到虚拟环境：tutor/"
    source "$VENV_DIR/bin/activate"
else
    echo "⚠️  未找到虚拟环境 tutor"
    echo ""
    read -p "是否自动配置虚拟环境？(yes/no): " CONFIRM
    if [ "$CONFIRM" = "yes" ]; then
        echo ""
        echo "🔧 正在创建虚拟环境..."
        cd "$PROJECT_DIR"
        python3 -m venv tutor

        echo "🔧 激活虚拟环境..."
        source tutor/bin/activate

        echo "🔧 安装 Python 依赖..."
        pip install -r requirements.txt

        echo ""
        echo "✅ 虚拟环境配置完成!"
    else
        echo "❌ 已取消"
        exit 1
    fi
fi

# 检查 uvicorn 是否可用
if ! command -v uvicorn &> /dev/null; then
    echo "⚠️  未找到 uvicorn，正在安装依赖..."
    cd "$PROJECT_DIR" && pip install -r requirements.txt
fi

# 检查 node_modules
if [ ! -d "$PROJECT_DIR/web/node_modules" ]; then
    echo "⚠️  未找到 node_modules，正在安装前端依赖..."
    cd "$PROJECT_DIR/web" && npm install
fi

echo "✅ 环境检查完成，开始启动服务..."
echo ""

# 启动后端（后台运行；8000 预留给本地 Embedding 服务）
echo "🔧 启动后端服务 (port 8001)..."
cd "$PROJECT_DIR"
uvicorn app.main:app --host 127.0.0.1 --port 8001 &
BACKEND_PID=$!
echo "   后端 PID: $BACKEND_PID"

# 等待后端启动
sleep 3

# 启动前端（后台运行）
echo "🎨 启动前端服务 (port 5173)..."
cd "$PROJECT_DIR/web"
npm run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!
echo "   前端 PID: $FRONTEND_PID"

# 等待前端启动
sleep 3

echo ""
echo "========================"
echo "✅ 所有服务已启动!"
echo "   后端：http://127.0.0.1:8001"
echo "   前端：http://127.0.0.1:5173"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo "========================"
echo ""

# 等待用户 Ctrl+C
wait $BACKEND_PID $FRONTEND_PID
