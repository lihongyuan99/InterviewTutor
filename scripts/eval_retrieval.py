"""知识库检索离线评测脚本。

对 ``data/golden_queries.json`` 中的黄金查询逐一调用检索器，
计算 Hit@1/3/5、MRR、Recall@5，并按维度、查询类型分组输出报告，
同时打印每条的命中明细（便于定位 bad case）。

用法：
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --golden data/golden_queries.json --top-k 5
    python scripts/eval_retrieval.py --dimension rag          # 只评某维度
    python scripts/eval_retrieval.py --type paraphrase         # 只评某查询类型

依赖：``data/knowledge.db`` 已构建，且本地 Embedding 服务在线
（检索的向量通道需要 embedding 接口）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.knowledge import search  # noqa: E402


def _load_golden(path: Path) -> List[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["queries"]


def _hit_at_k(ranked_ids: List[str], relevant_ids: List[str], k: int) -> bool:
    """前 k 个结果中是否命中任一相关题目。"""
    return any(rid in ranked_ids[:k] for rid in relevant_ids)


def _mrr(ranked_ids: List[str], relevant_ids: List[str]) -> float:
    """第一个相关结果排名的倒数；未命中为 0。"""
    for i, rid in enumerate(ranked_ids, 1):
        if rid in relevant_ids:
            return 1.0 / i
    return 0.0


def _recall_at_k(ranked_ids: List[str], relevant_ids: List[str], k: int) -> float:
    """Top-K 中召回的相关题目占比。无相关标注时返回 1.0（负样本）。"""
    if not relevant_ids:
        return 1.0
    hit = sum(1 for rid in relevant_ids if rid in ranked_ids[:k])
    return hit / len(relevant_ids)


def evaluate(queries: List[dict], top_k: int = 5, threshold: float = 0.0) -> Dict:
    """逐条评测，返回汇总指标与逐条明细。"""
    rows = []
    for q in queries:
        query = q["query"]
        relevant = q.get("relevant_ids", [])
        qtype = q.get("type", "verbatim")
        dimension = q.get("dimension", "")

        try:
            results = search(query, limit=top_k, threshold=threshold)
        except Exception as e:  # noqa: BLE001 - 单条失败不中断整体
            rows.append(
                {
                    "id": q["id"],
                    "query": query,
                    "type": qtype,
                    "dimension": dimension,
                    "relevant_ids": relevant,
                    "returned_ids": [],
                    "error": str(e),
                    "hit1": False,
                    "hit3": False,
                    "hit5": False,
                    "mrr": 0.0,
                    "recall5": 0.0,
                }
            )
            continue

        ranked_ids = [r.question_id for r in results]

        rows.append(
            {
                "id": q["id"],
                "query": query,
                "type": qtype,
                "dimension": dimension,
                "relevant_ids": relevant,
                "returned_ids": ranked_ids,
                "scores": [round(r.score, 4) for r in results],
                "error": None,
                "hit1": _hit_at_k(ranked_ids, relevant, 1),
                "hit3": _hit_at_k(ranked_ids, relevant, 3),
                "hit5": _hit_at_k(ranked_ids, relevant, 5),
                "mrr": _mrr(ranked_ids, relevant),
                "recall5": _recall_at_k(ranked_ids, relevant, 5),
            }
        )

    # 汇总（排除负样本 negative：无 relevant_ids 的查询不参与命中统计）
    positive = [r for r in rows if r["relevant_ids"]]
    negatives = [r for r in rows if not r["relevant_ids"]]
    n = len(positive) or 1

    # 负样本拦截率：threshold 下负样本应返回空（拦截成功）
    blocked = sum(1 for r in negatives if not r["returned_ids"])
    n_neg = len(negatives)

    summary = {
        "total_queries": len(rows),
        "positive_queries": len(positive),
        "negative_queries": n_neg,
        "hit@1": sum(r["hit1"] for r in positive) / n,
        "hit@3": sum(r["hit3"] for r in positive) / n,
        "hit@5": sum(r["hit5"] for r in positive) / n,
        "mrr": sum(r["mrr"] for r in positive) / n,
        "recall@5": sum(r["recall5"] for r in positive) / n,
        "negative_blocked": blocked,
        "negative_block_rate": (blocked / n_neg) if n_neg else 1.0,
    }

    return {"summary": summary, "rows": rows}


def _group_stats(rows: List[dict], key: str) -> Dict[str, dict]:
    """按维度或查询类型分组统计。"""
    groups: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        if not r["relevant_ids"]:
            continue
        groups[r.get(key) or "(未标注)"].append(r)

    out = {}
    for name, items in sorted(groups.items()):
        n = len(items)
        out[name] = {
            "count": n,
            "hit@1": sum(r["hit1"] for r in items) / n,
            "hit@3": sum(r["hit3"] for r in items) / n,
            "hit@5": sum(r["hit5"] for r in items) / n,
            "mrr": sum(r["mrr"] for r in items) / n,
        }
    return out


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def print_report(result: Dict) -> None:
    summary = result["summary"]
    rows = result["rows"]

    print("=" * 64)
    print("知识库检索评测报告")
    print("=" * 64)
    print(f"总查询数:   {summary['total_queries']}")
    print(f"  正样本:   {summary['positive_queries']}")
    print(f"  负样本:   {summary['negative_queries']}")
    print("-" * 64)
    print(f"Hit@1 : {_pct(summary['hit@1'])}")
    print(f"Hit@3 : {_pct(summary['hit@3'])}")
    print(f"Hit@5 : {_pct(summary['hit@5'])}")
    print(f"MRR   : {summary['mrr']:.4f}")
    print(f"Recall@5: {_pct(summary['recall@5'])}")
    if summary.get("negative_queries"):
        print(f"负样本拦截: {summary['negative_blocked']}/{summary['negative_queries']} "
              f"({_pct(summary['negative_block_rate'])})")

    # 按维度
    print("\n按维度分组：")
    dim_stats = _group_stats(rows, "dimension")
    print(f"  {'维度':<20}{'条数':>4}{'Hit@1':>8}{'Hit@3':>8}{'Hit@5':>8}{'MRR':>8}")
    for name, s in dim_stats.items():
        print(
            f"  {name:<20}{s['count']:>4}{_pct(s['hit@1']):>8}"
            f"{_pct(s['hit@3']):>8}{_pct(s['hit@5']):>8}{s['mrr']:>8.4f}"
        )

    # 按查询类型
    print("\n按查询类型分组：")
    type_stats = _group_stats(rows, "type")
    print(f"  {'类型':<18}{'条数':>4}{'Hit@1':>8}{'Hit@3':>8}{'Hit@5':>8}{'MRR':>8}")
    for name, s in type_stats.items():
        print(
            f"  {name:<18}{s['count']:>4}{_pct(s['hit@1']):>8}"
            f"{_pct(s['hit@3']):>8}{_pct(s['hit@5']):>8}{s['mrr']:>8.4f}"
        )

    # 未命中明细（bad case）
    misses = [r for r in rows if r["relevant_ids"] and not r["hit5"]]
    if misses:
        print("\n未命中明细（Hit@5 失败）：")
        for r in misses:
            print(f"  [{r['id']}] {r['query']}")
            print(f"        期望: {r['relevant_ids']}")
            print(f"        返回: {r['returned_ids']}")

    # 负样本表现（应低分/拒答）
    negatives = [r for r in rows if not r["relevant_ids"]]
    if negatives:
        print("\n负样本表现（期望无高相关结果）：")
        for r in negatives:
            if not r["returned_ids"]:
                print(f"  [{r['id']}] {r['query']} -> 已拦截 ✓")
            else:
                top = r["returned_ids"][:1]
                top_score = r["scores"][0] if r["scores"] else 0.0
                print(f"  [{r['id']}] {r['query']} -> 最高分 {top_score:.4f} ({top})")


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库检索离线评测")
    parser.add_argument(
        "--golden", default=str(ROOT / "data" / "golden_queries.json"),
        help="黄金查询集路径",
    )
    parser.add_argument("--top-k", type=int, default=5, help="检索 Top-K")
    parser.add_argument(
        "--threshold", type=float, default=0.5,
        help="检索相似度阈值（默认 0.5，与学习模式一致）",
    )
    parser.add_argument("--dimension", default="", help="只评测指定维度")
    parser.add_argument("--type", default="", help="只评测指定查询类型")
    parser.add_argument("--json", action="store_true", help="输出 JSON（便于归档）")
    args = parser.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"黄金查询集不存在：{golden_path}")
        sys.exit(1)

    queries = _load_golden(golden_path)
    if args.dimension:
        queries = [q for q in queries if q.get("dimension") == args.dimension]
    if args.type:
        queries = [q for q in queries if q.get("type") == args.type]

    if not queries:
        print("没有符合条件的查询")
        sys.exit(1)

    result = evaluate(queries, top_k=args.top_k, threshold=args.threshold)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
