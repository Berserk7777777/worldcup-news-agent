import dataclasses
import time
from pathlib import Path
from typing import Callable

from config import Settings
from knowledge_base import format_retrieval_context, retrieve_for_topic
from midjourney_service import create_midjourney_candidates
from monitoring import AgentTraceRecorder, DEFAULT_TRACE_STORE
from monitoring.sanitization import safe_summary
from prompts import build_planner_prompt, build_reviewer_prompt, build_writer_prompt
from schemas import GeneratedImage, MidJourneyJob, StageTrace, StageUsage, UserInput
from siliconflow_client import ConfigurationError, SiliconFlowClient
from utils import (
    count_non_whitespace_characters,
    create_run_directory,
    sanitize_error_message,
    save_creation_report_md,
    save_final_article_txt,
    save_run_results,
    validate_required_keys,
)


PLANNER_KEYS = [
    "can_proceed", "reason", "news_angle", "core_message", "title_direction",
    "outline", "fact_inventory", "missing_critical_facts", "risk_warnings",
    "image_concepts",
]
WRITER_KEYS = [
    "article_label", "title", "lead", "body_paragraphs", "ending",
    "full_article", "image_prompts", "fact_usage_map",
]
REVIEWER_KEYS = [
    "passed", "final_article_label", "unsupported_claims", "factual_conflicts",
    "style_issues", "length_issues", "revisions", "final_title",
    "final_article", "final_image_prompts", "review_summary",
]


def continue_with_user_material(user_input: UserInput, planner_result: dict) -> bool:
    """Convert an evidence-gap rejection into a clearly attributed draft plan."""
    if planner_result.get("can_proceed", False):
        return True
    if not user_input.topic.strip() or not user_input.factual_material.strip():
        return False

    original_reason = planner_result.get("reason", "缺少独立核实来源")
    warnings = list(planner_result.get("risk_warnings") or [])
    warning = (
        "核心故事来自用户提供的材料，尚未获得独立来源核实；成稿必须使用"
        "归因表达并标注为待核实稿。"
    )
    if warning not in warnings:
        warnings.append(warning)
    planner_result.update(
        {
            "can_proceed": True,
            "reason": "基于用户提供的故事线继续生成待核实稿",
            "original_stop_reason": original_reason,
            "verification_status": "user_material_unverified",
            "risk_warnings": warnings,
        }
    )
    return True


def ensure_image_prompts(
    user_input: UserInput,
    reviewer_result: dict,
    writer_result: dict,
) -> list[dict]:
    count = user_input.image_count if user_input.image_count in {1, 2} else 1
    candidates = (
        reviewer_result.get("final_image_prompts")
        or writer_result.get("image_prompts")
        or []
    )
    prompts = [
        {
            "name": item.get("name") or f"新闻配图{index + 1}",
            "prompt": str(item.get("prompt") or "").strip(),
            "negative_prompt": str(item.get("negative_prompt") or "").strip(),
        }
        for index, item in enumerate(candidates)
        if isinstance(item, dict) and str(item.get("prompt") or "").strip()
    ]
    while len(prompts) < count:
        index = len(prompts) + 1
        composition = "横版新闻主图" if index == 1 else "不同视角的辅助配图"
        prompts.append(
            {
                "name": "新闻主图" if index == 1 else f"辅助配图{index}",
                "prompt": (
                    f"{user_input.topic}，{user_input.image_style}，{composition}，"
                    "主体清晰，环境完整，纪实光线，高细节，不出现可读文字"
                ),
                "negative_prompt": (
                    "低清晰度，模糊，畸形手指，多余肢体，错误文字，乱码，"
                    "水印，品牌Logo，官方赛事Logo"
                ),
            }
        )
    return prompts[:count]


def _notify(callback, stage: str, message: str, status: str) -> None:
    if callback:
        callback(stage, message, status)


def _metrics(trace: list[StageTrace], started: float, draft: int = 0, final: int = 0) -> dict:
    return {
        "draft_character_count": draft,
        "final_character_count": final,
        "total_prompt_tokens": sum(item.usage.prompt_tokens for item in trace),
        "total_completion_tokens": sum(item.usage.completion_tokens for item in trace),
        "total_tokens": sum(item.usage.total_tokens for item in trace),
        "total_elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def _failed_result(
    stage: str,
    error: Exception,
    settings: Settings,
    started: float,
    trace: list[StageTrace],
    planner_result: dict,
    writer_result: dict,
    reviewer_result: dict,
    prompts_used: dict,
    draft_count: int = 0,
    final_count: int = 0,
    monitor_run_id: str = "",
) -> dict:
    return {
        "stopped_at": stage,
        "stop_reason": sanitize_error_message(error, settings.api_key),
        "planner_result": planner_result,
        "writer_result": writer_result,
        "reviewer_result": reviewer_result,
        "trace": trace,
        "images": [],
        "metrics": _metrics(trace, started, draft_count, final_count),
        "run_dir": "",
        "prompts_used": prompts_used,
        "monitor_run_id": monitor_run_id,
    }


def _fail_monitoring_run(
    recorder: AgentTraceRecorder, stage_name: str, error: Exception
) -> None:
    try:
        recorder.fail_run(stage_name, error)
    except Exception as recorded_error:
        if recorded_error is not error:
            raise


def _append_source_list(article: str, sources: list[dict]) -> str:
    if not sources:
        return article
    rows = ["来源："]
    for index, source in enumerate(sources, 1):
        rows.append(
            f"[{index}] {source['source_name']}，《{source['document_title']}》，"
            f"{source.get('published_at') or '未标注日期'}，{source['source_url']}"
        )
    return f"{article.rstrip()}\n\n" + "\n".join(rows)


def run_news_workflow(
    user_input: UserInput,
    settings: Settings,
    progress_callback: Callable | None = None,
) -> dict:
    recorder = AgentTraceRecorder(
        DEFAULT_TRACE_STORE,
        session_id="streamlit-local",
        user_query=f"{user_input.topic}；{user_input.factual_material}",
        task_type=user_input.news_type,
    )
    monitor_run_id = recorder.start_run()

    if settings.writer_model == settings.reviewer_model:
        error = ConfigurationError("WRITER_MODEL与REVIEWER_MODEL必须不同")
        recorder.fail_run("配置检查", error)

    started = time.perf_counter()
    try:
        client = SiliconFlowClient(settings)
    except Exception as error:
        recorder.fail_run("配置检查", error)
    trace: list[StageTrace] = []
    planner_result: dict = {}
    writer_result: dict = {}
    reviewer_result: dict = {}
    prompts_used: dict = {}
    retrieved_sources: list[dict] = []
    provided_factual_material = user_input.factual_material

    stage_started = time.perf_counter()
    retrieval_stage_id = recorder.start_stage(
        "知识检索",
        "Retrieval Agent",
        "retrieval",
        settings.embedding_model,
        safe_summary(user_input.topic, 150),
    )
    recorder.record_agent_message(
        "User",
        "Retrieval Agent",
        "evidence_request",
        safe_summary(user_input.topic, 150),
    )
    _notify(progress_callback, "知识检索", "正在检索世界杯知识库", "running")
    try:
        retrieved_sources, refreshed = retrieve_for_topic(
            user_input.topic,
            settings,
            progress_callback=progress_callback,
        )
        evidence = format_retrieval_context(retrieved_sources)
        if evidence:
            user_input.factual_material = (
                f"{user_input.factual_material}\n\n{evidence}".strip()
            )
        recorder.record_retrieval(
            retrieval_stage_id, user_input.topic, retrieved_sources
        )
        recorder.complete_stage(
            retrieval_stage_id,
            f"检索到{len(retrieved_sources)}条证据"
            + ("，并完成实时刷新" if refreshed else ""),
            metadata={
                "retrieved": len(retrieved_sources),
                "realtime_refreshed": refreshed,
            },
        )
        recorder.record_agent_message(
            "Retrieval Agent",
            "Planner Agent",
            "evidence_response",
            f"返回{len(retrieved_sources)}条白名单证据",
        )
        trace.append(
            StageTrace(
                "知识检索",
                settings.embedding_model,
                "关键词、语义、来源等级和发布日期混合检索",
                round(time.perf_counter() - stage_started, 2),
                StageUsage(),
                "completed",
                f"检索到{len(retrieved_sources)}条证据",
            )
        )
        _notify(
            progress_callback,
            "知识检索",
            f"知识检索完成，共{len(retrieved_sources)}条证据",
            "completed",
        )
    except Exception as error:
        recorder.fail_stage(retrieval_stage_id, error)
        trace.append(
            StageTrace(
                "知识检索",
                settings.embedding_model,
                "关键词、语义、来源等级和发布日期混合检索",
                round(time.perf_counter() - stage_started, 2),
                StageUsage(),
                "failed",
                "知识检索失败，继续使用用户材料",
            )
        )
        _notify(
            progress_callback,
            "知识检索",
            "知识检索失败，继续使用用户提供的材料",
            "failed",
        )

    stage_started = time.perf_counter()
    system_p, user_p = build_planner_prompt(user_input)
    prompts_used.update(planner_system=system_p, planner_user=user_p)
    planner_stage_id = recorder.start_stage(
        "任务规划",
        "Planner Agent",
        "llm",
        settings.planner_model,
        safe_summary(user_input.topic, 150),
    )
    recorder.record_agent_message(
        "User", "Planner Agent", "task_request", safe_summary(user_input.topic, 150)
    )
    _notify(progress_callback, "新闻策划", "正在分析新闻选题和事实材料", "running")
    planner_call_started = time.perf_counter()
    try:
        planner_result, usage1 = client.call_json_model(
            settings.planner_model, system_p, user_p, temperature=0.2, max_tokens=1800
        )
        validate_required_keys(planner_result, PLANNER_KEYS, "新闻策划")
    except Exception as error:
        recorder.record_model_call(
            planner_stage_id,
            "Planner Agent",
            settings.planner_model,
            "chat",
            status="failed",
            error=error,
            elapsed_seconds=time.perf_counter() - planner_call_started,
        )
        recorder.fail_stage(planner_stage_id, error)
        _fail_monitoring_run(recorder, "任务规划", error)
        trace.append(StageTrace(
            "新闻策划", settings.planner_model, "分析新闻选题、整理事实并制定文章结构",
            round(time.perf_counter() - stage_started, 2), StageUsage(), "failed",
            "新闻策划失败",
        ))
        _notify(progress_callback, "新闻策划", "新闻策划失败", "failed")
        return _failed_result(
            "planner", error, settings, started, trace, planner_result, {}, {},
            prompts_used, monitor_run_id=monitor_run_id
        )
    recorder.record_model_call(
        planner_stage_id,
        "Planner Agent",
        settings.planner_model,
        "chat",
        usage1.prompt_tokens,
        usage1.completion_tokens,
        usage1.total_tokens,
        elapsed_seconds=time.perf_counter() - planner_call_started,
    )
    recorder.complete_stage(
        planner_stage_id,
        "完成新闻角度与结构规划",
        usage1.prompt_tokens,
        usage1.completion_tokens,
        usage1.total_tokens,
    )
    trace.append(StageTrace(
        "新闻策划", settings.planner_model, "分析新闻选题、整理事实并制定文章结构",
        round(time.perf_counter() - stage_started, 2), usage1, "completed",
        "完成新闻角度与四段式结构规划",
    ))
    _notify(progress_callback, "新闻策划", "新闻策划完成", "completed")

    if not continue_with_user_material(user_input, planner_result):
        recorder.record_agent_message(
            "Planner Agent",
            "Final Output",
            "final_result",
            safe_summary(planner_result.get("reason", "事实材料不足"), 300),
        )
        recorder.finish_run()
        return {
            "stopped_at": "planner",
            "stop_reason": planner_result.get("reason", "事实材料不足"),
            "missing_facts": planner_result.get("missing_critical_facts", []),
            "planner_result": planner_result,
            "writer_result": {},
            "reviewer_result": {},
            "trace": trace,
            "images": [],
            "metrics": _metrics(trace, started),
            "run_dir": "",
            "prompts_used": prompts_used,
            "monitor_run_id": monitor_run_id,
            "sources": retrieved_sources,
        }
    if planner_result.get("verification_status") == "user_material_unverified":
        user_input.factual_material = provided_factual_material
        retrieved_sources = []
        planner_result["fact_inventory"] = [
            {
                "fact": user_input.topic,
                "source": "用户提供的事实材料（待核实）",
            }
        ]
        _notify(
            progress_callback,
            "新闻策划",
            "外部证据不足，将基于用户材料生成明确标注的待核实稿",
            "completed",
        )
        recorder.record_agent_message(
            "Planner Agent",
            "Writer Agent",
            "verification_warning",
            "基于用户材料继续写作，成稿须标注待核实状态",
        )

    stage_started = time.perf_counter()
    system_w, user_w = build_writer_prompt(user_input, planner_result)
    prompts_used.update(writer_system=system_w, writer_user=user_w)
    writer_stage_id = recorder.start_stage(
        "新闻撰写",
        "Writer Agent",
        "llm",
        settings.writer_model,
        safe_summary(planner_result.get("core_message", ""), 150),
    )
    recorder.record_agent_message(
        "Planner Agent",
        "Writer Agent",
        "draft_handoff",
        safe_summary(planner_result.get("core_message", "新闻写作计划已完成"), 300),
    )
    _notify(progress_callback, "新闻生成", "正在撰写新闻稿和图片提示词", "running")
    writer_call_started = time.perf_counter()
    try:
        writer_result, usage2 = client.call_json_model(
            settings.writer_model, system_w, user_w, temperature=0.65, max_tokens=2500
        )
        validate_required_keys(writer_result, WRITER_KEYS, "新闻生成")
    except Exception as error:
        recorder.record_model_call(
            writer_stage_id,
            "Writer Agent",
            settings.writer_model,
            "chat",
            status="failed",
            error=error,
            elapsed_seconds=time.perf_counter() - writer_call_started,
        )
        recorder.fail_stage(writer_stage_id, error)
        _fail_monitoring_run(recorder, "新闻撰写", error)
        trace.append(StageTrace(
            "新闻生成", settings.writer_model, "生成新闻标题、初稿和图片提示词",
            round(time.perf_counter() - stage_started, 2), StageUsage(), "failed",
            "新闻初稿生成失败",
        ))
        _notify(progress_callback, "新闻生成", "新闻初稿生成失败", "failed")
        return _failed_result(
            "writer", error, settings, started, trace, planner_result, writer_result,
            {}, prompts_used, monitor_run_id=monitor_run_id,
        )
    draft_count = count_non_whitespace_characters(writer_result.get("full_article", ""))
    recorder.record_model_call(
        writer_stage_id,
        "Writer Agent",
        settings.writer_model,
        "chat",
        usage2.prompt_tokens,
        usage2.completion_tokens,
        usage2.total_tokens,
        elapsed_seconds=time.perf_counter() - writer_call_started,
    )
    recorder.complete_stage(
        writer_stage_id,
        f"生成{draft_count}字符初稿",
        usage2.prompt_tokens,
        usage2.completion_tokens,
        usage2.total_tokens,
        {"evidence_count": len(writer_result.get("fact_usage_map", []))},
    )
    trace.append(StageTrace(
        "新闻生成", settings.writer_model, "生成新闻标题、初稿和图片提示词",
        round(time.perf_counter() - stage_started, 2), usage2, "completed",
        f"生成标题、{draft_count}字符初稿和{len(writer_result.get('image_prompts', []))}条图片提示词",
    ))
    _notify(progress_callback, "新闻生成", "新闻初稿完成", "completed")

    stage_started = time.perf_counter()
    system_r, user_r = build_reviewer_prompt(user_input, planner_result, writer_result)
    prompts_used.update(reviewer_system=system_r, reviewer_user=user_r)
    reviewer_stage_id = recorder.start_stage(
        "事实审校",
        "Reviewer Agent",
        "llm",
        settings.reviewer_model,
        f"初稿字符数：{draft_count}",
    )
    recorder.record_agent_message(
        "Writer Agent",
        "Reviewer Agent",
        "review_request",
        f"请审校{draft_count}字符新闻初稿",
    )
    _notify(progress_callback, "独立审校", "正在进行独立事实审校", "running")
    reviewer_call_started = time.perf_counter()
    try:
        reviewer_result, usage3 = client.call_json_model(
            settings.reviewer_model, system_r, user_r, temperature=0.1, max_tokens=2600
        )
        validate_required_keys(reviewer_result, REVIEWER_KEYS, "独立审校")
    except Exception as error:
        recorder.record_model_call(
            reviewer_stage_id,
            "Reviewer Agent",
            settings.reviewer_model,
            "chat",
            status="failed",
            error=error,
            elapsed_seconds=time.perf_counter() - reviewer_call_started,
        )
        recorder.fail_stage(reviewer_stage_id, error)
        _fail_monitoring_run(recorder, "事实审校", error)
        trace.append(StageTrace(
            "独立审校", settings.reviewer_model, "核查事实风险、修正语言并生成最终稿",
            round(time.perf_counter() - stage_started, 2), StageUsage(), "failed",
            "新闻审校失败",
        ))
        _notify(progress_callback, "独立审校", "新闻审校失败", "failed")
        return _failed_result(
            "reviewer", error, settings, started, trace, planner_result, writer_result,
            reviewer_result, prompts_used, draft_count,
            monitor_run_id=monitor_run_id,
        )
    final_count = count_non_whitespace_characters(reviewer_result.get("final_article", ""))
    reviewer_result["final_article"] = _append_source_list(
        reviewer_result.get("final_article", ""), retrieved_sources
    )
    unsupported_count = len(reviewer_result.get("unsupported_claims", []))
    claim_count = len(writer_result.get("fact_usage_map", []))
    supported_count = max(0, claim_count - unsupported_count)
    recorder.record_model_call(
        reviewer_stage_id,
        "Reviewer Agent",
        settings.reviewer_model,
        "chat",
        usage3.prompt_tokens,
        usage3.completion_tokens,
        usage3.total_tokens,
        elapsed_seconds=time.perf_counter() - reviewer_call_started,
    )
    recorder.complete_stage(
        reviewer_stage_id,
        f"完成{len(reviewer_result.get('revisions', []))}项修订",
        usage3.prompt_tokens,
        usage3.completion_tokens,
        usage3.total_tokens,
        {
            "total_claims": claim_count,
            "supported_claims": supported_count,
            "unsupported_claims": unsupported_count,
        },
    )
    recorder.record_agent_message(
        "Reviewer Agent",
        "Image Agent",
        "image_request",
        f"生成{user_input.image_count}张新闻宣传图",
    )
    trace.append(StageTrace(
        "独立审校", settings.reviewer_model, "核查事实风险、修正语言并生成最终稿",
        round(time.perf_counter() - stage_started, 2), usage3, "completed",
        f"完成{len(reviewer_result.get('revisions', []))}项修订，最终正文{final_count}字符",
    ))
    _notify(progress_callback, "独立审校", "新闻审校完成", "completed")

    _notify(progress_callback, "图片生成", "正在生成新闻宣传图片", "running")
    stage_started = time.perf_counter()
    image_stage_id = recorder.start_stage(
        "图片生成",
        "Image Agent",
        "image",
        settings.image_backend_label,
        f"请求生成{user_input.image_count}张图片",
    )
    images: list[GeneratedImage] = []
    midjourney_jobs: list[MidJourneyJob] = []
    try:
        run_dir = create_run_directory(Path("outputs"))
    except OSError as error:
        recorder.fail_stage(image_stage_id, error)
        _fail_monitoring_run(recorder, "图片生成", error)
        trace.append(StageTrace(
            "图片生成", settings.image_backend_label, "根据终审后的图片提示词生成新闻宣传图",
            round(time.perf_counter() - stage_started, 2), StageUsage(), "failed",
            "无法创建本地输出目录",
        ))
        _notify(progress_callback, "图片生成", "本地输出目录创建失败", "failed")
        return _failed_result(
            "image", error, settings, started, trace, planner_result, writer_result,
            reviewer_result, prompts_used, draft_count, final_count,
            monitor_run_id=monitor_run_id,
        )

    image_prompts = ensure_image_prompts(user_input, reviewer_result, writer_result)
    attempted_requests = min(user_input.image_count, len(image_prompts))
    successful_requests = 0
    for index, item in enumerate(image_prompts[: user_input.image_count]):
        name = item.get("name", f"图片{index + 1}")
        prompt = item.get("prompt", "")
        negative_prompt = item.get("negative_prompt", "")
        image_call_started = time.perf_counter()
        try:
            if settings.image_provider == "ttapi":
                job, generated = create_midjourney_candidates(
                    settings,
                    prompt,
                    negative_prompt,
                    run_dir,
                    f"midjourney_{index + 1}",
                    progress_callback,
                    user_input.midjourney_reference_url,
                    user_input.midjourney_reference_description,
                    user_input.midjourney_image_weight,
                )
                midjourney_jobs.append(job)
                images.extend(generated)
            else:
                url, seed = client.generate_image(
                    settings.image_model, prompt, negative_prompt, settings.image_size
                )
                image_path = run_dir / f"image_{index + 1}.png"
                client.download_image(url, image_path)
                images.append(GeneratedImage(
                    name, prompt, negative_prompt, url, str(image_path), seed, ""
                ))
            successful_requests += 1
            recorder.record_model_call(
                image_stage_id,
                "Image Agent",
                settings.image_backend_label,
                "image",
                elapsed_seconds=time.perf_counter() - image_call_started,
            )
        except Exception as error:
            images.append(GeneratedImage(
                name, prompt, negative_prompt, "", "", None,
                sanitize_error_message(error, settings.api_key),
            ))
            recorder.record_model_call(
                image_stage_id,
                "Image Agent",
                settings.image_backend_label,
                "image",
                status="failed",
                error=error,
                elapsed_seconds=time.perf_counter() - image_call_started,
            )

    success_count = successful_requests
    image_status = "completed" if success_count else "failed"
    if success_count:
        recorder.complete_stage(
            image_stage_id,
            f"成功生成{success_count}张宣传图片",
            metadata={
                "requested": user_input.image_count,
                "succeeded": success_count,
                "failed": attempted_requests - success_count,
            },
        )
    else:
        image_error = RuntimeError("图片生成失败")
        recorder.fail_stage(image_stage_id, image_error)
    trace.append(StageTrace(
        "图片生成", settings.image_backend_label, "根据终审后的图片提示词生成新闻宣传图",
        round(time.perf_counter() - stage_started, 2), StageUsage(), image_status,
        f"成功生成{success_count}张宣传图片",
    ))
    _notify(
        progress_callback,
        "图片生成",
        f"宣传图片生成完成（成功{success_count}张）" if success_count else "宣传图片生成失败",
        image_status,
    )

    metrics = _metrics(trace, started, draft_count, final_count)
    try:
        save_run_results(
            run_dir, user_input, settings, planner_result, writer_result, reviewer_result,
            trace, images, metrics, retrieved_sources, midjourney_jobs,
        )
        save_final_article_txt(run_dir, reviewer_result)
        save_creation_report_md(
            run_dir, user_input, settings, planner_result, writer_result, reviewer_result,
            trace, images, metrics,
        )
    except OSError as error:
        _fail_monitoring_run(recorder, "结果保存", error)
        return {
            **_failed_result(
                "save", error, settings, started, trace, planner_result, writer_result,
                reviewer_result, prompts_used, draft_count, final_count,
                monitor_run_id=monitor_run_id,
            ),
            "images": images,
            "run_dir": str(run_dir),
        }

    if success_count:
        recorder.record_agent_message(
            "Image Agent",
            "Final Output",
            "final_result",
            f"新闻终稿{final_count}字符，成功生成{success_count}张图片",
        )
        recorder.finish_run(
            article_character_count=final_count,
            generated_image_count=success_count,
            total_claims=claim_count,
            supported_claims=supported_count,
            unsupported_claims=unsupported_count,
        )
    else:
        _fail_monitoring_run(recorder, "图片生成", RuntimeError("图片生成失败"))

    return {
        "stopped_at": None if success_count else "image",
        "stop_reason": "" if success_count else "图片生成失败，已保留文字内容和图片提示词",
        "planner_result": planner_result,
        "writer_result": writer_result,
        "reviewer_result": reviewer_result,
        "trace": trace,
        "images": images,
        "metrics": metrics,
        "run_dir": str(run_dir),
        "prompts_used": prompts_used,
        "monitor_run_id": monitor_run_id,
        "sources": retrieved_sources,
        "midjourney_jobs": [dataclasses.asdict(item) for item in midjourney_jobs],
    }
