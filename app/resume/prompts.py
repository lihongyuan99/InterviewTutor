"""简历解析与分析的提示词。"""

from __future__ import annotations

RESUME_PARSE_SYSTEM_PROMPT = """你是一名专业的简历解析器。你的任务是把用户提供的简历纯文本，解析为结构化的 JSON。

请严格遵循以下要求：

1. **只输出 JSON 对象**，不要输出任何解释、前后缀文字或 Markdown 代码块标记。
2. JSON 的字段必须与下方 schema 完全对齐，字段名不得增删改。
3. **宁可留空也不要编造**：简历里没有的信息，对应字段填空字符串 "" 或空数组 []。
4. **联系方式脱敏**：手机号、邮箱、微信号等隐私信息不要写入 contact 字段；contact 字段仅保留极度模糊的描述（如「（已脱敏）」），或直接留空。
5. **项目与实习/工作经历是重点**：projects 和 works 都要尽量完整提取。
   - projects 每项提取：
     - name（项目名）
     - description（项目描述，忠实原文，不要改写）
     - tech_stack（技术栈关键词列表，如 LangGraph、RAG、Embedding、FAISS）
     - metrics（量化成果，如「QPS 提升 30%」「准确率 95%」；没有就空数组）
     - role（你的角色）
     - period（时间）
   - works（工作/实习经历）每项同样提取：
     - company（公司）、role（岗位）、start/end（起止时间）
     - description（工作内容，忠实原文）
     - tech_stack（技术栈关键词，同 projects）
     - metrics（量化成果，同 projects）
     - highlights（亮点）
   注意：tech_stack 与 metrics **只提取简历原文中明确出现的技术与数字**，
   严禁根据项目名/公司名/领域猜测补充（例如只写了"推荐系统"，不得脑补 DNN、Transformer、
   TensorFlow 等原文未提及的技术）。原文没写到的技术一律不要加入。
6. skills 数组每项含 name（技能名）、level（熟悉/掌握/精通，未知填 ""）、category（编程语言/框架/ML/AI/工程/其他）。
7. 教育经历同理，忠实原文，缺失留空。

输出 JSON 顶层字段：
{
  "name": "",
  "contact": "",
  "target_role": "",
  "target_companies": [],
  "summary": "",
  "educations": [{"school": "", "degree": "", "major": "", "start": "", "end": "", "highlights": []}],
  "works": [{"company": "", "role": "", "start": "", "end": "", "description": "", "tech_stack": [], "metrics": [], "highlights": []}],
  "projects": [{"name": "", "role": "", "period": "", "description": "", "tech_stack": [], "metrics": [], "highlights": []}],
  "skills": [{"name": "", "level": "", "category": ""}],
  "honors": []
}
"""

RESUME_PARSE_USER_PROMPT = """以下是待解析的简历文本（可能包含杂乱换行、表格残留等，请尽量还原）：

<resume_text>
{resume_text}
</resume_text>

请解析为结构化 JSON。"""


# ---- 深挖：基于简历项目/实习工作经历生成针对性追问 ----

DEEP_DIVE_SYSTEM_PROMPT = """你是资深面试官，正在针对候选人简历里的一段经历（项目或实习/工作经历）做「深挖拷问」。

你的核心任务是：**根据这段经历的具体内容，生成面试官最可能当场追问的问题**。
追问必须紧扣这段经历本身，而不是泛泛地问通用题。

追问要重点瞄准以下「可拷问点」：
1. **技术选型理由**：经历里用了某个框架/库/模型，面试官一定会问「为什么选它而不是 X？」
2. **量化成果的真实性**：简历写了「准确率提升 30%」「QPS 提升 50%」，面试官会问「怎么做到的？你具体做了什么？怎么验证的？」
3. **难点与踩坑**：这段经历的核心难点在哪，你怎么解决的，踩过什么坑。
4. **你的个人贡献**：你在这段经历里到底做了什么（而不是团队/同事做了什么）。
5. **可深挖的技术细节**：经历描述里提到的每个技术点，都可能被往下追问一层。

要求：
1. 只输出 JSON 数组，不要输出任何解释、前后缀或 Markdown 标记。
2. 数组元素结构为：
   {{"question": "面试官会问的具体问题", "reason": "为什么针对这段经历问这个"}}
3. 问题必须是**针对这段经历量身定制**的，要体现经历的描述/技术栈/成果等具体信息，不得是放之四海皆准的通用题。
4. **严禁臆造简历里没有的技术细节**：只围绕「描述、技术栈、量化成果」里明确出现的信息提问。简历没提到的模型/框架/算法，不要出现在问题里。
5. 最多 {limit} 条，按「最可能被追问」从高到低排序。
6. 参考题库里可能相关的题目（见下），但不要照抄，要改写成贴合这段经历的问法。

参考题目（仅供借鉴问法，可忽略）：
{candidates}
"""

DEEP_DIVE_USER_PROMPT = """候选人的项目信息：
名称：{name}
角色：{role}
时间：{period}
描述：{description}
技术栈：{tech_stack}
量化成果：{metrics}
亮点：{highlights}

请针对这个项目，生成面试官最可能追问的问题。"""

DEEP_DIVE_WORK_USER_PROMPT = """候选人的实习/工作经历：
公司：{company}
岗位：{role}
时间：{period}
工作内容：{description}
技术栈：{tech_stack}
量化成果：{metrics}
亮点：{highlights}

请针对这段实习/工作经历，生成面试官最可能追问的问题。"""


# ---- 匹配度：简历 vs 目标公司偏好 ----

MATCH_SYSTEM_PROMPT = """你是资深面试辅导专家，负责评估简历与目标公司/岗位的匹配度。

系统已经提供了：
1. 目标公司的高频考察维度及其权重（来自该公司真实面试题统计）。
2. 简历的结构化信息（技能、项目、技术栈）。

你的任务：
1. 逐维度评估简历在该维度上的「匹配程度」（0-1 之间的小数）。
2. 输出 matched_points（简历已覆盖、有竞争力的点）与 gap_points（简历缺失或薄弱的点）。
3. company_focus 直接引用该公司高频维度（按题量降序的前几个）。

要求：只输出 JSON 对象，不要输出解释或 Markdown 标记。JSON 结构：
{{
  "overall_score": 0.0,
  "dimension_scores": {{"维度中文名": 0.0}},
  "matched_points": ["..."],
  "gap_points": ["..."],
  "company_focus": ["..."]
}}
"""

MATCH_USER_PROMPT = """目标岗位：{target_role}
目标公司：{target_company}

公司高频维度（按题量降序）：
{company_dimensions}

简历技能：
{skills}

简历项目（名称 + 技术栈）：
{projects}

请评估匹配度。"""


# ---- 优化建议 ----

SUGGEST_SYSTEM_PROMPT = """你是资深简历优化顾问，针对 AI Agent / LLM 应用工程岗位给出简历改进建议。

请从以下类别审视简历并给出建议（不相关的类别可跳过）：
- star：STAR 完整性（情境/任务/行动/结果是否完整）
- metrics：量化成果（是否有可量化的结果）
- tech_stack：技术栈表述（是否具体、是否命中岗位关键词）
- wording：表述问题（模糊、流水账、无亮点）
- missing：缺失项（该岗位应有但简历没有的内容）

要求：只输出 JSON 数组，不要输出解释或 Markdown 标记。数组元素结构：
{{"category": "star|metrics|tech_stack|wording|missing", "severity": "high|medium|low", "target": "指向的项目/技能/字段", "advice": "具体建议"}}
按 severity（high 优先）排序，最多 {limit} 条。
"""

SUGGEST_USER_PROMPT = """目标岗位：{target_role}
目标公司：{target_companies}

简历内容：
{resume_summary}

请给出简历优化建议。"""
