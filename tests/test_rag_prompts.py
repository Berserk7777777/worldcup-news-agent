import unittest

from prompts import (
    build_planner_prompt,
    build_reviewer_prompt,
    build_writer_prompt,
)
from schemas import UserInput
from workflow import _append_source_list
from workflow import continue_with_user_material


class RagPromptTests(unittest.TestCase):
    def setUp(self):
        self.user_input = UserInput(
            "真实报道",
            "世界杯主办城市经济",
            "世界杯与城市经济",
            "公众",
            "简洁客观报道",
            "[1] FIFA，官方资料，2026-07-20，https://fifa.example/report",
            "体育新闻摄影",
            1,
        )

    def test_all_agents_receive_numbered_evidence(self):
        planner_system, planner_user = build_planner_prompt(self.user_input)
        writer_system, writer_user = build_writer_prompt(
            self.user_input, {"can_proceed": True}
        )
        reviewer_system, reviewer_user = build_reviewer_prompt(
            self.user_input,
            {"can_proceed": True},
            {"full_article": "城市客流增长[1]。"},
        )

        self.assertIn("[1]", planner_user)
        self.assertIn("对应编号", planner_system)
        self.assertIn("句末必须标注", writer_system)
        self.assertIn("[1]", writer_user)
        self.assertIn("核对正文每个[编号]", reviewer_system)
        self.assertIn("[1]", reviewer_user)

    def test_news_writing_skill_is_loaded_for_all_text_agents(self):
        planner_system, _ = build_planner_prompt(self.user_input)
        writer_system, _ = build_writer_prompt(
            self.user_input, {"can_proceed": True}
        )
        reviewer_system, _ = build_reviewer_prompt(
            self.user_input,
            {"can_proceed": True},
            {"full_article": "测试正文"},
        )

        for system_prompt in (planner_system, writer_system, reviewer_system):
            self.assertIn("<NEWS_WRITING_SKILL>", system_prompt)
            self.assertIn("不要把操作指令直接复制成标题", system_prompt)
            self.assertIn("AI生成示意图", system_prompt)

    def test_source_list_is_appended_deterministically(self):
        article = _append_source_list(
            "主办城市客流增长[1]。",
            [
                {
                    "source_name": "FIFA",
                    "document_title": "Official report",
                    "published_at": "2026-07-20",
                    "source_url": "https://fifa.example/report",
                }
            ],
        )
        self.assertTrue(article.endswith("https://fifa.example/report"))
        self.assertIn("[1] FIFA，《Official report》，2026-07-20", article)

    def test_planner_rejection_continues_as_attributed_draft(self):
        rejected = {
            "can_proceed": False,
            "reason": "知识库没有独立证据",
            "risk_warnings": [],
            "missing_critical_facts": ["独立来源"],
        }

        self.assertTrue(continue_with_user_material(self.user_input, rejected))
        self.assertTrue(rejected["can_proceed"])
        self.assertEqual(rejected["verification_status"], "user_material_unverified")
        self.assertIn("待核实稿", rejected["reason"])


if __name__ == "__main__":
    unittest.main()
