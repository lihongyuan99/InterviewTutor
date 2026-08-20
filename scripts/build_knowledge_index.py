#!/usr/bin/env python3
"""构建面试知识索引（或仅解析）。

用法：
    # 仅解析，输出统计与结构化 JSON，不调用模型、不下载 Embedding
    python scripts/build_knowledge_index.py --parse-only

    # 完整构建：解析 + 生成向量 + 写入 SQLite（含 FTS5 索引）
    python scripts/build_knowledge_index.py

    # 完整构建，指定知识库目录与数据库路径
    python scripts/build_knowledge_index.py --dir knowledge --db data/knowledge.db

    # 只解析 + 入库，不生成向量
    python scripts/build_knowledge_index.py --no-embedding
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# 允许以脚本方式直接运行时正确导入项目内模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge import parse_knowledge_dir  # noqa: E402


def _dump_json(questions, warnings, output_path: Path) -> None:
    payload = {
        "count": len(questions),
        "questions": [q.model_dump() for q in questions],
        "warnings": [w.model_dump() for w in warnings],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已写入结构化 JSON：{output_path}")


def _print_stats(questions, warnings) -> None:
    print(f"题目总数：{len(questions)}")
    print(f"解析警告：{len(warnings)}")

    dim_counter = Counter(q.dimension for q in questions)
    print("\n按维度统计：")
    for dim, cnt in sorted(dim_counter.items(), key=lambda x: -x[1]):
        print(f"  {dim}: {cnt}")

    comp_counter = Counter(c for q in questions for c in q.companies)
    if comp_counter:
        print("\n按公司统计（来源提及）：")
        for comp, cnt in comp_counter.most_common():
            print(f"  {comp}: {cnt}")

    missing_expert = sum(1 for q in questions if not q.expert_answer)
    missing_gap = sum(1 for q in questions if not q.gap_analysis)
    print("\n数据质量：")
    print(f"  缺高手答：{missing_expert}")
    print(f"  缺差距分析：{missing_gap}")

    if warnings:
        print("\n解析警告明细：")
        for w in warnings[:50]:
            loc = f":{w.line}" if w.line else ""
            print(f"  [{w.file}{loc}] {w.message}")
        if len(warnings) > 50:
            print(f"  ... 其余 {len(warnings) - 50} 条省略")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建面试知识索引")
    parser.add_argument("--dir", default="knowledge", help="知识库目录（默认 knowledge）")
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="仅解析，输出统计与 JSON，不构建向量索引、不写数据库",
    )
    parser.add_argument(
        "--no-embedding",
        action="store_true",
        help="入库时不生成向量（仅 FTS5 关键词检索）",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite 数据库路径（默认取 config 的 KNOWLEDGE_DB_PATH）",
    )
    parser.add_argument(
        "--output",
        default="data",
        help="JSON 输出目录（默认 data/）",
    )
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        print(f"错误：目录不存在：{root}", file=sys.stderr)
        return 1

    questions, warnings = parse_knowledge_dir(str(root))
    _print_stats(questions, warnings)

    if not questions:
        print("\n错误：未解析到任何题目，请检查知识库目录结构。", file=sys.stderr)
        return 1

    # 输出 JSON
    out_dir = Path(args.output)
    _dump_json(questions, warnings, out_dir / "knowledge_parsed.json")

    if args.parse_only:
        print("\n--parse-only 模式：已完成解析，未构建索引。")
        return 0

    # 完整构建：解析 + 向量 + 入库
    from app.knowledge import build_index  # noqa: E402

    print("\n构建索引...")
    stats = build_index(
        str(root),
        db_path=args.db,
        with_embedding=not args.no_embedding,
        progress=True,
    )
    print("\n完成！知识库就绪：")
    print(f"  总题数：{stats['total']}")
    print(f"  维度数：{stats['dimensions']}")
    print(f"  含向量：{stats['with_embedding']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
