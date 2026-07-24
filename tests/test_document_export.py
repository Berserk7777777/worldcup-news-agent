import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from document_export import build_docx_bytes, build_pdf_bytes


class DocumentExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp_dir.name)
        source_path = self.run_dir / "source_image_1.png"
        ai_path = self.run_dir / "image_1.png"
        Image.new("RGB", (640, 360), "#0f6b4f").save(source_path)
        Image.new("RGB", (640, 360), "#d8e862").save(ai_path)
        self.result = {
            "created_at": "2026-07-23 20:00:00",
            "user_input": {"topic": "世界杯新闻", "news_type": "真实报道"},
            "reviewer_result": {
                "final_title": "世界杯测试新闻",
                "final_article_label": "真实报道",
                "final_article": (
                    "世界杯测试新闻\n\n这是新闻导语。\n\n"
                    "这是带有事实引用的新闻正文[1]。\n\n"
                    "这是新闻结尾。\n\n"
                    "来源：\n[1] FIFA，测试来源，2026-07-23，https://example.com"
                ),
            },
            "writer_result": {},
            "images": [
                {
                    "image_id": "source_1",
                    "kind": "source",
                    "name": "真实新闻图片",
                    "caption": "球员在赛后致意",
                    "credit": "测试摄影者",
                    "source_url": "https://example.com/photo",
                    "local_path": str(source_path),
                    "placement": "after_lead",
                    "selected": True,
                },
                {
                    "image_id": "ai_1",
                    "kind": "ai",
                    "name": "AI新闻配图",
                    "caption": "赛场气氛示意",
                    "local_path": str(ai_path),
                    "placement": "after_paragraph_2",
                    "selected": True,
                    "ai_disclosure": "AI生成示意图",
                },
            ],
            "sources": [
                {
                    "source_name": "FIFA",
                    "document_title": "测试来源",
                    "published_at": "2026-07-23",
                    "source_url": "https://example.com",
                }
            ],
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_docx_contains_image_article_and_hyperlink(self):
        data = build_docx_bytes(self.result, self.run_dir)

        self.assertTrue(data.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            document_xml = archive.read("word/document.xml").decode("utf-8")
            relationships = archive.read(
                "word/_rels/document.xml.rels"
            ).decode("utf-8")
        self.assertTrue(any(name.startswith("word/media/") for name in names))
        self.assertIn("世界杯测试新闻", document_xml)
        self.assertIn("这是带有事实引用的新闻正文", document_xml)
        self.assertIn("图片来源：测试摄影者", document_xml)
        self.assertIn("AI生成示意图", document_xml)
        self.assertLess(
            document_xml.index("这是新闻导语"),
            document_xml.index("球员在赛后致意"),
        )
        self.assertLess(
            document_xml.index("球员在赛后致意"),
            document_xml.index("这是带有事实引用的新闻正文"),
        )
        self.assertLess(
            document_xml.index("这是带有事实引用的新闻正文"),
            document_xml.index("赛场气氛示意"),
        )
        self.assertIn("https://example.com", relationships)

    def test_pdf_contains_image_and_multiple_sections(self):
        data = build_pdf_bytes(self.result, self.run_dir)

        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 10_000)


if __name__ == "__main__":
    unittest.main()
