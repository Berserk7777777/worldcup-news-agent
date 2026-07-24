import tempfile
import unittest
from pathlib import Path

from knowledge_base import (
    Article,
    KnowledgeBase,
    _is_relevant,
    _normalize_date,
    _prioritize_urls,
    _rank_sitemap_entries,
    _should_search_live,
    format_retrieval_context,
    split_text,
)
from rag_sources import SourceConfig


class FakeEmbeddingClient:
    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts]


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = KnowledgeBase(Path(self.temp_dir.name) / "knowledge.db")
        self.source_a = SourceConfig(
            "fifa",
            "A",
            "FIFA",
            "en",
            "official",
            "https://www.fifa.com/news",
            "官方赛事信息",
        )
        self.source_b = SourceConfig(
            "media",
            "B",
            "Reliable Media",
            "zh",
            "media",
            "https://example.com/sports",
            "赛事报道",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_split_text_keeps_chunks_bounded(self):
        chunks = split_text(("第一段内容。" * 100) + "\n\n" + ("第二段内容。" * 100))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1352 for chunk in chunks))

    def test_save_deduplicates_and_hybrid_search_prefers_level_a(self):
        official = Article(
            self.source_a,
            "https://www.fifa.com/article/official",
            "FIFA World Cup 2026 official result",
            "2026-07-20",
            "en",
            "FIFA World Cup 2026 official result and match statistics.",
        )
        media = Article(
            self.source_b,
            "https://example.com/article",
            "世界杯赛事报道",
            "2026-07-20",
            "zh",
            "世界杯赛事报道和比赛统计。",
        )
        self.assertEqual(
            self.database.save_article(
                official, "世界杯官方赛果和统计。", [official.content], [[1.0, 0.0]], "test"
            ),
            "new",
        )
        self.assertEqual(
            self.database.save_article(
                official, "世界杯官方赛果和统计。", [official.content], [[1.0, 0.0]], "test"
            ),
            "skipped",
        )
        self.database.save_article(
            media, media.content, [media.content], [[1.0, 0.0]], "test"
        )

        results = self.database.search("世界杯赛果", FakeEmbeddingClient(), limit=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["source_level"], "A")
        self.assertEqual(self.database.status()["documents"], 2)

    def test_context_contains_numbered_sources(self):
        context = format_retrieval_context(
            [
                {
                    "source_level": "A",
                    "source_name": "FIFA",
                    "document_title": "Official report",
                    "published_at": "2026-07-20",
                    "source_url": "https://fifa.example/report",
                    "summary_zh": "中文摘要",
                    "chunk_preview": "Original excerpt",
                }
            ]
        )
        self.assertIn("[1]", context)
        self.assertIn("FIFA", context)
        self.assertIn("https://fifa.example/report", context)

    def test_year_in_url_does_not_make_unrelated_article_relevant(self):
        self.assertFalse(
            _is_relevant(
                "https://example.com/20260723/article 青少年阳光体育大会",
                "2026世界杯",
            )
        )

    def test_english_publication_date(self):
        self.assertEqual(
            _normalize_date("", "Published Monday 20 July 2026 at 10:00"),
            "2026-07-20",
        )

    def test_specific_moment_request_triggers_live_search(self):
        items = [
            {"retrieval_score": 0.8},
            {"retrieval_score": 0.7},
            {"retrieval_score": 0.6},
        ]

        self.assertTrue(
            _should_search_live("生成两个姆巴佩2026世界杯名场面", items)
        )
        self.assertFalse(_should_search_live("介绍世界杯历史", items))

    def test_sitemap_ranking_uses_player_search_words(self):
        entries = [
            (
                "https://www.fifa.com/en/articles/france-mbappe-dembele-goals",
                "2026-07-11",
            ),
            (
                "https://www.fifa.com/en/articles/spain-world-cup-final",
                "2026-07-20",
            ),
            (
                "https://www.fifa.com/en/articles/kylian-mbappe-records",
                "2026-07-18",
            ),
        ]

        results = _rank_sitemap_entries(
            entries,
            "Kylian Mbappe 2026 FIFA World Cup goals match reports",
            limit=2,
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all("mbappe" in url for url in results))

    def test_live_search_urls_are_prioritized(self):
        items = [
            {"source_url": "https://example.com/general", "retrieval_score": 0.8},
            {"source_url": "https://fifa.com/mbappe", "retrieval_score": 0.5},
        ]

        ranked = _prioritize_urls(items, {"https://fifa.com/mbappe"})

        self.assertEqual(ranked[0]["source_url"], "https://fifa.com/mbappe")
        self.assertEqual([item["rank"] for item in ranked], [1, 2])


if __name__ == "__main__":
    unittest.main()
