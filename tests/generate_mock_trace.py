import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitoring.trace_recorder import AgentTraceRecorder
from monitoring.trace_store import TraceStore
from monitoring.visualizations import (
    create_agent_sankey,
    create_model_token_bar,
    create_source_hit_bar,
)


def generate(db_path: Path) -> str:
    store = TraceStore(db_path)
    recorder = AgentTraceRecorder(
        store,
        session_id="mock-session",
        user_query="2026世界杯决赛及主办城市经济影响",
    )
    run_id = recorder.start_run()

    planner = recorder.start_stage(
        "任务规划", "Planner Agent", "llm", "mock-planner", "模拟新闻需求"
    )
    recorder.record_agent_message(
        "User", "Planner Agent", "task_request", "分析世界杯新闻需求"
    )
    recorder.record_model_call(
        planner, "Planner Agent", "mock-planner", "chat", 100, 50, 150
    )
    recorder.complete_stage(planner, "完成新闻结构规划", 100, 50, 150)

    retriever = recorder.start_stage(
        "RAG 知识检索", "Retriever Agent", "retrieval", "mock-embedding", "决赛与城市经济"
    )
    recorder.record_agent_message(
        "Planner Agent", "Retriever Agent", "evidence_request", "检索赛事与经济证据"
    )
    recorder.record_model_call(
        retriever, "Retriever Agent", "mock-embedding", "embedding", 60, 0, 60
    )
    recorder.record_model_call(
        retriever, "Retriever Agent", "mock-reranker", "rerank", 80, 0, 80
    )
    recorder.record_retrieval(
        retriever,
        "2026世界杯决赛 城市经济",
        [{
            "document_id": f"doc-{index}",
            "document_title": f"2026世界杯资料 {index}",
            "source_name": "FIFA" if index <= 5 else "新华网",
            "source_type": "official" if index <= 5 else "news_agency",
            "source_url": f"https://example.com/doc-{index}",
            "published_at": "2026-07-20",
            "rank": index,
            "retrieval_score": 1 - index * 0.03,
            "rerank_score": 1 - index * 0.02,
            "used_in_answer": index <= 4,
            "chunk_preview": f"第 {index} 篇检索资料的安全摘要。",
        } for index in range(1, 11)],
    )
    recorder.complete_stage(retriever, "检索10篇资料")
    recorder.record_agent_message(
        "Retriever Agent", "Writer Agent", "evidence_response", "返回10篇资料"
    )

    writer = recorder.start_stage(
        "新闻撰写", "Writer Agent", "llm", "mock-writer", "使用4篇证据"
    )
    recorder.record_model_call(
        writer, "Writer Agent", "mock-writer", "chat", 200, 100, 300
    )
    recorder.complete_stage(writer, "生成420字符初稿", 200, 100, 300)
    recorder.record_agent_message(
        "Writer Agent", "Reviewer Agent", "review_request", "审校420字符初稿"
    )

    reviewer = recorder.start_stage(
        "事实审校", "Reviewer Agent", "llm", "mock-reviewer", "核查6项声明"
    )
    recorder.record_model_call(
        reviewer, "Reviewer Agent", "mock-reviewer", "chat", 180, 80, 260
    )
    recorder.complete_stage(
        reviewer,
        "5项有据，1项无据",
        180,
        80,
        260,
        {"total_claims": 6, "supported_claims": 5, "unsupported_claims": 1},
    )
    recorder.record_agent_message(
        "Reviewer Agent", "Image Agent", "image_request", "生成1张宣传图"
    )

    image = recorder.start_stage(
        "图片生成", "Image Agent", "image", "mock-image", "生成1张图片"
    )
    recorder.record_model_call(image, "Image Agent", "mock-image", "image")
    recorder.complete_stage(image, "成功生成1张图片")
    recorder.record_agent_message(
        "Image Agent", "Final Output", "final_result", "新闻与图片生成完成"
    )
    recorder.finish_run(
        article_character_count=410,
        generated_image_count=1,
        total_claims=6,
        supported_claims=5,
        unsupported_claims=1,
    )

    stages = store.get_run_stages(run_id)
    calls = store.get_run_model_calls(run_id)
    retrieval = store.get_run_retrieval_records(run_id)
    events = store.get_run_agent_events(run_id)
    assert len(stages) == 5
    assert len(retrieval) == 10
    assert len(events) == 6
    assert create_agent_sankey(events, stages) is not None
    assert create_model_token_bar(calls) is not None
    assert create_source_hit_bar(retrieval) is not None
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/agent_traces.db"),
    )
    args = parser.parse_args()
    mock_run_id = generate(args.db)
    print(f"MOCK_RUN_OK run_id={mock_run_id} db={args.db}")
