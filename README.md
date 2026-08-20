# InterviewTutor

> 🎓 面向 AI Agent / LLM 应用工程岗位的个性化技术面试训练 Agent

InterviewTutor 通过**题库 RAG、模拟追问、结构化评分、错题复习**，帮助用户从「会背概念」提升到「能讲工程决策与实践」。

## ✨ 核心能力

- **🧠 多智能体协作** - 基于 LangGraph 构建 Analyzer / Tutor / Judge / Inquiry 等专业角色，智能路由不同学习场景
- **📚 面试题库 RAG** - 485 道领域题（17 个维度）解析入库，混合检索（Embedding 语义 + 关键词兜底），带引用来源讲解
- **🎯 三种训练模式** - 刷题、复习、学习，覆盖「出题 → 作答 → 结构化评分 → 追问 → 高手答 → 掌握度记录」完整闭环
- **📊 结构化评分** - L1-L5 回答质量模型，多维度打分 + 已覆盖点/缺失点/改进建议，防答案泄露
- **💡 苏格拉底式教学** - 拒绝填鸭式回答，通过启发式提问引导独立思考（支持多种教学风格切换）
- **🔄 流式响应** - SSE 实时输出，提供流畅的对话体验
- **📝 自动记忆压缩** - 智能管理长对话上下文，支持语义检索历史内容
- **🧩 知识图谱** - 自动从对话中抽取实体关系，构建个人知识网络
- **🏷️ 任务自动命名** - 会话累计足够消息后，自动为「新的学习」占位任务生成简洁标题
- **🖥️ Web 控制台** - 现代化 Web 界面，随时随地学习

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     表现层 (Presentation)                     │
│                       Web Dashboard                           │
│                       (React + Vite)                          │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    API 网关 (FastAPI)                        │
│  /chat  /tasks  /notes  /agent  /kg  /interview  /settings   │
└──────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
┌─────────────────────────┐          ┌─────────────────────────┐
│    通用对话 Agent         │          │   面试训练状态机          │
│   (LangGraph 多智能体)    │          │   (显式工作流)            │
├─────────────────────────┤          ├─────────────────────────┤
│ Analyzer / Tutor / Judge │          │ Interviewer / Evaluator  │
│ / Inquiry / Plan /       │          │ / Coach                 │
│ Aggregator               │          │ start → asking →        │
└─────────────────────────┘          │ awaiting_answer →       │
          │                          │ evaluating → reviewing   │
          ▼                          └───────────┬─────────────┘
┌─────────────────────────────────────────────────────────────┐
│                   数据层 (Memory & Storage)                   │
├──────────────┬──────────────┬───────────────────────────────┤
│   Sessions   │    Notes     │  题库 (SQLite + FTS5)          │
│   (JSON)     │  (Markdown)  │  向量索引 (Embedding)          │
│              │              │  知识图谱 (NetworkX)           │
└──────────────┴──────────────┴───────────────────────────────┘
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- DeepSeek API Key（或其他 OpenAI 兼容 / Anthropic 模型的 API Key）

### 安装

```bash
# 克隆仓库
git clone <your-repo-url>
cd InterviewTutor

# 创建并激活虚拟环境（项目默认使用 tutor 目录）
python3 -m venv tutor
source tutor/bin/activate        # Windows: tutor\Scripts\activate

# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd web
npm install
cd ..
```

### 配置

创建 `.env` 文件（可选，也支持在 Web 控制台的「设置」页动态配置模型服务）：

```ini
# DeepSeek API（或其他 OpenAI 兼容服务）
DEEPSEEK_API_KEY=sk-your-api-key
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat

# 可选 - 百度搜索（用于联网查询）
BAIDU_API_KEY=bce-v3/your-api-key
```

> 模型服务与教学风格也可以启动后在前端「设置」页通过界面配置，保存后无需重启后端。

### 启动

**方式一：一键启动（推荐）**

```bash
./scripts/start_all.sh
```

**方式二：分别启动**

```bash
# 终端 1 - 后端服务
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

# 终端 2 - 前端服务
cd web
npm run dev -- --host 127.0.0.1 --port 5173
```

### 访问

- **Web 控制台**: http://127.0.0.1:5173
- **API 文档**: http://127.0.0.1:8001/docs

## 📁 项目结构

```
InterviewTutor/
├── app/                          # 后端核心（Python / FastAPI）
│   ├── api/                      # API 路由层
│   │   ├── chat.py               # 对话接口（支持流式 SSE）
│   │   ├── tasks.py              # 任务管理（增删改查、归档）
│   │   ├── notes.py              # 笔记与学习计划数据
│   │   ├── task_plan.py          # 学习计划生成/确认
│   │   ├── history.py            # 会话历史与每日/任务总结
│   │   ├── kg.py                 # 知识图谱
│   │   ├── interview.py          # 面试训练接口
│   │   └── settings.py           # 模型服务与教学风格设置
│   ├── core/                     # 核心引擎
│   │   ├── agent_builder.py      # LangGraph 多智能体构建
│   │   ├── models.py             # AgentState 与结构化输出
│   │   ├── prompts.py            # 各角色提示词
│   │   ├── memory.py             # 会话/任务/笔记持久化 + 自动命名
│   │   ├── context_rag.py        # 历史对话记忆 RAG
│   │   ├── vector_store.py       # 对话向量库 (FAISS)
│   │   ├── llm_factory.py        # 模型创建
│   │   ├── llm_settings.py       # 模型服务配置持久化
│   │   ├── learning_profile.py   # 学习画像
│   │   ├── tools.py              # 联网搜索工具
│   │   ├── summary/              # 总结生成器
│   │   └── task_plan/            # 学习计划逻辑
│   ├── knowledge/                # 面试知识库（题库底座）
│   │   ├── schema.py             # InterviewQuestion 等数据模型
│   │   ├── parser.py             # Markdown → 结构化题目
│   │   ├── repository.py         # SQLite + FTS5 存储
│   │   ├── indexer.py            # Embedding 向量索引
│   │   ├── retriever.py          # 混合检索
│   │   └── service.py            # 统一入口
│   ├── interview/                # 面试训练状态机
│   │   ├── workflow.py           # 刷题/复习/模拟面试工作流
│   │   ├── learn.py              # 学习模式（RAG 问答）
│   │   ├── models.py             # 会话/评分/进度模型
│   │   ├── prompts.py            # Interviewer/Evaluator/Coach 提示词
│   │   ├── progress.py           # 掌握度与复习调度
│   │   └── session_store.py      # 会话持久化
│   ├── knowledge_graph/          # 知识图谱模块
│   └── main.py                   # FastAPI 入口
│
├── web/                          # Web 前端（React + Vite）
│   └── src/app/components/       # 页面组件
│       ├── TutorSession.tsx      # 主对话界面
│       ├── InterviewPage.tsx     # 刷题/复习模式
│       ├── LearnPage.tsx         # 学习模式
│       ├── ProgressPage.tsx      # 进度/错题/薄弱维度
│       ├── TaskSidebar.tsx       # 任务侧边栏
│       └── ...
│
├── knowledge/                    # 领域知识库（36 个 Markdown，485 道题）
├── data/                         # 构建产物
│   ├── knowledge.db              # 题库 SQLite（含 FTS5）
│   └── knowledge_parsed.json     # 解析后的结构化题目
├── memory/                       # 运行时数据
│   ├── sessions/                 # 对话会话 (JSON)
│   ├── notes/                    # 学习笔记与任务计划
│   ├── task_index/               # 任务索引
│   ├── interview_sessions/       # 面试训练会话
│   ├── interview_progress/       # 答题进度
│   └── learner_profiles/         # 学习画像
├── scripts/                      # 启动与建索引脚本
│   ├── start_all.sh              # 一键启动
│   └── build_knowledge_index.py  # 题库解析与索引构建
├── tests/                        # 单元测试
├── requirements.txt
└── .env
```

## 🧠 多智能体工作流

### 通用对话 Agent

```
用户输入
    │
    ▼
┌─────────┐
│Analyzer │ ← 意图识别 & 任务路由（输出 ExecutionPlan）
└────┬────┘
     │
     ├─── request_plan? ───→ [Plan] 生成学习计划
     │
     ├─── needs_tutor/judge ─→ [Tutor + Judge] 并行执行（支持联网搜索）
     │
     ├─── needs_inquiry? ───→ [Inquiry] 苏格拉底式追问
     │
     ▼
┌──────────┐
│Aggregator│ ← 融合多模块输出 + 记忆压缩 + 画像更新 + 持久化
└──────────┘
```

### 面试训练状态机

```
start → asking → awaiting_answer → evaluating → reviewing → completed
```

| 角色 | 职责 | 防泄露约束 |
|------|------|-----------|
| **Interviewer** | 出题 + 针对性追问 | 出题阶段**看不到**标准答案 |
| **Evaluator** | 结构化 L1-L5 评分 | 用户作答后**才**接触标准答案 |
| **Coach** | 复盘反馈（亮点/缺失点/建议） | - |

## 🎯 三种训练模式

| 模式 | 路由 | 数据流 | 是否 RAG |
|------|------|--------|---------|
| **刷题模式** | `/interview` | SQL 抽题 → 结构化评分 → 追问 → 高手答 | 否 |
| **复习模式** | `/interview`（mode=review） | 复习队列选题 → 评分（按掌握度升序） | 否 |
| **学习模式** | `/interview/learn` | 检索召回 → 带 `[n]` 引用讲解 | 是 |

## 🔌 API 参考

### 对话接口

```http
POST /api/v1/chat
Content-Type: application/json

{
  "message": "什么是注意力机制？",
  "task_id": "task_1",        // 可选
  "session_id": "session_1",  // 可选，自动生成
  "topic": "深度学习"          // 可选
}
```

```http
POST /api/v1/chat/stream      # 返回 NDJSON 事件流（SSE）
```

### 面试训练

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/v1/interview/start` | 开始训练（practice/mock/review），返回题目（不含答案） |
| POST | `/api/v1/interview/answer` | 提交作答，返回结构化评分 + 追问 |
| POST | `/api/v1/interview/review` | 展示高手答与复盘反馈 |
| POST | `/api/v1/interview/ask` | 学习模式 RAG 问答（带引用） |
| GET | `/api/v1/interview/progress` | 学习进度、复习队列、错题本、薄弱维度 |

### 任务管理

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/v1/tasks` | 获取任务列表 |
| POST | `/api/v1/tasks` | 创建任务 |
| PATCH | `/api/v1/tasks/{id}` | 更新任务标题/图标 |
| PATCH | `/api/v1/tasks/{id}/status` | 归档/恢复 |
| DELETE | `/api/v1/tasks/{id}` | 删除任务 |

### 学习计划

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/v1/agent/task-plan` | 生成学习计划 |
| POST | `/api/v1/agent/task-plan/confirm` | 确认计划 |
| POST | `/api/v1/agent/task-plan/from-chat` | 从对话历史生成计划 |

### 知识图谱

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/v1/kg/build-from-task` | 从任务会话构建图谱 |
| GET | `/api/v1/kg/get-task-kg` | 获取图谱数据 |
| GET | `/api/v1/kg/doc-graph` | 获取文档知识图谱 |

### 模型设置

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/v1/settings/llm` | 获取模型服务配置（脱敏） |
| PUT | `/api/v1/settings/llm` | 更新模型服务与教学风格 |

> 完整 API 文档请访问 http://127.0.0.1:8001/docs

## ⚙️ 配置说明

### 模型服务与教学风格

模型服务（OpenAI 兼容 / Anthropic）与教学风格（苏格拉底式 / 直接讲解 / 问答互动 / 自定义）可在 Web 控制台「设置」页动态配置，保存在 `memory/llm_settings.json`，无需重启。

### 知识库构建

```bash
# 仅解析（不调模型、不下载 Embedding），输出统计与可检查 JSON
python scripts/build_knowledge_index.py --parse-only

# 构建索引（含 Embedding 向量）
python scripts/build_knowledge_index.py

# 跳过 Embedding（仅关键词检索）
python scripts/build_knowledge_index.py --no-embedding
```

解析结果：**485 道题、17 个维度**；检索评测：Hit@1 83.3%、Hit@3 100%、Hit@5 100%。

### 核心参数 (app/core/config.py)

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `MODEL_NAME` | deepseek-chat | 主模型 |
| `RAG_ENABLED` | True | 启用对话记忆语义检索 |
| `RAG_TOP_K` | 3 | 记忆检索返回数量 |
| `RAG_EMBEDDING_MODEL` | Qwen3-Embedding-0.6B-4bit-DWQ | 对话记忆 Embedding 模型（已统一为 Qwen3） |
| `KNOWLEDGE_EMBEDDING_MODEL` | Qwen3-Embedding-0.6B-4bit-DWQ | 题库 Embedding 模型 |
| `KNOWLEDGE_EMBEDDING_BASE_URL` | http://127.0.0.1:8000/v1 | 题库 Embedding 服务地址 |
| `KNOWLEDGE_EMBEDDING_DIM` | 1024 | 题库 Embedding 向量维度 |
| `MAX_ITERATIONS` | 5 | 苏格拉底追问上限 |

### 内存管理 (app/core/context_rag.py)

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `COMPRESSION_THRESHOLD` | 16 | 触发压缩的消息数 |
| `KEEP_WINDOW` | 5 | 保留的原始消息数 |
| `DISPLAY_WINDOW` | 12 | 显示的历史消息数 |

### 任务自动命名 (app/core/memory.py)

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `AUTO_TITLE_MIN_USER_MSGS` | 4 | 触发自动命名的累计用户消息数 |

## 🛠️ 技术栈

### 后端

- **框架**: FastAPI, Uvicorn
- **Agent**: LangGraph, LangChain
- **模型**: DeepSeek / OpenAI 兼容 / Anthropic（可配置）
- **向量检索**: FAISS + Sentence-Transformers + Qwen3-Embedding
- **知识图谱**: NetworkX, PyVis, KeyBERT, SpaCy

### Embedding 模型（统一为 Qwen3）

两条检索链路**统一使用同一个 Embedding 模型**，共用同一套本地服务与客户端：

| 用途 | Embedding 模型 | 维度 | 部署方式 |
|------|---------------|------|---------|
| **面试题库检索**（`app/knowledge/`） | Qwen3-Embedding-0.6B-4bit-DWQ | 1024 | 本地 OpenAI 兼容服务（默认 `http://127.0.0.1:8000/v1`） |
| **对话记忆检索**（`app/core/vector_store.py`） | Qwen3-Embedding-0.6B-4bit-DWQ | 1024 | 同上 |

**说明**：

- 统一客户端位于 `app/core/embedding_client.py`（`Qwen3EmbeddingClient`），题库与对话记忆共用，实现 LangChain `Embeddings` 接口（`embed_documents` / `embed_query`），可直接作为 FAISS 的 embeddings 参数。
- **题库向量化**：输入由 `题目 + 专家答案前 1500 字` 拼接而成，作为学习模式（`/interview/learn`）语义检索主通道。
- **对话记忆向量化**：把用户历史问答对（`User: ... Assistant: ...`）写入 FAISS，作为通用对话 Agent 的历史记忆召回通道。
- 调用时使用 `requests` 而非 `openai` SDK，以规避本地 `omlx` 服务对 httpx 的 502 兼容问题。
- 模型本身为中文友好（Qwen 系列），相比早期使用的 `all-MiniLM-L6-v2`（英文模型，384 维），中文语义召回能力显著提升。

### 前端

- **框架**: React 18, Vite 6, React Router
- **UI**: Material-UI, Radix UI, TailwindCSS 4
- **可视化**: Plotly.js, Recharts
- **Markdown**: React-Markdown, KaTeX

## 📊 数据格式

### 会话状态 (memory/sessions/*.json)

```json
{
  "session_id": "task_1__20260101__120000",
  "task_id": "task_1",
  "topic": "深度学习",
  "conversation_summary": "长期记忆摘要...",
  "summarized_msg_count": 16,
  "messages": [
    {"type": "human", "data": {"content": "..."}},
    {"type": "ai", "data": {"content": "..."}}
  ]
}
```

### 面试题目 (app/knowledge/schema.py)

```json
{
  "id": "architecture-react-vs-plan",
  "dimension": "architecture",
  "title": "ReAct 与 Plan-and-Execute",
  "question": "你用 ReAct 还是 Plan-and-Execute？为什么？",
  "expert_answer": "...",
  "key_points": ["选择标准", "适用场景"],
  "followups": ["Planner 和 Executor 如何通信？"],
  "companies": ["腾讯", "字节"],
  "difficulty": 3,
  "source_file": "knowledge/01-architecture-design/index.md"
}
```

## 🧪 测试

```bash
# 使用项目虚拟环境运行全部测试
tutor/bin/python -m pytest tests/
```

覆盖：知识解析、知识检索、面试工作流、学习模式（共 35 个用例）。

## 📄 许可

本项目采用 [MIT License](LICENSE)。

> 知识库内容来自外部上游；若计划公开发布或商业使用，请确认上游许可、保留来源信息并检查内容授权。
