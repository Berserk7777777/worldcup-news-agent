import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from news_images import (
    COMBINED_IMAGE_USAGE,
    images_by_placement,
    save_source_image,
    uses_midjourney_reference,
    uses_source_image,
)


class NewsImageTests(unittest.TestCase):
    def test_combined_usage_enables_both_paths(self):
        self.assertTrue(uses_source_image(COMBINED_IMAGE_USAGE))
        self.assertTrue(uses_midjourney_reference(COMBINED_IMAGE_USAGE))

    def test_source_image_is_saved_and_ai_candidate_is_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            buffer = BytesIO()
            Image.new("RGB", (320, 180), "#0f6b4f").save(buffer, format="JPEG")
            user_input = SimpleNamespace(
                source_image_caption="真实赛场图片",
                source_image_credit="测试摄影者",
                source_image_url="https://example.com/photo",
                source_image_placement="after_lead",
            )
            source = save_source_image(
                run_dir,
                {"bytes": buffer.getvalue(), "name": "photo.jpg"},
                user_input,
            )
            candidate_path = run_dir / "candidate.png"
            Image.new("RGB", (320, 180), "#d8e862").save(candidate_path)
            result = {
                "images": [
                    source,
                    {
                        "kind": "ai",
                        "name": "候选图",
                        "local_path": str(candidate_path),
                        "placement": "after_paragraph_2",
                        "selected": False,
                    },
                ]
            }

            grouped = images_by_placement(result, run_dir)

            self.assertTrue((run_dir / "source_image_1.png").is_file())
            self.assertEqual(len(grouped["after_lead"]), 1)
            self.assertEqual(grouped["after_paragraph_2"], [])


if __name__ == "__main__":
    unittest.main()
