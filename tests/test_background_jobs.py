import time
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from background_jobs import (
    get_job,
    start_chat_job,
    start_image_job,
    start_midjourney_action_job,
    start_news_job,
)
from schemas import GeneratedImage, MidJourneyJob, UserInput


def wait_for(job_id):
    for _ in range(100):
        job = get_job(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("background job did not finish")


class BackgroundJobTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            api_key="secret",
            base_url="https://api.example.test/v1",
            request_timeout=30,
            chat_model="chat-model",
            image_model="image-model",
            image_provider="siliconflow",
            image_size="1024x1024",
            ttapi_image_api_key="ttapi-secret",
        )

    @patch("background_jobs.SiliconFlowClient.stream_chat")
    def test_chat_job_collects_stream(self, stream_chat):
        stream_chat.return_value = iter(["你", "好"])

        job = wait_for(
            start_chat_job(
                self.settings,
                [{"role": "user", "content": "你好"}],
            )
        )

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["output"], "你好")

    @patch("background_jobs.create_run_directory")
    @patch("background_jobs.SiliconFlowClient.download_image")
    @patch("background_jobs.SiliconFlowClient.generate_image")
    def test_image_job_generates_requested_count(
        self, generate_image, download_image, create_run_directory
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            create_run_directory.return_value = Path(temp_dir)
            generate_image.side_effect = [
                ("https://example.test/1.png", 1),
                ("https://example.test/2.png", 2),
            ]
            download_image.side_effect = lambda _, path: path.write_bytes(b"image")

            job = wait_for(start_image_job(self.settings, "生成两张梅西图片", 2))

            self.assertEqual(job["status"], "completed")
            self.assertEqual(len(job["result"]["images"]), 2)
            self.assertEqual(generate_image.call_count, 2)

    @patch("background_jobs.create_run_directory")
    @patch("background_jobs.SiliconFlowClient.download_image")
    @patch("background_jobs.SiliconFlowClient.generate_image")
    def test_image_job_recovers_from_none_count(
        self, generate_image, download_image, create_run_directory
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            create_run_directory.return_value = Path(temp_dir)
            generate_image.return_value = ("https://example.test/1.png", 1)
            download_image.side_effect = lambda _, path: path.write_bytes(b"image")

            job = wait_for(start_image_job(self.settings, "生成图片", None))

            self.assertEqual(job["status"], "completed")
            self.assertEqual(generate_image.call_count, 1)

    @patch("background_jobs.run_news_workflow")
    def test_news_job_keeps_result(self, workflow):
        workflow.return_value = {"missing_facts": [], "run_dir": ""}
        user_input = UserInput(
            "真实报道", "测试", "其他", "公众", "客观", "事实", "摄影", 1
        )

        job = wait_for(start_news_job(self.settings, user_input))

        self.assertEqual(job["status"], "completed")
        self.assertIs(job["result"]["user_input"], user_input)

    @patch("background_jobs.SiliconFlowClient.analyze_image")
    @patch("background_jobs.run_news_workflow")
    def test_reference_image_analysis_is_not_added_as_news_fact(
        self, workflow, analyze_image
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "result.json").write_text(
                json.dumps({"images": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            workflow.return_value = {
                "missing_facts": [],
                "run_dir": str(run_dir),
                "images": [],
            }
            analyze_image.return_value = "一名球员在球场庆祝"
            buffer = BytesIO()
            Image.new("RGB", (320, 180), "#0f6b4f").save(buffer, format="JPEG")
            user_input = UserInput(
                "真实报道",
                "测试",
                "其他",
                "公众",
                "客观",
                "已核实事实",
                "摄影",
                1,
                image_usage="图片作为MidJourney参考图",
                midjourney_reference_url="https://example.test/reference.jpg",
                include_uploaded_image=True,
            )

            job = wait_for(
                start_news_job(
                    self.settings,
                    user_input,
                    image={
                        "bytes": buffer.getvalue(),
                        "name": "image.jpg",
                        "type": "image/jpeg",
                    },
                )
            )

            self.assertEqual(job["status"], "completed")
            self.assertEqual(
                user_input.midjourney_reference_description,
                "一名球员在球场庆祝",
            )
            self.assertNotIn("上传图片分析结果", user_input.factual_material)
            self.assertEqual(job["result"]["images"][0]["kind"], "source")
            self.assertTrue((run_dir / "source_image_1.png").is_file())

    @patch("background_jobs.SiliconFlowClient.analyze_image")
    @patch("background_jobs.run_news_workflow")
    def test_combined_image_is_saved_and_used_for_prompt_analysis(
        self, workflow, analyze_image
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "result.json").write_text(
                json.dumps({"images": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            workflow.return_value = {
                "missing_facts": [],
                "run_dir": str(run_dir),
                "images": [],
            }
            analyze_image.return_value = "一名球员在球场庆祝"
            buffer = BytesIO()
            Image.new("RGB", (320, 180), "#0f6b4f").save(buffer, format="JPEG")
            user_input = UserInput(
                "真实报道",
                "测试",
                "其他",
                "公众",
                "客观",
                "已核实事实",
                "摄影",
                1,
                image_usage="同时作为新闻资料和MidJourney参考图",
                midjourney_reference_url="https://example.test/reference.jpg",
                source_image_credit="测试摄影者",
            )

            job = wait_for(
                start_news_job(
                    self.settings,
                    user_input,
                    image={
                        "bytes": buffer.getvalue(),
                        "name": "image.jpg",
                        "type": "image/jpeg",
                    },
                )
            )

            self.assertEqual(job["status"], "completed")
            self.assertEqual(user_input.midjourney_reference_description, "一名球员在球场庆祝")
            self.assertIn("上传图片分析结果", user_input.factual_material)
            self.assertEqual(job["result"]["images"][0]["kind"], "source")
            self.assertTrue((run_dir / "source_image_1.png").is_file())

    @patch("background_jobs.persist_midjourney_state")
    @patch("background_jobs.run_midjourney_action")
    def test_midjourney_action_replaces_job_candidates(self, run_action, persist):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = {
                "run_dir": temp_dir,
                "images": [
                    {
                        "name": "grid",
                        "prompt": "prompt",
                        "negative_prompt": "text",
                        "source_url": "",
                        "local_path": "grid.png",
                        "provider_job_id": "job-1",
                    }
                ],
                "midjourney_jobs": [
                    {
                        "job_id": "job-1",
                        "prompt": "prompt",
                        "actions": [{"label": "U1", "action_id": "u1"}],
                    }
                ],
            }
            run_action.return_value = (
                MidJourneyJob(
                    job_id="job-2",
                    prompt="prompt",
                    status="SUCCESS",
                    requested_action="U1",
                    final_image_url="https://example.test/final.png",
                    final_image_local_path=str(Path(temp_dir) / "final.png"),
                ),
                [
                    GeneratedImage(
                        "final",
                        "prompt",
                        "text",
                        "https://example.test/final.png",
                        str(Path(temp_dir) / "final.png"),
                        provider_job_id="job-2",
                    )
                ],
            )

            job = wait_for(start_midjourney_action_job(self.settings, result, 0, "U1"))

            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["result"]["midjourney_jobs"][0]["job_id"], "job-2")
            self.assertEqual(len(job["result"]["images"]), 1)
            persist.assert_called_once()


if __name__ == "__main__":
    unittest.main()
