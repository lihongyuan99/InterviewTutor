# AI 面试训练 Agent 改造 Handoff

更新时间：2026-08-19

## 1. 目标定位

将本项目从通用学习助手，收敛为：

> 面向 AI Agent / LLM 应用工程岗位的个性化技术面试训练 Agent，通过题库 RAG、模拟追问、结构化评分和错题复习，帮助用户从“会背概念”提升到“能讲工程决策与实践”。

第一版不要同时覆盖简历修改、行为面、求职策略等全部场景。优先完成一个可验证的核心闭环：

```text
选择方向或公司
→ 系统选择一道题
→ 用户作答
→ 结构化评分
→ 指出缺失点
→ 生成一道针对性追问
→ 展示高手回答
→ 保存掌握度与错题记录
```

## 2. 当前项目现状

### 现有能力

- 后端：FastAPI。
- Agent 编排：LangGraph。
- 模型：DeepSeek Chat。
- 现有角色：Analyzer、Tutor、Judge、Inquiry、Plan、Aggregator。
- 支持学习计划、会话持久化、摘要压缩、学习画像、知识图谱和联网搜索。
- 前端：React + Vite。
- 主 Agent 已使用 `app/core/context_rag.py` 构建上下文。

### 当前 RAG 的边界

现有 RAG 是“历史对话记忆 RAG”，不是面试知识库 RAG：

- `app/core/vector_store.py` 将用户与助手的历史对话对写入 FAISS。
- `app/core/context_rag.py` 根据新问题召回同一任务下的历史对话。
- `app/core/config.py` 中 `RAG_ENABLED=True`，默认召回 3 条。
- 向量检索无结果时会回退到字符级 Jaccard 检索。

面试知识库必须使用独立索引，不能直接混入对话记忆向量库。

## 3. `knowledge/` 目录检查结果

- 目录约 1.3 MB。
- 共 36 个 Markdown 文件。
- 实际检测到约 486 个 `## Q` / `### Q` 问题段落，分布在约 28 个文件中。
- 内容覆盖 Agent 架构、工具调用、容错、记忆、评估、多 Agent、Prompt、RAG、训练、工程实践和项目深挖等方向。
- `coaching-methodology/interview-coaching.md` 提供了 L1–L5 回答质量模型，可直接作为评分体系基础。

### 已知数据问题

1. `knowledge/README.md` 声称“每个 Markdown 文件代表一道题”，但实际很多 `index.md` 包含几十道题。
2. 解析器必须同时支持 `## Q：...` 和 `### Q：...`。
3. 部分补充目录与主目录概念重叠，例如：
   - `01-architecture/` 与 `01-architecture-design/`
   - `04-rag/` 与 `09-rag-retrieval/`
   - `05-multi-agent/` 与 `06-multi-agent-collab/`
4. `knowledge/README.md` 提到 `npm run build-kb`，但项目根目录没有 `package.json`，该命令目前不能使用。
5. 知识内容来自外部上游；若项目计划公开发布或商业使用，需要确认上游许可、保留来源信息并检查内容授权。

## 4. 推荐的产品模式

### 学习模式

- 用户可以直接提问。
- Retriever 召回相关题目和专家答案。
- Tutor 基于知识库解释，并标明知识来源。

### 刷题模式

- 系统先出题，不泄露标准答案。
- 用户回答后，Judge 根据知识库和 rubric 评分。
- Inquiry 只生成一个针对缺失点的追问。
- 完成后展示高手回答并更新掌握度。

### 模拟面试模式

- 连续提问，中途不展示答案和详细提示。
- 根据目标公司、岗位和难度选题。
- 面试结束后统一输出能力雷达、主要问题和复习建议。

MVP 只需先完成“刷题模式”。

## 5. 数据与存储边界

必须拆分三类数据：

| 数据 | 内容 | 建议存储 |
|---|---|---|
| 领域知识 | 题目、专家答案、考察点、追问、来源 | SQLite + 独立向量索引 |
| 对话记忆 | 用户过去聊过和学过什么 | 保留现有会话 JSON 与 FAISS |
| 学习进度 | 答题次数、评分、薄弱点、复习时间 | SQLite 或独立 JSON |

不要复用 `memory/vector_store/<task_id>` 存放知识题库。

建议路径：

```text
data/
├── knowledge.db
└── knowledge_index/

memory/
├── vector_store/       # 保留：用户历史对话
└── interview_progress/ # 新增：用户答题进度
```

## 6. 建议的知识记录模型

每一道主问题解析为一条 `InterviewQuestion`：

```json
{
  "id": "architecture-react-vs-plan",
  "dimension": "architecture",
  "title": "ReAct 与 Plan-and-Execute",
  "question": "你用 ReAct 还是 Plan-and-Execute？为什么？",
  "novice_answer": "...",
  "expert_answer": "...",
  "key_points": ["选择标准", "适用场景", "工程取舍"],
  "followups": ["Planner 和 Executor 如何通信？"],
  "companies": ["腾讯", "字节"],
  "tags": ["ReAct", "Plan-and-Execute"],
  "difficulty": 3,
  "source_file": "knowledge/01-architecture-design/index.md",
  "source_heading": "Q：你用 ReAct 还是 Plan-and-Execute？为什么？"
}
```

建议分块策略：

- 主问题为父文档。
- 专家回答、考察点和追问可作为子块。
- 每个子块都携带父问题 ID、完整问题、维度、公司和来源。
- Markdown 表格、代码块和完整案例不得从中间切断。
- 超长专家回答再按二级标题或语义段落递归切分。
- 不要只按固定字符数切割整个 Markdown 文件。

## 7. 推荐新增代码结构

```text
app/knowledge/
├── __init__.py
├── schema.py       # InterviewQuestion、KnowledgeChunk、SearchResult
├── parser.py       # Markdown → 结构化题目
├── repository.py   # SQLite 读写与筛选
├── indexer.py      # Embedding 与向量索引构建
├── retriever.py    # 关键词/向量混合检索
└── service.py      # 给 Agent 和 API 使用的统一入口

app/interview/
├── __init__.py
├── models.py       # 训练会话、评分、进度模型
├── prompts.py      # Interviewer、Coach、Evaluator 提示词
├── progress.py     # 掌握度与复习调度
└── workflow.py     # 面试训练状态机或 LangGraph 节点

scripts/
└── build_knowledge_index.py

tests/
├── test_knowledge_parser.py
├── test_knowledge_retrieval.py
└── test_interview_workflow.py
```

## 8. 检索方案

第一版建议采用可解释、可评测的混合检索：

```text
用户问题或训练目标
→ 元数据过滤（维度、公司、难度）
→ 关键词召回 + 向量召回
→ 去重/融合
→ Top-K 结果
→ 注入对应 Agent
```

注意事项：

- 当前 `all-MiniLM-L6-v2` 不应未经测试直接用于中文面试题库。
- 先建立约 20–30 条中文黄金查询及期望命中题目，再选择中文或多语言 Embedding 模型。
- Retriever 返回的每条结果必须包含题目 ID 和来源，方便回答引用与离线评估。
- 首版不必立即引入复杂 Reranker；先确保解析、过滤和基础召回正确。

建议最少评测：

- Hit@1、Hit@3、Hit@5。
- 不同维度和公司的过滤正确率。
- 同义表达的召回能力。
- 不相关问题的拒答或低置信度表现。

## 9. Agent 改造方案

现有角色可以复用并重新定义：

| 现有节点 | 新职责 |
|---|---|
| Analyzer | 识别学习、刷题、模拟面试、总结等模式 |
| Tutor | 基于知识库进行讲解和补弱 |
| Judge | 使用标准答案和 rubric 结构化评分 |
| Inquiry | 扮演面试官，生成一个针对性追问 |
| Plan | 根据目标岗位、公司、时间和薄弱项生成计划 |
| Aggregator | 整理单题反馈或整场面试报告 |

建议新增：

- `InterviewController`：显式管理出题、等待回答、追问、讲解和完成状态。
- `KnowledgeRetriever`：在 Tutor/Judge/Inquiry 前召回领域知识。
- `ProgressUpdater`：保存评分、薄弱点和下次复习时间。

建议流程：

```text
Analyzer
→ InterviewController
→ KnowledgeRetriever
→ Interviewer / Tutor / Judge
→ ProgressUpdater
→ Aggregator
```

不要让 Analyzer 每轮只靠语言模型猜测训练阶段。应在 `AgentState` 中显式增加：

```python
learning_mode
interview_phase
current_question_id
current_question
question_round
retrieved_knowledge
evaluation_result
```

可选的 `interview_phase`：

```text
idle
asking
awaiting_answer
evaluating
probing
reviewing
completed
```

## 10. 评分模型

Judge 必须改为结构化输出，避免只有一段不可追踪的点评。

推荐输出：

```json
{
  "overall_level": 3,
  "correctness": 4,
  "depth": 3,
  "tradeoff_reasoning": 2,
  "engineering_evidence": 2,
  "clarity": 4,
  "covered_points": [],
  "missing_points": [],
  "strengths": [],
  "improvement_advice": [],
  "next_followup": "...",
  "mastery_delta": 0.1
}
```

总体等级建议复用知识库方法论：

- L1：能复述定义。
- L2：能比较不同方案。
- L3：能给出选择标准和适用场景。
- L4：能说明工程实践、指标和踩坑。
- L5：能完成体系设计并预判风险。

### 防答案泄露

- 出题阶段只向 Interviewer 提供问题、难度和可用追问，不传专家答案。
- 用户提交答案后，才向 Judge 提供专家答案、考察点和 rubric。
- 模拟面试期间不调用 Tutor；结束后再统一讲解。

## 11. 学习进度模型

用户画像至少包含：

- 目标岗位。
- 目标公司。
- 当前水平。
- 面试日期。
- 每日可投入时间。
- 项目背景。
- 各维度掌握度。

每道题至少记录：

```json
{
  "user_id": "local_user",
  "question_id": "...",
  "attempts": 2,
  "best_level": 3,
  "last_scores": {},
  "missing_points": [],
  "last_reviewed_at": "...",
  "next_review_at": "...",
  "mastery": 0.6
}
```

首版复习调度可使用简单分箱或规则，不需要一开始实现复杂算法：

- L1–L2：次日复习。
- L3：3 天后复习。
- L4：7 天后复习。
- L5：14–30 天后复习。

## 12. 建议 API

MVP 可先提供：

```text
POST /api/v1/knowledge/rebuild
GET  /api/v1/knowledge/search
POST /api/v1/interview/start
POST /api/v1/interview/answer
GET  /api/v1/interview/progress
GET  /api/v1/interview/review-queue
```

`/interview/start` 建议参数：

```json
{
  "user_id": "local_user",
  "mode": "practice",
  "dimensions": ["rag", "architecture"],
  "companies": ["腾讯"],
  "difficulty": 3
}
```

## 13. 前端改造优先级

MVP 只需要新增或改造以下界面：

1. 训练目标设置：岗位、公司、难度、时间。
2. 今日训练：待练题目和待复习题目。
3. 单题训练页：问题、回答输入、追问、评分反馈。
4. 进度页：各维度掌握度和薄弱知识点。

现有 `NewTaskPage.tsx` 可改造成目标设置入口；现有 `TutorSession.tsx` 可承载单题训练对话。第一阶段不要先投入大量时间重做 UI。

## 14. 推荐实施顺序

### Phase 1：知识底座

1. 定义 `InterviewQuestion` 数据模型。
2. 编写 Markdown 解析器。
3. 为解析器补单元测试，确认约 486 道题不会被静默丢失。
4. 将结构化数据写入 SQLite/JSON。
5. 建立独立检索索引。
6. 准备黄金查询并做检索评测。

### Phase 2：单题训练闭环

1. 从知识库选择一道题。
2. 返回题目并进入 `awaiting_answer`。
3. 接收用户回答。
4. 根据标准答案和 rubric 评分。
5. 生成一道缺失点追问。
6. 更新学习记录。
7. 返回结构化反馈。

### Phase 3：产品化

- 公司与方向定向训练。
- 今日任务和间隔复习。
- 错题本。
- 完整模拟面试。
- 面试报告与能力雷达。

### Phase 4：扩展能力

- 项目经历深挖。
- 简历内容与题库联动。
- 行为面训练。
- 更新知识源和增量索引。
- 基于真实人工评分校准 Judge。

## 15. MVP 验收标准

知识底座完成标准：

- 能稳定解析所有问题段落，解析失败有明确日志。
- 每道题具有稳定 ID、维度、问题文本和来源。
- 典型中文查询能在 Top-3 命中预期问题。
- 可按维度和公司过滤。
- 知识索引与用户对话索引物理隔离。

训练闭环完成标准：

- 系统出题时不泄露标准答案。
- 用户回答后返回结构化 L1–L5 评分。
- 反馈明确列出已覆盖点和缺失点。
- 追问与缺失点相关，而不是泛泛提问。
- 同一道题的多次作答可以累积学习记录。
- 结束训练后可以看到本次结果和下一次建议复习时间。

## 16. 暂不建议做的事情

- 不要把整个 `knowledge/` 目录直接塞进现有对话向量库。
- 不要只修改 Prompt 就宣称完成领域化。
- 不要在建立检索评测前反复更换 Embedding 模型。
- 不要一开始加入过多 Agent 角色；当前角色数量已足够。
- 不要先重做完整 Dashboard，再补后端训练状态。
- 不要让 LLM 自由生成题目 ID、学习进度或状态迁移。

## 17. 下一位开发者的第一项任务

建议从“只读、可测试”的知识解析器开始，不要先修改主 Agent：

1. 新建 `app/knowledge/schema.py`。
2. 新建 `app/knowledge/parser.py`。
3. 正确解析两类文件：单题文件和包含多题的 `index.md`。
4. 输出规范化 JSON 到临时或 `data/` 目录。
5. 添加测试，校验题目总数、关键字段和稳定 ID。
6. 解析完成并人工抽查后，再实现索引与 Agent 接入。

第一项任务的建议完成定义：

```text
python scripts/build_knowledge_index.py --parse-only
```

能够输出题目总数、按维度统计、解析警告，并生成可人工检查的结构化 JSON。此阶段不调用模型、不下载 Embedding、不修改现有聊天行为。

## 18. 关键文件索引

- `README.md`：当前产品与架构说明。
- `knowledge/README.md`：知识库来源和声明格式，但与实际文件结构不完全一致。
- `app/core/agent_builder.py`：主 LangGraph 和各 Worker。
- `app/core/models.py`：AgentState 和结构化输出模型。
- `app/core/prompts.py`：Analyzer、Tutor、Judge、Inquiry、Aggregator 提示词。
- `app/core/context_rag.py`：历史对话召回与上下文拼装。
- `app/core/vector_store.py`：现有对话 FAISS。
- `app/core/memory.py`：会话持久化与 RAG 索引触发。
- `app/core/task_plan/`：学习计划逻辑。
- `app/api/chat.py`：聊天 API 和流式执行入口。
- `app/api/task_plan.py`：学习计划 API。
- `web/src/app/components/NewTaskPage.tsx`：任务创建入口。
- `web/src/app/components/TutorSession.tsx`：主要学习对话界面。

## 19. 当前改动状态

- 尚未实现知识库解析、索引或训练状态机。
- 本次只完成项目检查、方向设计与本 Handoff 文档。
- 当前目录未检测到可用的 Git 仓库元数据，因此无法提供 commit 或 diff 基线；后续修改前应先确认版本管理方式。

---

## 20. 已实现进度（2026-08-19 更新）

### Phase 1：知识底座 ✅ 已完成

- `app/knowledge/schema.py`：`InterviewQuestion`、`KnowledgeChunk`、`SearchResult`、`ParseWarning` 数据模型。
- `app/knowledge/parser.py`：`KnowledgeParser`，解析单题文件与多题 `index.md`，支持 `## Q` / `### Q`、`**差距在哪**`、内嵌 `**追问：xxx**`、独立 `## 考察点`/`## 追问` 段落。
- `app/knowledge/repository.py`：`KnowledgeRepository`，SQLite 存储 + FTS5 索引（含触发器同步），与对话记忆向量库物理隔离。
- `app/knowledge/indexer.py`：`EmbeddingClient` + `KnowledgeIndexer`，调用本地 Qwen3-Embedding（OpenAI 兼容接口，用 requests 而非 openai SDK 以规避 omlx 服务对 httpx 的 502 兼容问题）。
- `app/knowledge/retriever.py`：`KnowledgeRetriever`，双通道混合检索（embedding 语义主通道 + 关键词 LIKE 子串兜底，中文关键词用 jieba 分词）。
- `app/knowledge/service.py`：`build_index` / `search` / `get_question` 统一入口。
- `scripts/build_knowledge_index.py`：支持 `--parse-only`、`--no-embedding`、`--db`。
- 测试：`tests/test_knowledge_parser.py`（14 用例）、`tests/test_knowledge_retrieval.py`（8 用例）。

**解析结果**：485 道题、17 个维度、0 警告；gap_analysis 覆盖 475、source 覆盖 485。

**检索评测**（可复现，2026-08-20）：

- 黄金查询集：`data/golden_queries.json`（50 条，覆盖 11 个维度，含原题复述/同义改写/口语化/负样本 4 类）。
- 评测脚本：`python scripts/eval_retrieval.py`（默认 threshold=0.5）。
- 指标：Hit@1 95.3%、Hit@3 97.7%、Hit@5 100%、MRR 0.967、Recall@5 98.8%，负样本拦截率 100%（7/7）。
- 检索实现要点：中文关键词用 jieba 分词（替代旧版 2-gram 滑窗，消除跨词边界噪声）；合并结果统一按 threshold 过滤；学习模式 `_SIMILARITY_THRESHOLD=0.5`（依据正样本最低分 0.65、负样本最高分 0.44 的分界）。

### Phase 2：单题训练闭环 ✅ 已完成

- `app/interview/models.py`：`InterviewSession`、`EvaluationResult`、`QuestionProgress`、请求体。
- `app/interview/prompts.py`：Interviewer / Evaluator / Coach 三角色提示词（防答案泄露）。
- `app/interview/progress.py`：`ProgressStore`，掌握度 + 简单分箱复习调度（L1-L2 次日、L3 三天、L4 七天、L5 十四天）。
- `app/interview/workflow.py`：显式状态机 `start → asking → awaiting_answer → evaluating → reviewing → completed`，选题、结构化评分、追问、复盘。
- `app/api/interview.py`：`/interview/start`、`/interview/answer`、`/interview/review`、`/interview/progress` 路由。
- 测试：`tests/test_interview_workflow.py`（6 用例）。

**关键实现约束**：出题阶段不向 Interviewer 注入专家答案；用户提交作答后才向 Evaluator 提供标准答案。会话状态用内存字典（MVP），可后续替换为持久化存储。

### 待办（Phase 3+）

- 公司与方向定向训练、今日任务与间隔复习队列的产品化接入。
- 错题本、完整模拟面试、面试报告与能力雷达。
- 会话状态持久化（替换内存 `_sessions` 字典）。
- 前端改造（目标设置、单题训练页、进度页）。
- 基于真实人工评分校准 Judge。

---

## 21. 已实现进度（2026-08-19 第二批更新）

### Phase 3：会话持久化 + 公司定向 + 复习模式 ✅ 已完成

- `app/interview/session_store.py`：会话 JSON 持久化（`memory/interview_sessions/`），替换原内存 `_sessions` 字典，后端重启不丢会话。
- `app/interview/workflow.py`：
  - `start_session` 支持三种模式：`practice`（随机新题，排除已答题）、`review`（从复习队列选题，按掌握度升序）、`mock`。
  - `_pick_question` 增强：支持 `exclude_ids`（排除已做过的题）、公司优先匹配。
  - `_pick_review_question`：复习模式选题（到期待复习 + 掌握度低优先）。
- `app/interview/models.py`：`InterviewMode` 新增 `review`。
- 前端 `InterviewPage.tsx`：新增「刷新题 / 复习」模式切换、16 家公司定向选择器。
- 测试：`tests/test_interview_workflow.py` 新增会话持久化、公司优先、排除已答题 3 个用例（共 9 用例）。

**验证**：29 个测试全部通过；公司定向（字节）成功出题；复习模式正确返回「暂无待复习题目」；会话文件正确落盘。

### 仍待办（Phase 3+）

- 错题本、完整模拟面试、面试报告与能力雷达。
- 今日任务（每日推荐）产品化。
- 基于真实人工评分校准 Judge。
- 前端 chunk 过大，可考虑路由级 code-split。

---

## 22. 已实现进度（2026-08-19 第三批更新）

### Phase 4：学习模式（真正的 RAG 问答）✅ 已完成

- `app/interview/learn.py`：`ask()` 学习模式问答。数据流：用户自由提问 → `KnowledgeRetriever` 双通道召回 Top-4 → 拼接「题目+专家答案+差距分析」为上下文 → Tutor 基于上下文生成**带 [n] 引用**的讲解。
- `app/api/interview.py`：新增 `POST /interview/ask` 路由。
- 前端 `LearnPage.tsx`：学习模式页（自由提问 + 预置示例问题 + 带引用来源展示），路由 `/interview/learn`。
- `InterviewPage.tsx`：顶部新增「学习模式」入口。
- 测试：`tests/test_interview_learn.py`（3 用例：上下文拼接、无结果回退、端到端检索）。

**验证**：32 个测试全部通过；真实问答「什么是 GraphRAG」返回高质量带引用回答（4 条 citation，相关度 0.80），引用正确标注 [1] 并命中 GraphRAG 原题。

### 三种模式现已齐备

| 模式 | 路由 | 数据流 | 是否 RAG |
|---|---|---|---|
| 刷题模式 | `/interview` | SQL 抽题 → 评分 → 复盘 | 否 |
| 复习模式 | `/interview`（mode=review） | 复习队列选题 → 评分 | 否 |
| 学习模式 | `/interview/learn` | 检索召回 → 带引用讲解 | 是 |

---

## 23. 已实现进度（2026-08-19 第四批更新）

### Phase 5：错题本 + 数据安全加固 ✅ 已完成

- `app/interview/workflow.py`：
  - `_aggregate_wrong_questions()`：聚合错题本（best_level <= 2 的题，按掌握度升序），含题目、维度、缺失点。
  - `_aggregate_weak_dimensions()`：筛出薄弱维度（平均掌握度 < 0.6）。
  - `get_progress` 返回新增 `wrong_questions`、`weak_dimensions` 字段。
- 前端 `ProgressPage.tsx`：新增「薄弱维度」（可点击跳转刷题并预选维度）与「错题本」（L1-L2 题 + 缺失点展示）模块。
- `InterviewPage.tsx`：支持从路由 state 预选维度（从薄弱维度跳转时自动选中）。
- `app/utils/file_io.py`：`save_json` 改为**原子写**（临时文件 + `os.fsync` + `os.replace`），避免写入中断损坏数据。
- `app/core/memory.py`：`_save_task_index` 写入前自动备份当前非空 tasks.json（保留最近 10 份，带时间戳）。

**验证**：35 个测试全部通过；progress 接口正确返回 3 道错题 + 3 个薄弱维度；tasks.json 自动备份生效。

**修复记录**：此前 tasks.json 被清空（`[]`），已从会话文件 + 任务计划文件恢复 7 个任务；本次加固为防止再次发生。

### 仍待办（Phase 3+）

- 完整模拟面试、面试报告与能力雷达。
- 今日任务（每日推荐）产品化。
- 基于真实人工评分校准 Judge。
- 前端 chunk 过大，可考虑路由级 code-split。
