import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from schemas import GeneratedImage, MidJourneyJob, StageUsage, UserInput
from workflow import ensure_image_prompts, run_news_workflow


class WorkflowFallbackTests(unittest.TestCase):
    def test_missing_model_image_prompt_gets_topic_fallback(self):
        user_input = UserInput(
            "真实报道",
            "根据用户照片故事生成梅西与亚马尔主题新闻配图",
            "人物特写",
            "普通读者",
            "正式体育新闻",
            "用户提供的故事材料",
            "体育新闻摄影",
            1,
        )

        prompts = ensure_image_prompts(user_input, {}, {})

        self.assertEqual(len(prompts), 1)
        self.assertIn("梅西与亚马尔", prompts[0]["prompt"])
        self.assertIn("体育新闻摄影", prompts[0]["prompt"])

    @patch("workflow.save_creation_report_md")
    @patch("workflow.save_final_article_txt")
    @patch("workflow.save_run_results")
    @patch("workflow.create_midjourney_candidates")
    @patch("workflow.create_run_directory")
    @patch("workflow.retrieve_for_topic")
    @patch("workflow.AgentTraceRecorder")
    @patch("workflow.SiliconFlowClient")
    def test_planner_evidence_rejection_still_writes_and_generates_image(
        self,
        client_class,
        recorder_class,
        retrieve,
        create_run_directory,
        create_midjourney,
        save_results,
        save_article,
        save_report,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            create_run_directory.return_value = run_dir
            retrieve.return_value = ([], False)

            recorder = MagicMock()
            recorder.start_run.return_value = "run-1"
            recorder.start_stage.side_effect = [
                "retrieval",
                "planner",
                "writer",
                "reviewer",
                "image",
            ]
            recorder_class.return_value = recorder

            planner = {
                "can_proceed": False,
                "reason": "没有独立来源",
                "news_angle": "跨越时间的足球影像故事",
                "core_message": "用户提供的照片故事",
                "title_direction": "梅西与亚马尔的影像联系",
                "outline": [],
                "fact_inventory": [],
                "missing_critical_facts": ["独立来源"],
                "risk_warnings": [],
                "image_concepts": [],
            }
            writer = {
                "article_label": "待核实稿",
                "title": "一张旧照串联两代球员",
                "lead": "用户提供的资料呈现了一段跨越时间的足球影像故事。",
                "body_paragraphs": ["正文第一段。", "正文第二段。"],
                "ending": "相关细节仍待独立核实。",
                "full_article": "用户提供的资料呈现了一段跨越时间的足球影像故事。",
                "image_prompts": [
                    {
                        "name": "新闻主图",
                        "prompt": "两代足球人物的纪实感画面",
                        "negative_prompt": "文字，水印",
                    }
                ],
                "fact_usage_map": [],
            }
            reviewer = {
                "passed": True,
                "final_article_label": "待核实稿",
                "unsupported_claims": [],
                "factual_conflicts": [],
                "style_issues": [],
                "length_issues": [],
                "revisions": [],
                "final_title": "一张旧照串联两代球员",
                "final_article": "用户提供的资料呈现了一段跨越时间的足球影像故事。",
                "final_image_prompts": [
                    {
                        "name": "新闻主图",
                        "prompt": "两代足球人物的纪实感画面",
                        "negative_prompt": "文字，水印",
                    }
                ],
                "review_summary": "已保留归因和待核实标识。",
            }
            client = client_class.return_value
            client.call_json_model.side_effect = [
                (planner, StageUsage()),
                (writer, StageUsage()),
                (reviewer, StageUsage()),
            ]

            generated = GeneratedImage(
                "MidJourney 最终图片",
                "两代足球人物的纪实感画面",
                "文字，水印",
                "https://example.test/image.png",
                str(run_dir / "image.png"),
            )
            create_midjourney.return_value = (
                MidJourneyJob("mj-1", "prompt", status="SUCCESS"),
                [generated],
            )
            settings = SimpleNamespace(
                api_key="secret",
                planner_model="planner-model",
                writer_model="writer-model",
                reviewer_model="reviewer-model",
                embedding_model="embedding-model",
                image_provider="ttapi",
                image_backend_label="MidJourney via TTAPI",
                image_size="1024x1024",
            )
            user_input = UserInput(
                "真实报道",
                "围绕用户提供的照片故事撰写新闻并生成配图",
                "人物特写",
                "普通读者",
                "正式体育新闻",
                "用户提供的资料称，这张照片记录了两代球员之间的故事。",
                "体育新闻摄影",
                1,
            )

            result = run_news_workflow(user_input, settings)

            self.assertEqual(client.call_json_model.call_count, 3)
            create_midjourney.assert_called_once()
            self.assertEqual(result["reviewer_result"]["final_article_label"], "待核实稿")
            self.assertEqual(len(result["images"]), 1)
            self.assertEqual(result["stop_reason"], "")
            save_results.assert_called_once()
            save_article.assert_called_once()
            save_report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
