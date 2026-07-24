from dataclasses import dataclass


@dataclass
class RunRecord:
    run_id: str = ""
    session_id: str | None = None
    user_query: str = ""
    task_type: str = ""
    started_at: str = ""
    ended_at: str | None = None
    status: str = "running"
    total_elapsed_seconds: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    llm_call_count: int = 0
    embedding_call_count: int = 0
    rerank_call_count: int = 0
    image_call_count: int = 0
    retrieved_documents: int = 0
    used_documents: int = 0
    total_claims: int = 0
    supported_claims: int = 0
    unsupported_claims: int = 0
    evidence_coverage: float | None = None
    article_character_count: int | None = None
    generated_image_count: int = 0
    error_stage: str | None = None
    error_message: str | None = None


@dataclass
class StageRecord:
    id: int = 0
    run_id: str = ""
    sequence: int = 0
    stage_name: str = ""
    agent_name: str = ""
    operation_type: str = ""
    model_name: str | None = None
    status: str = "pending"
    started_at: str = ""
    ended_at: str | None = None
    elapsed_seconds: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_summary: str = ""
    output_summary: str = ""
    error_message: str | None = None
    metadata_json: str | None = None


@dataclass
class ModelCallRecord:
    id: int = 0
    run_id: str = ""
    stage_id: int | None = None
    agent_name: str = ""
    model_name: str = ""
    call_type: str = ""
    started_at: str = ""
    ended_at: str | None = None
    elapsed_seconds: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    status: str = "running"
    error_message: str | None = None
    metadata_json: str | None = None


@dataclass
class RetrievalRecord:
    id: int = 0
    run_id: str = ""
    stage_id: int | None = None
    query: str = ""
    document_id: str | None = None
    document_title: str = ""
    source_name: str = ""
    source_type: str | None = None
    source_url: str = ""
    published_at: str | None = None
    rank: int | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None
    used_in_answer: int = 0
    chunk_preview: str = ""
    metadata_json: str | None = None


@dataclass
class AgentEvent:
    id: int = 0
    run_id: str = ""
    sequence: int = 0
    from_agent: str = ""
    to_agent: str = ""
    event_type: str = ""
    content_summary: str = ""
    created_at: str = ""
    metadata_json: str | None = None


@dataclass
class StageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    elapsed_seconds: float = 0.0
