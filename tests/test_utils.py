import json
import shutil
import tempfile
import unittest
from pathlib import Path

from siliconflow_client import ModelOutputError
from utils import (
    count_non_whitespace_characters,
    create_run_directory,
    extract_urls,
    is_image_generation_request,
    should_start_image_only_job,
    is_valid_article_length,
    load_saved_result,
    requested_image_count,
    sanitize_error_message,
    strip_json_code_fence,
    validate_required_keys,
)


class UtilsTests(unittest.TestCase):
    def test_strip_plain_json(self):
        self.assertEqual(json.loads(strip_json_code_fence('{"ok": true}'))["ok"], True)

    def test_strip_json_fence(self):
        cleaned = strip_json_code_fence('```json\n{"ok": true}\n```')
        self.assertTrue(json.loads(cleaned)["ok"])

    def test_strip_json_with_surrounding_text(self):
        cleaned = strip_json_code_fence('以下是JSON输出：\n{"ok": true}\n分析完毕')
        self.assertTrue(json.loads(cleaned)["ok"])

    def test_count_ignores_whitespace(self):
        self.assertEqual(count_non_whitespace_characters("你好 世界\n测试"), 6)

    def test_valid_length_300(self):
        self.assertTrue(is_valid_article_length("字" * 300))

    def test_valid_length_500(self):
        self.assertTrue(is_valid_article_length("字" * 500))

    def test_invalid_length_299(self):
        self.assertFalse(is_valid_article_length("字" * 299))

    def test_invalid_length_501(self):
        self.assertFalse(is_valid_article_length("字" * 501))

    def test_validate_required_keys_raises(self):
        with self.assertRaises(ModelOutputError):
            validate_required_keys({"a": 1}, ["a", "b"], "测试阶段")

    def test_sanitize_bearer_token(self):
        cleaned = sanitize_error_message(Exception("Authorization: Bearer sk-abc123"))
        self.assertNotIn("sk-abc123", cleaned)

    def test_sanitize_long_message(self):
        cleaned = sanitize_error_message(Exception("x" * 600))
        self.assertLessEqual(len(cleaned), 550)
        self.assertTrue(cleaned.endswith("…[已截断]"))

    def test_create_run_directory_no_overwrite(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            first = create_run_directory(temp_dir)
            second = create_run_directory(temp_dir)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
        finally:
            shutil.rmtree(temp_dir)

    def test_extract_urls_deduplicates_and_trims_punctuation(self):
        text = "来源：https://example.com/a。再次引用 https://example.com/a。"
        self.assertEqual(extract_urls(text), ["https://example.com/a"])

    def test_requested_image_count_uses_message(self):
        self.assertEqual(requested_image_count("生成两张梅西图片", 1), 2)
        self.assertEqual(
            requested_image_count("给我生成一个决赛梅西的图片。生成两张", 1),
            2,
        )
        self.assertEqual(requested_image_count("只要1张图片", 2), 1)
        self.assertEqual(requested_image_count("生成梅西图片", 2), 2)

    def test_requested_image_count_recovers_from_none_default(self):
        self.assertEqual(requested_image_count("生成梅西图片", None), 1)

    def test_image_generation_request_detection(self):
        self.assertTrue(
            is_image_generation_request("给出世界杯2026年决赛梅西的两张特写照片")
        )
        self.assertTrue(is_image_generation_request("给我生成两张梅西图片"))
        self.assertFalse(is_image_generation_request("写一篇新闻并生成两张配图"))

    def test_news_mode_never_routes_to_image_only_job(self):
        request = "根据上传照片生成一张MidJourney图片"
        self.assertFalse(should_start_image_only_job("新闻创作", request))
        self.assertTrue(should_start_image_only_job("对话", request))

    def test_load_saved_result_rejects_parent_path(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(FileNotFoundError):
                load_saved_result("../outside", temp_dir)
        finally:
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
