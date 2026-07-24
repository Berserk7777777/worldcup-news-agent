import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from siliconflow_client import SiliconFlowClient


class MediaClientTests(unittest.TestCase):
    def setUp(self):
        self.client = SiliconFlowClient.__new__(SiliconFlowClient)
        self.client.settings = SimpleNamespace(
            api_key="secret",
            base_url="https://api.example.test/v1",
            request_timeout=30,
            asr_model="asr-model",
            vision_model="vision-model",
            embedding_model="embedding-model",
            chat_model="chat-model",
        )

    @patch("siliconflow_client.requests.post")
    def test_transcribe_audio(self, post):
        response = post.return_value
        response.json.return_value = {"text": "世界杯新闻"}

        text = self.client.transcribe_audio(b"wav", "recording.wav", "audio/wav")

        self.assertEqual(text, "世界杯新闻")
        self.assertEqual(post.call_args.kwargs["data"]["model"], "asr-model")

    def test_analyze_image_uses_data_url(self):
        response = MagicMock()
        response.choices = [
            SimpleNamespace(message=SimpleNamespace(content="图片中是一座足球场"))
        ]
        self.client.client = MagicMock()
        self.client.client.chat.completions.create.return_value = response

        text = self.client.analyze_image(b"image", "image/png", "写一篇新闻")

        self.assertEqual(text, "图片中是一座足球场")
        request = self.client.client.chat.completions.create.call_args.kwargs
        image_url = request["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))

    def test_stream_chat_yields_content_chunks(self):
        self.client.client = MagicMock()
        self.client.client.chat.completions.create.return_value = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="！"))]
            ),
        ]

        chunks = list(
            self.client.stream_chat(
                "chat-model",
                [{"role": "user", "content": "你好"}],
            )
        )

        self.assertEqual(chunks, ["你好", "！"])
        request = self.client.client.chat.completions.create.call_args.kwargs
        self.assertTrue(request["stream"])
        self.assertEqual(request["model"], "chat-model")
        self.assertEqual(request["extra_body"], {"enable_thinking": False})

    def test_call_json_model_retries_without_unsupported_thinking_parameter(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
        self.client.client = MagicMock()
        create = self.client.client.chat.completions.create
        create.side_effect = [
            Exception(
                "Error code: 400 - {'code': 20015, 'message': "
                "'current model does not support parameter enable_thinking.'}"
            ),
            response,
        ]

        data, usage = self.client.call_json_model(
            "review-model",
            "system",
            "user",
            0.1,
            1000,
        )

        self.assertEqual(data, {"ok": True})
        self.assertEqual(usage.total_tokens, 15)
        self.assertEqual(create.call_count, 2)
        first_request = create.call_args_list[0].kwargs
        second_request = create.call_args_list[1].kwargs
        self.assertEqual(
            first_request["extra_body"],
            {"enable_thinking": False},
        )
        self.assertNotIn("extra_body", second_request)

    def test_call_json_model_does_not_retry_unrelated_error(self):
        self.client.client = MagicMock()
        create = self.client.client.chat.completions.create
        create.side_effect = RuntimeError("service unavailable")

        with self.assertRaisesRegex(RuntimeError, "service unavailable"):
            self.client.call_json_model(
                "review-model",
                "system",
                "user",
                0.1,
                1000,
            )

        self.assertEqual(create.call_count, 1)

    def test_embed_texts_preserves_api_order(self):
        self.client.client = MagicMock()
        self.client.client.embeddings.create.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ]
        )

        vectors = self.client.embed_texts(["世界杯", "足球"])

        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        request = self.client.client.embeddings.create.call_args.kwargs
        self.assertEqual(request["model"], "embedding-model")

    def test_summarize_to_chinese(self):
        self.client.client = MagicMock()
        self.client.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="中文摘要"))]
        )

        summary = self.client.summarize_to_chinese("Title", "English article")

        self.assertEqual(summary, "中文摘要")

    def test_build_search_query(self):
        self.client.client = MagicMock()
        self.client.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Kylian Mbappe 2026 World Cup goals match reports"
                    )
                )
            ]
        )

        query = self.client.build_search_query("姆巴佩2026世界杯名场面")

        self.assertEqual(
            query,
            "Kylian Mbappe 2026 World Cup goals match reports",
        )
        request = self.client.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "chat-model")
        self.assertEqual(request["extra_body"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()
