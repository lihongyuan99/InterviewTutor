"""为 6 个新任务生成模拟会话，主题对齐，并回填向量库。

用法：
    tutor/bin/python scripts/gen_mock_sessions_new.py [--no-backfill]
"""

import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SESSIONS_DIR = "memory/sessions"

# 6 个新任务 -> 主题 + 对话内容
NEW_TASK_SESSIONS = [
    {
        "task_id": "task_mt0y1ctd",
        "topic": "向量数据库",
        "dialog": [
            ("human", "选型向量数据库时主要看哪些指标？"),
            ("ai", "核心指标有四类：\n\n1. **召回性能**：QPS、查询延迟（P99）、召回率。\n2. **索引类型**：HNSW（快、内存大）、IVF（省内存、需训练）、Flat（精确但慢）。\n3. **过滤能力**：是否支持标量过滤 + 向量混合查询（filter + ANN）。\n4. **运维成本**：持久化、水平扩展、是否托管。\n\n常见选择：数据量小（<百万）用 FAISS 内存版即可；需要持久化和过滤用 Milvus / Qdrant；云上省事用 Pinecone。"),
            ("human", "HNSW 和 IVF 怎么选？"),
            ("ai", "HNSW 是图索引，IVF 是倒排聚类：\n\n- **HNSW**：查询快、召回高，但内存占用大、构建慢，适合内存充足的中等规模。\n- **IVF**：内存省、可上亿级，但需要训练、召回略低，需配合 nprobe 调参。\n\n经验法则：百万级以内、追求低延迟选 HNSW；千万级以上、内存受限选 IVF。"),
        ],
    },
    {
        "task_id": "task_mt0y1cte",
        "topic": "多Agent",
        "dialog": [
            ("human", "多 Agent 协作一般有哪些组织模式？"),
            ("ai", "主流有三种：\n\n1. **顺序流水线**：Agent A 的输出作为 B 的输入（如 检索→生成→审核）。\n2. **中心化协调**（Orchestrator-Worker）：一个主控 Agent 拆解任务、分发给多个 Worker。\n3. **去中心化协作**：多个对等 Agent 通过消息传递协商（如 AutoGen 的 group chat）。\n\n选型看任务：步骤清晰用流水线；需要动态编排用中心化；需要自主协商用去中心化。"),
            ("human", "多 Agent 的难点主要在哪？"),
            ("ai", "三个老大难：\n\n1. **上下文与记忆共享**：多个 Agent 之间如何高效传递状态，避免信息丢失或重复。\n2. **错误传播**：上游 Agent 出错会级联到下游，需要中间校验。\n3. **成本与延迟**：多轮多 Agent 调用 token 消耗和时延显著上升。\n\n工程上常用「共享记忆 + 结构化消息协议 + 关键节点人工/规则校验」来缓解。"),
        ],
    },
    {
        "task_id": "task_mt0y1ctf",
        "topic": "评估",
        "dialog": [
            ("human", "LLM 应用怎么搭评估体系？"),
            ("ai", "分三层：\n\n1. **单点评估**：检索（Hit@k、Recall）、生成（事实性、相关性、流畅度）。\n2. **端到端评估**：整条链路的最终回答质量（人工 + LLM-as-judge）。\n3. **回归评估**：黄金集 + 持续跑分，防止改动退化。\n\n关键是先建**黄金查询集**（20-30 条带标注的 case），否则无法量化。"),
            ("human", "LLM-as-judge 靠谱吗？怎么用？"),
            ("ai", "LLM-as-judge 可用于初筛，但需注意：\n\n- **与人工对齐**：先拿几十条让 LLM 评分，和人工标注算一致性（如 Cohen's kappa）。\n- **避免偏差**：位置偏见（偏好第一个答案）、长度偏见，可交换顺序多次打分取均值。\n- **只做粗筛**：最终上线决策仍需人工抽检。\n\n结论：适合做「快速回归 + 粗排」，不适合替代关键场景的人工评估。"),
        ],
    },
    {
        "task_id": "task_mt0y1ctg",
        "topic": "函数调用",
        "dialog": [
            ("human", "设计 tool calling 的工具描述要注意什么？"),
            ("ai", "工具描述是模型选工具的依据，关键点：\n\n1. **名字语义化**：`get_user_by_id` 优于 `f1`。\n2. **参数描述精确**：类型、约束、示例都要写清楚。\n3. **明确副作用**：区分「只读」和「写操作」，避免模型误用。\n4. **控制工具数量**：工具太多模型会选错，可分组 + 按需注入。\n\n本质是把工具的「能力边界」讲清楚，降低模型的调用歧义。"),
            ("human", "工具太多导致模型选错怎么办？"),
            ("ai", "三个策略：\n\n1. **按场景分组注入**：只把当前任务相关的工具暴露给模型，而不是全部。\n2. **路由前置**：先用一个轻量分类器判断意图，再给对应工具集。\n3. **工具描述去重**：功能重叠的工具合并，避免模型在相似工具间纠结。\n\n核心思路是「缩小候选空间」，而不是让模型从几十个工具里硬选。"),
        ],
    },
    {
        "task_id": "task_mt0y1cth",
        "topic": "微调",
        "dialog": [
            ("human", "什么时候该微调，什么时候用 RAG 就够了？"),
            ("ai", "判断维度是「知识」还是「能力」：\n\n- **RAG**：需要外部知识、实时数据、可溯源时用 RAG（成本低、更新快）。\n- **微调**：需要改变模型的「行为风格」或「特定领域能力」时用（如让模型固定输出某种格式、学会特定术语体系）。\n\n常见误区：想注入新知识就微调——其实 RAG 更合适且可解释。微调适合「风格/格式/能力」层面的定制。"),
            ("human", "RAG 和微调能结合吗？"),
            ("ai", "可以，且常结合：\n\n1. **微调做「能力」**：让模型学会某领域的推理习惯、输出格式。\n2. **RAG 做「知识」**：动态注入最新、可溯源的内容。\n\n典型组合：微调后的模型 + RAG 检索，既具备领域能力，又能访问实时知识。但工程复杂度高，建议先单独验证各自效果再组合。"),
        ],
    },
    {
        "task_id": "task_mt0y1cti",
        "topic": "推理规划",
        "dialog": [
            ("human", "让 LLM 做多步推理，有哪些常用技术？"),
            ("ai", "主要三类：\n\n1. **CoT（思维链）**：引导模型「一步步想」，最简单有效。\n2. **ToT（思维树）**：维护多条推理路径，回溯 + 剪枝，适合复杂搜索型问题。\n3. **自我一致性**：多次采样 + 投票，降低单次推理的随机性。\n\n工程上先上 CoT，简单问题够用；复杂规划再用 ToT 或结合外部 Planner。"),
            ("human", "CoT 和显式的 Plan-and-Execute 什么关系？"),
            ("ai", "两者互补：\n\n- **CoT** 是「隐式推理」，让模型在内部把思路展开，不产生可执行的动作。\n- **Plan-and-Execute** 是「显式规划」，产出结构化计划，交给执行器逐步完成。\n\n复杂任务通常「先 Plan 定框架，再让每一步内部用 CoT 细化」，既能全局规划又能局部推理。"),
        ],
    },
]


def _make_msg(role: str, content: str) -> dict:
    msg_type = "human" if role == "human" else "ai"
    data = {
        "content": content,
        "additional_kwargs": {},
        "response_metadata": {},
        "type": msg_type,
        "name": None,
        "id": str(uuid.uuid4()),
    }
    if msg_type == "ai":
        data.update({
            "tool_calls": [],
            "invalid_tool_calls": [],
            "usage_metadata": None,
        })
    return {"type": msg_type, "data": data}


def gen() -> list[str]:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    written = []
    now = datetime.now()
    for spec in NEW_TASK_SESSIONS:
        task_id = spec["task_id"]
        ts = now.strftime("%Y%m%d__%H%M%S")
        session_id = f"{task_id}__{ts}"
        i = 1
        base = session_id
        while os.path.exists(os.path.join(SESSIONS_DIR, f"{session_id}.json")):
            session_id = f"{base}_{i}"
            i += 1

        record = {
            "session_id": session_id,
            "task_id": task_id,
            "last_updated": now.isoformat(),
            "topic": spec["topic"],
            "conversation_summary": "",
            "summarized_msg_count": 0,
            "messages": [_make_msg(r, c) for r, c in spec["dialog"]],
        }
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        written.append(path)
        print(f"  生成 {session_id}（{len(spec['dialog'])} 条，topic={spec['topic']}）")
    return written


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-backfill", action="store_true", help="不回填向量库")
    args = parser.parse_args()

    print(f"为 {len(NEW_TASK_SESSIONS)} 个新任务生成模拟会话...\n")
    written = gen()
    print(f"\n完成，共生成 {len(written)} 个会话文件。")

    if not args.no_backfill:
        print("\n回填向量库...\n")
        import subprocess
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "backfill_vector_store.py")],
            check=False,
        )
