"""Evaluate the positive-retrieval baseline for customer-facing business knowledge.

This intentional AI evaluation does not cover no-answer behavior, out-of-domain
rejection, relevance thresholds, ambiguous queries, multiple equivalent sources,
or adversarial retrieval.

python -m app.scripts.evaluate_business_knowledge_retrieval
"""
import json
import tempfile
from pathlib import Path

from app.rag.chunking import FixedSizeChunkingStrategy
from app.rag.embeddings import SentenceTransformerEmbeddingProvider
from app.rag.ingestion import KnowledgeIngestor
from app.rag.retriever import VectorRetriever
from app.rag.vector_store import ChromaVectorStore


KNOWLEDGE_DIR = Path(__file__).parents[1] / "data" / "business_knowledge"
# 固定与当前 Business Knowledge ingestion 对齐的 baseline，避免本地 .env 静默改变评估条件。
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
CHUNK_SIZE = 100
CHUNK_OVERLAP = 20
TOP_K = 3
# 每条 positive-retrieval case 包含 query、唯一 expected source 和 required evidence terms。
CASES = [
    ("签收以后，七天无理由退货一共有多长时间？", "no_reason_return_policy.md", ("7 × 24 小时",)),
    ("刚好到了退货截止时间，还来得及申请吗？", "no_reason_return_policy.md", ("截止时刻", "仍在期限内")),
    ("店里的每件商品都可以无理由退货吗？", "no_reason_return_policy.md", ("明确支持无理由退货",)),
    ("订单还没寄出来，我现在能取消吗？", "cancellation_policy.md", ("尚未进入发货流程", "可以申请取消")),
    ("快递已经发出了，这个订单还能直接取消吗？", "cancellation_policy.md", ("不能直接取消",)),
    ("一个商品的退货还在处理中，可以再提一次吗？", "after_sales_requests.md", ("不能重复提交",)),
    ("哪些情况表示售后流程还没有结束？", "after_sales_requests.md",
     ("已提交待处理", "已审核通过", "退回途中", "已收到退回商品")),
    ("物流四天都没有有效更新，算异常吗？", "logistics_exception.md", ("严格超过 72 小时",)),
    ("物流正好停在 72 小时，已经算超时异常了吗？", "logistics_exception.md", ("恰好经过 72 小时", "暂不属于")),
    ("包裹一直没动静，要多久才会被认为不正常？", "logistics_exception.md", ("严格超过 72 小时",)),
    ("查询结果已经显示物流异常，还需要继续等三天吗？", "logistics_exception.md", ("明确显示为异常", "直接")),
    ("还在等待发货，超过三天没有更新会算异常吗？", "logistics_exception.md", ("等待发货", "严格超过 72 小时")),
]


def evaluation_exit_code(rows: list[dict]) -> int:
    """将任一 case-level FAIL 映射为 non-zero process exit。"""
    return 0 if all(row["result"] == "PASS" for row in rows) else 1


def main() -> int:
    documents = sorted(KNOWLEDGE_DIR.glob("*.md"))
    with tempfile.TemporaryDirectory() as persist_path:
        embedding = SentenceTransformerEmbeddingProvider(EMBEDDING_MODEL)
        store = ChromaVectorStore(persist_path, "business_knowledge_baseline")
        try:
            ingestor = KnowledgeIngestor(
                FixedSizeChunkingStrategy(CHUNK_SIZE, CHUNK_OVERLAP),
                embedding,
                store,
            )
            inserted = sum(ingestor.ingest(str(path)) for path in documents)
            retriever = VectorRetriever(embedding, store, TOP_K)
            rows = []
            for query, expected, required_terms in CASES:
                results = retriever.retrieve(query)
                sources = [Path(result.metadata["source"]).name for result in results]
                rank = next(
                    (index for index, source in enumerate(sources, 1) if source == expected),
                    None,
                )
                expected_chunks = [
                    result
                    for result, source in zip(results, sources)
                    if source == expected
                ]
                sufficient = all(
                    any(term in chunk.content for chunk in expected_chunks)
                    for term in required_terms
                )
                # Hard gate 同时要求 expected source 命中 Top-K 且 required evidence 完整。
                row = {
                    "query": query,
                    "expected": expected,
                    "top_1": sources[0] if sources else None,
                    "top_k": [
                        f"{source}#{result.metadata['chunk_index']}"
                        for source, result in zip(sources, results)
                    ],
                    "rank": rank,
                    "required_evidence_terms": required_terms,
                    "sufficient": sufficient,
                    "result": "PASS" if rank is not None and sufficient else "FAIL",
                    "chunks": [result.content for result in results],
                }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False))

            recalled = sum(row["rank"] is not None for row in rows)
            # Top-1 只诊断 ranking quality，不独立决定 case PASS/FAIL。
            top_1 = sum(row["top_1"] == row["expected"] for row in rows)
            sufficient = sum(row["sufficient"] for row in rows)
            passed = evaluation_exit_code(rows) == 0
            print(json.dumps({
                "scope": "positive_policy_retrieval",
                "embedding_model": EMBEDDING_MODEL,
                "documents": len(documents),
                "chunks": inserted,
                "cases": len(rows),
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "top_k": TOP_K,
                # Hit Rate@K 衡量source命中；evidence_sufficiency是项目自定义coverage。
                "expected_source_hit_rate_at_k": f"{recalled}/{len(rows)}",
                "top_1_source_accuracy": f"{top_1}/{len(rows)}",
                "evidence_sufficiency": f"{sufficient}/{len(rows)}",
                "all_cases_passed": passed,
                "limitations": [
                    "single labeled relevant source per case",
                    "positive retrieval only",
                    "embedding model revision is not repository-pinned",
                ],
            }, ensure_ascii=False))
            return evaluation_exit_code(rows)
        finally:
            # Windows 上未关闭的 Chroma handle 会阻塞临时目录清理，异常路径也必须释放。
            store.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
