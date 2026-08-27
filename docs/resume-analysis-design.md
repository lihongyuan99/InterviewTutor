# 简历分析场景详细设计

> 版本：v1.0（设计稿）
> 更新时间：2026-08-26
> 状态：待评审，未实现

## 0. 文档目的

本文档给出「对话内上传简历 → 结构化解析 → 简历-题库联动 → 定向追问/匹配分析」这一场景的完整设计，
包括产品定位、数据结构、模块划分、API 契约、Agent 编排、前端交互与实施顺序。

本文档**只做设计**，不改动现有代码。落地时优先遵循「只读可测试」原则，从解析器开始，不碰主 Agent。

## 1. 背景与目标

### 1.1 现状

| 能力 | 现状 | 缺口 |
|------|------|------|
| 对话接口 | `POST /api/v1/chat` + `/chat/stream`，仅接收 `message: str` | 无文件上传 |
| 文档解析 | `app/knowledge/parser.py` 只解析固定格式 Markdown 题库（`## Q`/`### Q`） | 无 PDF/Word/通用简历解析 |
| 文件存储 | 无上传目录、无 `UploadFile` 处理 | 依赖缺失 `python-multipart`、PDF/Word 解析库 |
| 向量检索 | 题库 RAG（`app/knowledge/`）+ 对话记忆 RAG（`app/core/vector_store.py`） | 可复用，但需第三套"简历"索引，物理隔离 |

### 1.2 产品定位

产品既定路线（`HANDOFF.md` Phase 4）已包含「简历内容与题库联动」。本场景是该项的落地形态：

> 用户上传简历 → 系统解析为结构化 `Resume` → 结合题库 `project-deep-dive`（简历项目深挖）与
> `company-preferences`（公司偏好）两个维度 → 生成"面试官会怎么问你的简历"的定向问题集，
> 并给出简历-岗位匹配度与优化建议。

### 1.3 目标用户与价值

- **目标用户**：正在准备 AI Agent / LLM 应用工程岗位面试的求职者。
- **核心价值**：
  1. 把简历从"静态文本"变成"可被拷问的对象"，提前暴露简历里的深挖雷区。
  2. 与题库 592 道题联动，让简历项目自动关联到真实面试题。
  3. 复用公司偏好数据，做"简历 vs 目标公司"的差距分析。

### 1.4 非目标（第一版不做）

- 不生成/美化简历（不做简历排版、写作服务）。
- 不做行为面（BQ）训练（产品路线明确排除，后续单独规划）。
- 不做多候选人横向比较、不做 HR 视角的筛选打分。
- 不做录音/视频转写（ASR）。

## 2. 场景拆解

### 2.1 核心场景

1. **简历上传与解析**：用户上传 PDF/Word/Markdown 简历，系统解析为结构化对象并回显预览。
2. **简历项目深挖**：针对简历中每个项目/经历，召回 `project-deep-dive` 维度题目并生成定制追问。
3. **匹配度分析**：结合 `company-preferences`，输出"简历 vs 目标公司/岗位"的匹配度与差距。
4. **简历优化建议**：给出 STAR 完整性、量化成果缺失、技术栈表述等改进点。
5. **简历问答（RAG）**：在对话中针对简历内容自由提问，回答带引用（复用学习模式范式）。

### 2.2 场景优先级

| 优先级 | 场景 | 理由 |
|--------|------|------|
| P0 | 上传 + 解析 + 结构化预览 | 一切能力的入口，必须最先打通 |
| P0 | 简历项目深挖（联动 project-deep-dive） | 核心差异化价值 |
| P1 | 匹配度分析（联动 company-preferences） | 复用现有数据，价值高 |
| P1 | 简历优化建议 | 解析结果的直接延伸，成本低 |
| P2 | 简历问答（RAG） | 需要独立向量索引，工作量略大 |

## 3. 数据模型设计

新增模块 `app/resume/`，与现有 `app/knowledge/`、`app/interview/` 平级，物理隔离。

### 3.1 `Resume` 顶层结构

```python
# app/resume/models.py
from pydantic import BaseModel, Field
from typing import List, Optional

class ResumeEducation(BaseModel):
    school: str = ""
    degree: str = ""          # 本科/硕士/博士
    major: str = ""
    start: str = ""
    end: str = ""
    highlights: List[str] = Field(default_factory=list)

class ResumeWork(BaseModel):
    company: str = ""
    role: str = ""
    start: str = ""
    end: str = ""
    description: str = ""
    highlights: List[str] = Field(default_factory=list)

class ResumeProject(BaseModel):
    name: str = ""
    role: str = ""
    period: str = ""
    description: str = ""
    # 关键技术栈（用于题库维度映射）
    tech_stack: List[str] = Field(default_factory=list)
    # 量化成果（STAR 的 R，缺失则提示）
    metrics: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)

class ResumeSkill(BaseModel):
    name: str = ""
    level: str = ""           # 熟悉/掌握/精通
    category: str = ""        # 编程语言/框架/ML/AI/工程/其他

class Resume(BaseModel):
    resume_id: str
    user_id: str = "local_user"
    source_file: str = ""               # 原始文件相对路径
    source_type: str = ""               # pdf/docx/md
    raw_text: str = ""                  # 解析出的纯文本（保留备查）
    name: str = ""
    contact: str = ""                   # 脱敏：默认不存手机/邮箱原文
    target_role: str = ""               # 目标岗位
    target_companies: List[str] = Field(default_factory=list)
    summary: str = ""                   # 个人简介/自我评价
    educations: List[ResumeEducation] = Field(default_factory=list)
    works: List[ResumeWork] = Field(default_factory=list)
    projects: List[ResumeProject] = Field(default_factory=list)
    skills: List[ResumeSkill] = Field(default_factory=list)
    honors: List[str] = Field(default_factory=list)
    # 维度映射结果（解析时由模型输出，或后续单独计算）
    mapped_dimensions: List[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
```

### 3.2 简历-题库关联结构

```python
class ProjectQuestionLink(BaseModel):
    """简历项目与面试题的一条关联。"""
    project_name: str
    question_id: str          # InterviewQuestion.id
    dimension: str
    question: str
    score: float              # 关联相关度
    reason: str = ""          # 为什么这道题会问到该项目

class ResumeAnalysis(BaseModel):
    """一次简历分析的完整输出。"""
    analysis_id: str
    resume_id: str
    # 深挖问题集
    project_questions: List[ProjectQuestionLink] = Field(default_factory=list)
    # 匹配度
    match: Optional[ResumeMatch] = None
    # 优化建议
    suggestions: List[ResumeSuggestion] = Field(default_factory=list)
    created_at: str = ""

class ResumeMatch(BaseModel):
    """简历 vs 目标公司/岗位的匹配度。"""
    target_role: str = ""
    target_company: str = ""
    overall_score: float = 0.0          # 0-1
    dimension_scores: dict = Field(default_factory=dict)  # dimension -> score
    matched_points: List[str] = Field(default_factory=list)
    gap_points: List[str] = Field(default_factory=list)
    company_focus: List[str] = Field(default_factory=list)  # 该公司高频维度

class ResumeSuggestion(BaseModel):
    category: str = ""        # star / metrics / tech_stack / wording / missing
    severity: str = ""        # high / medium / low
    target: str = ""          # 指向的项目/技能/字段
    advice: str = ""
```

### 3.3 存储边界（遵循 HANDOFF §5「三类数据拆分」）

```
memory/
├── uploads/          # 原始上传文件（新增，Git 忽略）
├── resumes/          # 结构化简历 JSON（新增，resume_id.json）
├── resume_analysis/  # 分析结果 JSON（新增）
├── resume_index/     # 简历分块向量索引（新增，与题库/对话索引物理隔离）
├── sessions/         # 保留：对话会话
└── ...
```

**关键约束**：简历向量索引不得复用 `memory/vector_store/<task_id>`（对话记忆）或
`data/knowledge.db`（题库）。三者物理隔离。

## 4. 模块设计

### 4.1 目录结构

```
app/resume/
├── __init__.py
├── models.py          # 上述数据模型
├── extract.py         # 文本抽取（PDF/Word/MD -> 纯文本）
├── parser.py          # 纯文本 -> Resume（LLM 结构化输出）
├── store.py           # 简历 JSON 持久化 + 上传文件管理
├── indexer.py         # 简历分块向量化（复用 Qwen3EmbeddingClient）
├── retriever.py       # 简历片段检索
├── linker.py          # 简历项目 <-> 题库题目关联（联动 project-deep-dive）
├── matcher.py         # 简历 vs 公司偏好匹配度（联动 company-preferences）
├── analyzer.py        # 编排入口：解析 -> 深挖 -> 匹配 -> 建议
└── prompts.py         # 简历解析/深挖/匹配/建议的提示词

app/api/resume.py      # 路由层（上传/解析/分析/问答）

tests/
├── test_resume_extract.py
├── test_resume_parser.py
├── test_resume_linker.py
└── test_resume_matcher.py
```

### 4.2 各模块职责

| 模块 | 职责 | 复用现有能力 |
|------|------|--------------|
| `extract.py` | 按文件类型抽取纯文本：PDF 用 `pypdf`/`pdfplumber`，Word 用 `python-docx`，MD 直接读 | 无 |
| `parser.py` | 纯文本 → `Resume`，用 LLM 结构化输出（`with_structured_output` 或 JSON 模式） | `app/core/llm_factory.create_chat_model` |
| `store.py` | 保存原始文件 + 简历 JSON，原子写 | `app/utils/file_io` |
| `indexer.py` | 简历分块（按项目/工作/技能段落）向量化 | `app/core/embedding_client.Qwen3EmbeddingClient` |
| `retriever.py` | 简历片段语义检索 | 同上 + FAISS |
| `linker.py` | 项目关键词/向量 → 召回 `project-deep-dive` 题目 | `app/knowledge.service.search(dimension="project-deep-dive")` |
| `matcher.py` | 简历技能 → 公司偏好维度匹配 | `app/knowledge.service.search` + `company-preferences` 数据 |
| `analyzer.py` | 编排上述能力，输出 `ResumeAnalysis` | 全部 |

## 5. API 契约

### 5.1 上传并解析

```http
POST /api/v1/resume/upload
Content-Type: multipart/form-data

file: <binary>
target_role: "AI Agent 工程师"        # 可选
target_companies: "腾讯,字节"          # 可选（逗号分隔）
```

响应（202 或 200，视解析方式）：

```json
{
  "resume_id": "resume_20260826_120000",
  "source_type": "pdf",
  "resume": { "...": "Resume 结构化对象" },
  "warnings": ["未识别到量化成果，共 3 个项目"]
}
```

### 5.2 简历项目深挖

```http
POST /api/v1/resume/deep-dive
{ "resume_id": "...", "project_names": ["项目A", "项目B"], "limit": 5 }
```

响应：

```json
{
  "analysis_id": "...",
  "project_questions": [
    {
      "project_name": "项目A",
      "question_id": "project-deep-dive-...",
      "dimension": "project-deep-dive",
      "question": "你的 Agent 项目用了什么框架？为什么选它？",
      "score": 0.87,
      "reason": "简历项目提到 LangGraph 框架选型，命中该题考察点"
    }
  ]
}
```

### 5.3 匹配度分析

```http
POST /api/v1/resume/match
{ "resume_id": "...", "target_role": "...", "target_company": "腾讯" }
```

响应：`ResumeMatch`（含 overall_score、dimension_scores、gap_points、company_focus）。

### 5.4 优化建议

```http
POST /api/v1/resume/suggest
{ "resume_id": "..." }
```

响应：`ResumeSuggestion[]`（按 severity 排序）。

### 5.5 简历问答（RAG，P2）

```http
POST /api/v1/resume/ask
{ "resume_id": "...", "question": "我这个 RAG 项目还有哪些没讲清楚的？" }
```

响应复用学习模式 `learn.ask` 的 `{answer, citations, ...}` 范式，citations 指向简历片段。

### 5.6 查询与删除

```http
GET    /api/v1/resume/{resume_id}      # 读取结构化简历
GET    /api/v1/resume/list             # 列表（按 user_id）
DELETE /api/v1/resume/{resume_id}      # 删除简历 + 文件 + 索引 + 分析
```

## 6. Agent 编排设计

简历分析**不进主对话 Agent 的多智能体图**（避免侵入现有 `agent_builder.py`），而是作为独立的
`analyzer.py` 编排流程。原因：

- 简历分析是**一次性、长耗时**的批量任务（解析 + 深挖 + 匹配），不适合塞进每轮对话的意图路由。
- 遵循 HANDOFF「不要让 LLM 每轮猜测训练阶段」的原则，用显式流程而非隐式路由。

### 6.1 编排流程

```
上传文件
  → extract（纯文本）
  → parser（LLM 结构化 -> Resume）
  → store（持久化）
  → [可选] indexer（向量化，供 RAG 问答）
  → linker（项目 -> project-deep-dive 题目）
  → matcher（技能 -> company-preferences 匹配）
  → suggester（优化建议）
  → 返回 ResumeAnalysis
```

### 6.2 与主对话的关系

- 简历分析结果**不写入主对话历史**，而是作为独立资源（`resume_id`）存在。
- 若用户后续在对话中问"我的简历有什么问题"，主 Agent 通过 `resume_id` 关联上下文，
  可选地注入简历摘要（类似 `_inject_profile` 注入画像摘要的既有模式）。
- 深挖出的题目可直接作为刷题模式的 `question_ids` 传入 `POST /interview/start`，复用现有评分闭环。

### 6.3 关键提示词要点（`prompts.py`）

- **解析提示词**：要求输出 JSON，字段与 `Resume` 对齐；对缺失字段置空而非编造；联系方式脱敏。
- **深挖提示词**：基于项目 `tech_stack` + 描述，从召回题目中挑选最可能被追问的，并解释关联原因。
- **匹配提示词**：结合公司偏好（腾讯重 RAG 系统设计、字节重记忆上下文等）与简历技能做差距判断。
- **建议提示词**：按 STAR 完整性、量化成果、技术栈表述、关键词命中四类给建议。

## 7. 前端设计

### 7.1 入口

- `TutorSession.tsx`（主对话界面）输入框旁新增「上传简历」按钮（纸夹图标）。
- 或在「目标设置」页（现有 `GoalTrainingPage.tsx`）新增简历上传卡片。
- 支持拖拽上传，接受 `.pdf / .docx / .md`，单文件 ≤ 10MB。

### 7.2 交互流

```
点击上传 → 选择文件 → 进度条（解析中）→ 结构化预览（可编辑修正）
        → 触发「深挖分析」→ 展示问题集卡片（可点击进入刷题）
        → 触发「匹配度」→ 展示雷达/差距列表
```

### 7.3 新增组件

| 组件 | 职责 |
|------|------|
| `ResumeUploader.tsx` | 拖拽/选择上传，类型与大小校验，进度展示 |
| `ResumePreview.tsx` | 结构化简历回显（分区块展示，支持手改后重新解析） |
| `ResumeDeepDive.tsx` | 项目深挖问题集，点击问题 → 跳转刷题模式 |
| `ResumeMatch.tsx` | 匹配度雷达图（复用 Recharts/Plotly）+ 差距列表 |
| `ResumeSuggestions.tsx` | 优化建议列表（按 severity 分组） |

### 7.4 前端 API 层

在 `web/src/lib/api.ts` 新增 `uploadResume` / `analyzeResume` / `matchResume` / `askResume` 等封装。

## 8. 复用与新增清单

### 8.1 复用现有

| 现有能力 | 用途 |
|----------|------|
| `app/core/embedding_client.Qwen3EmbeddingClient` | 简历向量化（统一 Embedding） |
| `app/knowledge.service.search/get_question` | 联动 `project-deep-dive` / `company-preferences` |
| `app/core/llm_factory.create_chat_model` | 解析/深挖/匹配/建议的模型调用 |
| `app/utils/file_io` | 原子写简历 JSON |
| `app/interview` 评分闭环 | 深挖题直接进刷题模式 |
| 前端 `learn` 的 citation 展示范式 | 简历问答引用展示 |

### 8.2 新增依赖（`requirements.txt`）

```
python-multipart   # FastAPI 文件上传必需
pypdf              # PDF 文本抽取（或 pdfplumber）
python-docx        # Word 解析
```

（注：`faiss-cpu`、`sentence-transformers`、`jieba` 已存在，无需新增。）

## 9. 数据安全与隐私

- **脱敏**：解析时对手机号、邮箱做脱敏处理，`Resume.contact` 默认不存原文。
- **本地优先**：文件与解析结果默认只存本地 `memory/`，不上传第三方。
- **删除即清理**：`DELETE /resume/{id}` 同时删除原始文件、JSON、向量索引与分析结果。
- **上传校验**：限制文件类型白名单（pdf/docx/md）、大小上限、文件头魔数校验（防伪造扩展名）。

## 10. 实施顺序

### Phase R1：解析底座（只读可测试，不碰主 Agent）

1. `app/resume/models.py` + `app/resume/extract.py`。
2. `app/resume/parser.py`（LLM 结构化输出）。
3. `tests/test_resume_extract.py` / `test_resume_parser.py`。
4. 验收：`PDF/MD → Resume` 稳定，字段完整，缺失字段不编造。

### Phase R2：上传 API + 持久化

1. `app/resume/store.py` + `app/api/resume.py` 的 `/upload` / `GET` / `DELETE`。
2. 新增依赖 `python-multipart` / `pypdf` / `python-docx`。
3. 前端 `ResumeUploader.tsx` + `ResumePreview.tsx`。
4. 验收：上传 → 预览 → 修正 → 重新解析 闭环可用。

### Phase R3：深挖 + 匹配（核心价值）

1. `app/resume/linker.py` + `matcher.py` + `prompts.py`。
2. `/deep-dive`、`/match`、`/suggest` API。
3. 前端 `ResumeDeepDive.tsx` + `ResumeMatch.tsx` + `ResumeSuggestions.tsx`。
4. 验收：深挖题能命中 `project-deep-dive` 真实题目并进入刷题；匹配度贴合公司偏好。

### Phase R4：简历问答 RAG（可选，P2）

1. `app/resume/indexer.py` + `retriever.py`。
2. `/ask` API + 前端问答。
3. 验收：简历相关问题带引用回答。

## 11. 验收标准（MVP = Phase R1 + R2 + R3）

- 上传 PDF/Word/MD 简历均能解析出结构化 `Resume`，失败有明确警告。
- 简历每个项目能召回 ≥3 条相关 `project-deep-dive` 题目，且题目可一键进入刷题评分。
- 匹配度分析能体现目标公司的高频维度（如腾讯 RAG、字节记忆）与简历技能的差距。
- 优化建议至少覆盖 STAR 完整性、量化成果、技术栈表述三类。
- 简历数据与题库、对话记忆三者物理隔离，删除即彻底清理。

## 12. 暂不做（防范围蔓延）

- 简历自动写作/美化、排版导出。
- 行为面（BQ）训练。
- 多候选人比较、HR 筛选打分。
- 录音/视频转写（ASR）。
- 把简历分析塞进主对话 Agent 的意图路由。
