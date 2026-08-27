"""面试知识库 Markdown 解析器。

将 ``knowledge/`` 目录下的 Markdown 文件解析为结构化的
:class:`~app.knowledge.schema.InterviewQuestion` 记录。

支持两类文件：

1. **单题文件**：如 ``01-architecture/react-loop.md``，包含一个或多个
   ``## Q：...`` 段落，可能带有独立的 ``## 考察点`` / ``## 追问`` 段落。
2. **多题 index 文件**：如 ``01-architecture-design/index.md``，包含
   frontmatter + 多个 ``### Q：...`` 段落，考察点/追问内嵌在问题段落内
   （例如 ``**追问：...**`` 段落）。

本模块只做解析，不调用模型、不下载 Embedding、不修改现有聊天行为。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Optional, Tuple

from app.knowledge.schema import InterviewQuestion, ParseWarning

# 需要跳过的非题库目录：coaching-methodology 为辅导方法论，
# 14-company-preferences 为公司偏好速查（不含 Q 段落）。
_SKIP_DIRS = {"coaching-methodology", "14-company-preferences"}

# 目录名 -> 维度（dimension）映射。未命中的目录回退为其目录名。
# 维度用于跨目录合并同概念题目，避免 01-architecture 与
# 01-architecture-design 被当作两个不同维度。
_DIMENSION_ALIASES = {
    "01-architecture-design": "architecture",
    "01-architecture": "architecture",
    "02-engineering": "engineering",
    "02-tool-management": "tool-management",
    "03-fault-tolerance": "fault-tolerance",
    "03-model": "model",
    "04-memory-context": "memory-context",
    "04-rag": "rag",
    "05-eval-and-vision": "evaluation",
    "05-multi-agent": "multi-agent",
    "06-evaluation": "evaluation",
    "06-multi-agent-collab": "multi-agent",
    "07-engineering-pitfalls": "engineering-pitfalls",
    "07-full-stack": "full-stack",
    "08-prompt-engineering": "prompt-engineering",
    "09-rag-retrieval": "rag",
    "10-training-and-data": "training",
    "11-ai-code-testing": "ai-code-testing",
    "12-business-ai-engineering": "business-ai",
    "13-project-deep-dive": "project-deep-dive",
    "14-company-preferences": "company-preferences",
    "15-agent-concepts": "agent-concepts",
    "16-agent-infra": "agent-infra",
    "17-ai-infra": "ai-infra",
}

# 维度 -> 中文名。用于 dimension_label 字段。
_DIMENSION_LABELS = {
    "architecture": "架构选型",
    "tool-management": "工具管理",
    "fault-tolerance": "容错与鲁棒性",
    "memory-context": "记忆与上下文",
    "evaluation": "评估与全局观",
    "multi-agent": "多智能体协作",
    "engineering-pitfalls": "工程化踩坑",
    "prompt-engineering": "Prompt 工程",
    "rag": "RAG 与检索",
    "training": "训练与模型",
    "ai-code-testing": "AI 代码测试",
    "business-ai": "业务 AI 工程",
    "project-deep-dive": "简历项目深挖",
    "company-preferences": "公司偏好",
    "agent-concepts": "Agent 概念",
    "agent-infra": "Agent 基础设施",
    "ai-infra": "AI 基础设施",
    "engineering": "工程实践",
    "model": "模型",
    "full-stack": "全栈工程",
}


def _dimension_label(dimension: str) -> str:
    return _DIMENSION_LABELS.get(dimension, dimension)


# 常见公司名，用于从「来源」行提取公司标签。
_COMPANY_PATTERNS = [
    "腾讯", "字节", "阿里", "蚂蚁", "淘宝", "淘天", "快手", "小红书",
    "美团", "百度", "京东", "拼多多", "滴滴", "携程", "bilibili",
    "高德", "抖音", "快手",
]

_Q_RE = re.compile(r"^(#{2,3})\s+Q[：:]\s*(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SOURCE_RE = re.compile(r"^>\s*来源[：:]\s*(.*)$")
_NOVICE_RE = re.compile(r"^\*\*新手答?\*\*[：:]?\s*(.*)$")
_EXPERT_RE = re.compile(r"^\*\*高手答?\*\*[：:]?\s*(.*)$")
_GAP_RE = re.compile(r"^\*\*(?:差距在哪|关键差距|差距分析)\*\*[：:]\s*(.*)$")
_KEYPOINT_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_INLINE_FOLLOWUP_RE = re.compile(r"^\*\*追问[：:]\s*(.*?)\*\*\s*$")
_INLINE_FOLLOWUP_BODY_RE = re.compile(r"^\*\*追问[：:]\s*(.*)$")


def _normalize_dimension(dirname: str) -> str:
    return _DIMENSION_ALIASES.get(dirname, dirname)


def _slugify(text: str, limit: int = 40) -> str:
    """从问题文本生成稳定、可复现的短 slug。"""
    # 仅保留中文、字母、数字、连字符，空格/标点转连字符
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        return "q"
    return cleaned[:limit].lower()


def _stable_id(dimension: str, question: str, source_file: str) -> str:
    """基于维度 + 问题文本生成稳定 ID。

    使用问题文本的哈希保证同一道题在不同次解析时 ID 稳定；
    维度与文件路径参与作为人类可读前缀与消歧。
    """
    slug = _slugify(question)
    digest = hashlib.md5(question.strip().encode("utf-8")).hexdigest()[:8]
    return f"{dimension}-{slug}-{digest}"


def _extract_companies(text: str) -> List[str]:
    """从「来源」文本中提取公司名。"""
    found: List[str] = []
    for name in _COMPANY_PATTERNS:
        if name in text and name not in found:
            found.append(name)
    return found


def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """剥离并解析文件开头的 YAML frontmatter（若存在）。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    meta: dict = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, text[end + 4:]


class KnowledgeParser:
    """解析 ``knowledge/`` 目录，产出题目记录与警告。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.warnings: List[ParseWarning] = []

    def _warn(self, file: str, message: str, line: Optional[int] = None) -> None:
        self.warnings.append(ParseWarning(file=file, message=message, line=line))

    def parse_all(self) -> List[InterviewQuestion]:
        """解析根目录下所有可解析的 Markdown 题库文件。"""
        questions: List[InterviewQuestion] = []
        for md in sorted(self.root.rglob("*.md")):
            rel = md.relative_to(self.root)
            parts = rel.parts
            # 跳过非题库目录（coaching-methodology）
            if any(p in _SKIP_DIRS for p in parts):
                continue
            # 只有直接位于维度目录下的文件才是题库文件
            # （knowledge/ 根下的 README.md 等不属于题库）
            if len(parts) < 2:
                continue
            dimension = _normalize_dimension(parts[0])
            try:
                qs = self.parse_file(md, dimension)
            except Exception as e:  # noqa: BLE001 - 解析失败不应中断整体
                self._warn(str(rel), f"解析文件异常：{e}")
                continue
            if not qs:
                self._warn(str(rel), "未解析到任何 Q 段落")
            questions.extend(qs)
        return questions

    def parse_file(self, path: Path, dimension: str) -> List[InterviewQuestion]:
        """解析单个 Markdown 文件为题目列表。"""
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(self.root))
        meta, body = _parse_frontmatter(text)
        # 提取 frontmatter 里的 title（若有）
        fm_title = meta.get("title", "")

        blocks = self._split_questions(body)
        questions: List[InterviewQuestion] = []
        for idx, block in enumerate(blocks):
            q = self._parse_block(block, dimension, rel, fm_title if idx == 0 else "")
            if q is not None:
                questions.append(q)
        return questions

    # ---- 内部切分 ----

    def _split_questions(self, body: str) -> List[Tuple[int, int, str, str]]:
        """将文件正文切分为若干问题块。

        返回列表，每项为 ``(start_line, heading, question_text, block_text)``。
        ``block_text`` 从该 Q 标题到下一个 Q 标题（或文件末尾）之间。
        """
        lines = body.splitlines()
        blocks: List[Tuple[int, int, str, str]] = []
        current: Optional[Tuple[int, int, str, List[str]]] = None

        for i, line in enumerate(lines):
            m = _Q_RE.match(line)
            if not m:
                if current is not None:
                    current[3].append(line)
                continue
            # 遇到新 Q，收尾上一个 block
            if current is not None:
                sline, lvl, heading, buf = current
                blocks.append((sline, lvl, heading, "\n".join(buf)))
            level = len(m.group(1))
            current = (i + 1, level, m.group(2).strip(), [line])

        if current is not None:
            sline, lvl, heading, buf = current
            blocks.append((sline, lvl, heading, "\n".join(buf)))

        # 兼容无 Q 标题、但存在「新手答/高手答」结构的单题文件
        if not blocks and "**高手答" in body:
            blocks.append((1, 2, "", body))

        return blocks

    def _parse_block(
        self,
        block: Tuple[int, int, str, str],
        dimension: str,
        rel: str,
        fm_title: str,
    ) -> Optional[InterviewQuestion]:
        start_line, level, heading, text = block
        question_text = heading or fm_title or ""

        novice = ""
        expert_parts: List[str] = []
        gap_parts: List[str] = []
        key_points: List[str] = []
        followups: List[str] = []
        companies: List[str] = []
        source_line = ""

        # 是否已经遇到「高手答」标记（一旦开始，直到「考察点/追问」章节才结束）
        expert_started = False
        # 是否已经遇到「差距在哪」标记（终止高手答收集）
        gap_started = False
        # 独立「考察点」/「追问」段落
        in_keypoint_section = False
        in_followup_section = False

        lines = text.splitlines()
        for line in lines:
            s = line.strip()

            # 跳过空行与分隔线
            if not s or s == "---":
                continue

            # 来源行
            sm = _SOURCE_RE.match(s)
            if sm:
                source_line = sm.group(1)
                companies = _extract_companies(source_line)
                continue

            # 新手答
            nm = _NOVICE_RE.match(s)
            if nm:
                novice = nm.group(1).strip().strip("\"'")
                expert_started = False
                gap_started = False
                in_keypoint_section = False
                in_followup_section = False
                continue

            # 高手答开始
            em = _EXPERT_RE.match(s)
            if em:
                expert_started = True
                gap_started = False
                in_keypoint_section = False
                in_followup_section = False
                if em.group(1).strip():
                    expert_parts.append(em.group(1).strip())
                continue

            # 差距在哪（终止高手答，开始差距分析）
            gm = _GAP_RE.match(s)
            if gm:
                gap_started = True
                expert_started = False
                in_keypoint_section = False
                in_followup_section = False
                if gm.group(1).strip():
                    gap_parts.append(gm.group(1).strip())
                continue

            # 内嵌追问标题（**追问：xxx**）
            fm = _INLINE_FOLLOWUP_RE.match(s)
            if fm:
                followups.append(fm.group(1).strip())
                in_keypoint_section = False
                in_followup_section = False
                continue

            # 章节标题
            hm = _HEADING_RE.match(s)
            if hm:
                sec_title = hm.group(2).strip()
                lvl = len(hm.group(1))
                if lvl <= 3 and sec_title in ("考察点", "考点"):
                    expert_started = False
                    in_keypoint_section = True
                    in_followup_section = False
                elif lvl <= 3 and sec_title == "追问":
                    expert_started = False
                    in_followup_section = True
                    in_keypoint_section = False
                else:
                    # 高手答内部的普通子标题仍属于专家回答内容；
                    # 差距分析内部的子标题属于差距分析
                    if expert_started:
                        expert_parts.append(line)
                    elif gap_started:
                        gap_parts.append(line)
                    else:
                        in_keypoint_section = False
                        in_followup_section = False
                continue

            # 列表项
            km = _KEYPOINT_RE.match(s)
            if km:
                content = km.group(1).strip()
                if in_keypoint_section:
                    key_points.append(content)
                elif in_followup_section:
                    followups.append(content)
                elif expert_started:
                    expert_parts.append(line)
                elif gap_started:
                    gap_parts.append(line)
                # 否则忽略（可能是问题外的普通列表）
                continue

            # 内嵌追问的正文（**追问：xxx** 之后的内容）
            bm = _INLINE_FOLLOWUP_BODY_RE.match(s)
            if bm:
                followups.append(bm.group(1).strip())
                in_keypoint_section = False
                in_followup_section = False
                continue

            # 其余内容
            if expert_started:
                expert_parts.append(line)
            elif gap_started:
                gap_parts.append(line)
            elif in_keypoint_section:
                # 非列表的考察点段落
                if s and not s.startswith(">"):
                    key_points.append(s)
            elif in_followup_section:
                if s and not s.startswith(">"):
                    followups.append(s)

        expert = "\n".join(expert_parts).strip()
        gap = "\n".join(gap_parts).strip()

        # 无问题文本则无法形成有效记录
        if not question_text:
            self._warn(rel, f"第 {start_line} 行附近的 Q 段落缺少问题文本，已跳过")
            return None
        if not expert:
            self._warn(rel, f"题目「{question_text[:30]}」缺少高手答")

        # 提取 tags：从问题文本中识别常见技术关键词
        tags = _extract_tags(question_text)

        qid = _stable_id(dimension, question_text, rel)

        return InterviewQuestion(
            id=qid,
            dimension=dimension,
            dimension_label=_dimension_label(dimension),
            title=question_text,
            question=question_text,
            source=source_line,
            novice_answer=novice,
            expert_answer=expert,
            gap_analysis=gap,
            key_points=key_points,
            followups=followups,
            companies=companies,
            tags=tags,
            difficulty=0,
            source_file=rel,
            source_heading=question_text,
        )


_TAG_KEYWORDS = [
    "ReAct", "Plan-and-Execute", "ToT", "CoT", "RAG", "GraphRAG", "Embedding",
    "Rerank", "MCP", "Function Calling", "Tool Calling", "Prompt", "微调",
    "RLHF", "GRPO", "多智能体", "记忆", "上下文", "向量", "召回", "幻觉",
    "Agent", "SSE", "流式", "缓存", "Human-in-the-Loop",
]


def _extract_tags(text: str) -> List[str]:
    tags: List[str] = []
    for kw in _TAG_KEYWORDS:
        if kw.lower() in text.lower() and kw not in tags:
            tags.append(kw)
    return tags


def parse_knowledge_dir(root: str) -> Tuple[List[InterviewQuestion], List[ParseWarning]]:
    """便捷入口：解析目录并返回题目列表与警告列表。"""
    parser = KnowledgeParser(Path(root))
    questions = parser.parse_all()
    return questions, parser.warnings
