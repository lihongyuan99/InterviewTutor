"""生成模拟会话数据，用于丰富演示 / 验证向量库检索。

用法：
    tutor/bin/python scripts/gen_mock_sessions.py [--count N]

生成内容：针对现有任务，写入新的会话文件（格式与真实会话完全一致）。
"""

import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SESSIONS_DIR = "memory/sessions"

# 模拟会话内容：每个会话是 (task_id, topic, [(role, content), ...])
# role: "human" | "ai"
MOCK_SESSIONS = [
    {
        "task_id": "task_mt0ualqz",  # RAG基础
        "topic": "RAG",
        "dialog": [
            ("human", "RAG 的检索环节一般用哪些方案？"),
            ("ai", "检索环节通常有几种主流方案：\n\n1. **关键词检索**（BM25 / TF-IDF）：快、可解释，但对同义表达不敏感。\n2. **向量检索**（Embedding + 向量数据库，如 FAISS、Milvus）：语义匹配强，适合模糊查询。\n3. **混合检索**：关键词 + 向量结果融合（RRF 重排），兼顾精确与语义。\n4. **重排模型**（Reranker）：对初召回结果做精排，进一步提升精度。\n\n实际工程里常用「混合检索 + 重排」的组合，因为单一方案很难兼顾召回率和准确率。"),
            ("human", "混合检索里 RRF 是怎么融合的？"),
            ("ai", "RRF（Reciprocal Rank Fusion）是一种免训练的融合算法：\n\n对每个文档 d，在每路检索结果中的排名 rank_i(d) 求倒数之和：\n\nscore(d) = Σ 1 / (k + rank_i(d))\n\n其中 k 是平滑常数（常取 60），避免单路排名靠前就主导全局。\n\n优点：无需调权重、无需训练、对排名尺度不敏感，各路检索分数不可比时也能融合。"),
            ("human", "那重排模型一般用什么？"),
            ("ai", "常用两类：\n\n- **交叉编码器**（Cross-Encoder，如 bge-reranker、Cohere Rerank）：把 query 和 doc 拼接后送入模型打分，精度高但慢，只用于精排少量候选。\n- **双塔模型的分数**复用：快但精度不如交叉编码器。\n\n工程上典型的漏斗是：向量检索召回 Top100 → 关键词补充 → Reranker 精排到 Top5 → 送入 LLM。"),
        ],
    },
    {
        "task_id": "task_mt0w5jro",  # Agent开发面试
        "topic": "Agent",
        "dialog": [
            ("human", "面试时怎么讲清楚 Agent 的 ReAct 模式？"),
            ("ai", "ReAct 是「推理 + 行动」交替进行的模式。讲解时可以分三层：\n\n1. **循环结构**：Thought → Action → Observation → Thought → ... 直到产出 Final Answer。\n2. **工具调用**：Action 就是调用工具（搜索、计算、查库），Observation 是工具返回结果，模型据此更新推理。\n3. **为什么有效**：把「思考过程」外化为可观察的步骤，既能纠错（看到工具结果后修正），又能提升可解释性。\n\n面试加分点：能对比 ReAct vs Plan-and-Execute——ReAct 是逐步决策，Plan 是先规划后执行，后者适合步骤明确的任务，前者适合需要动态调整的场景。"),
            ("human", "Plan-and-Execute 和 ReAct 什么时候该选哪个？"),
            ("ai", "核心判断标准是「任务确定性」：\n\n- **选 Plan-and-Execute**：步骤可预测、目标明确（如「生成周报：先查数据→再汇总→最后排版」）。优点是可并行、可审查计划、token 消耗低。\n- **选 ReAct**：环境不确定、需要根据中间结果动态调整（如「帮我调研某个陌生领域」）。\n\n工程上常见混合：先用一个轻量 Planner 生成粗计划，执行阶段每个子任务内部再用 ReAct 灵活处理。"),
        ],
    },
    {
        "task_id": "task_mt0wdnpg",  # 新的学习（内容最少，丰富它）
        "topic": "Prompt",
        "dialog": [
            ("human", "写 prompt 有哪些实用的工程技巧？"),
            ("ai", "几个高频实用的技巧：\n\n1. **结构化输出**：明确要求 JSON / 指定字段，必要时给 schema 示例。\n2. **Few-shot**：给 2-3 个「输入→期望输出」示例，比纯描述更稳。\n3. **角色设定 + 约束**：明确身份、受众、禁止事项。\n4. **把大任务拆小**：chain-of-thought、分步执行，比一次性要求更可控。\n5. **负例 + 边界**：告诉模型「不要做什么」，比只说「要做什么」更精准。\n\n最重要的是：把 prompt 当代码一样迭代和版本管理，用 eval 集回归测试。"),
            ("human", "few-shot 里示例怎么选效果最好？"),
            ("ai", "选示例有三个原则：\n\n1. **覆盖边界**：挑能代表「易混淆 / 难判」的 case，而不是最简单的那几个。\n2. **多样性**：示例之间尽量不重复，覆盖不同风格和长度。\n3. **与测试集同分布**：示例要贴近真实输入，否则会带偏模型。\n\n进阶技巧：动态检索 few-shot（从样本库里用相似度挑最相关的示例），比固定示例效果好。"),
        ],
    },
    {
        "task_id": "task_mszwng14",  # 代理约束框架
        "topic": "Agent",
        "dialog": [
            ("human", "Agent 里的 harness 具体指什么？"),
            ("ai", "harness（约束框架 / 运行框架）是包裹在 LLM 外、负责控制 Agent 执行边界的那层逻辑。它不参与「思考」，只负责「约束」。\n\n典型职责：\n- **循环控制**：限定最大步数、超时、预算，防止死循环。\n- **工具白名单**：限制模型只能调用授权的工具。\n- **权限与沙箱**：危险操作（写文件、执行命令）需审批或沙箱隔离。\n- **状态管理**：维护对话状态、记忆、中间结果。\n- **可观测性**：记录每一步的 thought/action/tool 调用，便于追踪。\n\n一句话：LLM 是大脑，harness 是「护栏 + 方向盘」。"),
            ("human", "harness 和 prompt 里的约束有什么本质区别？"),
            ("ai", "本质区别在「可执行性」和「强制性」：\n\n- **prompt 约束**：是「请求」，模型可能不遵守，属于软约束。\n- **harness 约束**：是「代码层强制」，模型想越界也做不到，属于硬约束。\n\n比如「不要执行危险命令」写在 prompt 里，模型可能被 prompt 注入绕过；但 harness 里做权限校验 + 沙箱，就能物理上阻断。\n\n所以安全相关的约束，一定不能只依赖 prompt，必须落到 harness 的代码层。"),
        ],
    },
]


def _make_msg(role: str, content: str) -> dict:
    """构造一条与真实会话格式一致的消息。"""
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


def gen_sessions(count: int) -> list[str]:
    """生成会话文件，返回写入的文件路径列表。"""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    written = []

    for spec in MOCK_SESSIONS[:count]:
        task_id = spec["task_id"]
        now = datetime.now()
        # 用当前时间 + 递增序号保证唯一
        ts = now.strftime("%Y%m%d__%H%M%S")
        session_id = f"{task_id}__{ts}"
        # 若同一秒生成多个，追加毫秒避免冲突
        base = session_id
        i = 1
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
            "messages": [_make_msg(role, content) for role, content in spec["dialog"]],
        }

        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        written.append(path)
        print(f"  生成 {session_id}（{len(spec['dialog'])} 条消息，topic={spec['topic']}）")

    return written


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成模拟会话数据")
    parser.add_argument("--count", type=int, default=len(MOCK_SESSIONS),
                        help="生成前 N 个模拟会话（默认全部）")
    args = parser.parse_args()

    print(f"开始生成 {min(args.count, len(MOCK_SESSIONS))} 个模拟会话...\n")
    paths = gen_sessions(args.count)
    print(f"\n完成，共生成 {len(paths)} 个会话文件。")
    print("提示：生成后可运行 backfill_vector_store.py 将这些会话写入向量库。")
