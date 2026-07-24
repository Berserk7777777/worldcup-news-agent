import unittest
from unittest.mock import patch

from config import Settings
from midjourney_service import build_midjourney_prompt, validate_reference_image_url
from ttapi_client import TTAPIError, TTAPIMidJourneyClient


class TTAPIClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(ttapi_image_api_key="test-key")

    def test_create_response_extracts_job_id(self):
        payload = {"status": "SUCCESS", "data": {"jobId": "job-001"}}

        job = TTAPIMidJourneyClient.to_job(payload, "prompt")

        self.assertEqual(job.job_id, "job-001")
        self.assertEqual(job.status, "SUCCESS")

    def test_fetch_response_extracts_grid_and_actions(self):
        payload = {
            "status": "SUCCESS",
            "data": {
                "jobId": "job-001",
                "imageUrl": "https://example.test/grid.png",
                "buttons": [
                    {"label": "U1", "customId": "action-u1"},
                    {"label": "V1", "customId": "action-v1"},
                ],
            },
        }

        job = TTAPIMidJourneyClient.to_job(payload, "prompt")

        self.assertEqual(job.grid_url, "https://example.test/grid.png")
        self.assertEqual(job.actions[0].label, "U1")
        self.assertEqual(job.actions[0].action_id, "action-u1")

    def test_action_label_can_be_inferred_from_custom_id(self):
        payload = {
            "status": "SUCCESS",
            "data": {
                "jobId": "job-001",
                "imageUrl": "https://example.test/grid.png",
                "components": [
                    {"custom_id": "MJ::JOB::upsample::2::abc"},
                    {"custom_id": "MJ::JOB::variation::3::abc"},
                ],
            },
        }

        job = TTAPIMidJourneyClient.to_job(payload, "prompt")

        self.assertEqual([item.label for item in job.actions], ["U2", "V3"])

    def test_four_u_images_become_candidates(self):
        payload = {
            "status": "SUCCESS",
            "data": {
                "jobId": "job-u-images",
                "uImages": [
                    {"url": f"https://example.test/{index}.png"}
                    for index in range(1, 5)
                ],
            },
        }

        job = TTAPIMidJourneyClient.to_job(payload, "prompt")

        self.assertEqual(len(job.candidates), 4)
        self.assertEqual(job.candidates[0].label, "候选 1")

    def test_submit_action_requires_real_action_id(self):
        client = TTAPIMidJourneyClient(self.settings)
        job = TTAPIMidJourneyClient.to_job(
            {"status": "SUCCESS", "data": {"jobId": "job-001"}},
            "prompt",
        )

        with self.assertRaisesRegex(TTAPIError, "没有可用的 U1 Action ID"):
            client.submit_action(job, "U1")

    def test_prompt_adds_midjourney_parameters(self):
        prompt = build_midjourney_prompt(
            "editorial football photography",
            "文字，水印",
            "1280x720",
        )

        self.assertIn("--ar 16:9", prompt)
        self.assertIn("--style raw", prompt)
        self.assertIn("--no text watermark logo", prompt)

    def test_prompt_adds_reference_image_and_weight(self):
        prompt = build_midjourney_prompt(
            "editorial football photography",
            "文字，水印",
            "1280x720",
            "https://example.test/reference.jpg",
            "A player celebrating in a stadium",
            1.7,
        )

        self.assertTrue(prompt.startswith("https://example.test/reference.jpg "))
        self.assertIn("A player celebrating in a stadium", prompt)
        self.assertIn("--iw 1.7", prompt)

    def test_reference_image_requires_https(self):
        with self.assertRaisesRegex(ValueError, "HTTPS URL"):
            validate_reference_image_url("http://example.test/reference.jpg")

    @patch("ttapi_client.requests.request")
    def test_ttapi_uses_independent_short_request_timeout(self, request):
        self.settings.ttapi_request_timeout_seconds = 7
        response = request.return_value
        response.json.return_value = {
            "status": "PENDING",
            "data": {"jobId": "job-001"},
        }

        client = TTAPIMidJourneyClient(self.settings)
        job = client.create_job("prompt")

        self.assertEqual(job.job_id, "job-001")
        self.assertEqual(request.call_args.kwargs["timeout"], (7.0, 7.0))


if __name__ == "__main__":
    unittest.main()
