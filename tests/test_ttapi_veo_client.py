import unittest
from unittest.mock import patch

from config import Settings
from ttapi_veo_client import TTAPIVeoClient


class TTAPIVeoClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(ttapi_video_api_key="veo-test-key")

    @patch("ttapi_veo_client.requests.request")
    def test_create_video_uses_official_ttapi_endpoint(self, request):
        response = request.return_value
        response.json.return_value = {"status": "SUCCESS", "data": {"jobId": "veo-001"}}

        job_id = TTAPIVeoClient(self.settings).create_video(
            "football match", "16:9", "veo-3.1-fast"
        )

        self.assertEqual(job_id, "veo-001")
        self.assertTrue(request.call_args.args[1].endswith("/gemini/video/generations"))
        self.assertEqual(request.call_args.kwargs["json"]["duration"], "8")

    @patch("ttapi_veo_client.requests.request")
    def test_fetch_extracts_video_url(self, request):
        response = request.return_value
        response.json.return_value = {
            "status": "SUCCESS",
            "data": {"jobId": "veo-001", "video_url": "https://example.test/clip.mp4"},
        }

        url, payload = TTAPIVeoClient(self.settings).poll_until_ready("veo-001")

        self.assertEqual(url, "https://example.test/clip.mp4")
        self.assertEqual(payload["data"]["jobId"], "veo-001")


if __name__ == "__main__":
    unittest.main()
