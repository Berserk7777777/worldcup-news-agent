import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image

from news_video_service import (
    compose_video,
    render_news_frame,
    split_broadcast_script,
    subtitle_entries,
    wav_duration,
    write_srt,
)


class NewsVideoTests(unittest.TestCase):
    def test_script_is_split_into_short_subtitles(self):
        text = "这是第一句世界杯新闻。第二句话比较长，需要拆分为适合视频展示的字幕内容。"

        segments = split_broadcast_script(text, max_chars=12)

        self.assertGreater(len(segments), 2)
        self.assertTrue(all(len(item) <= 12 for item in segments))

    def test_subtitle_timeline_matches_audio_duration(self):
        entries = subtitle_entries("第一句。第二句稍微长一些。", 9.5)

        self.assertEqual(entries[0]["start"], 0)
        self.assertAlmostEqual(entries[-1]["end"], 9.5)
        self.assertTrue(all(item["duration"] > 0 for item in entries))

    def test_srt_and_frame_are_materialized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "source.png"
            Image.new("RGB", (640, 480), "#336655").save(image_path)
            entries = subtitle_entries("世界杯新闻播报测试。", 2.0)
            subtitle_path = root / "subtitles.srt"
            write_srt(entries, subtitle_path)
            frame_path = root / "frame.png"
            render_news_frame(
                frame_path,
                (640, 360),
                "世界杯新闻",
                entries[0]["text"],
                {
                    "path": image_path,
                    "kind": "source",
                    "credit": "测试来源",
                },
                None,
            )

            self.assertIn("00:00:00,000", subtitle_path.read_text(encoding="utf-8"))
            self.assertGreater(frame_path.stat().st_size, 1000)

    def test_wav_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 8000)

            self.assertAlmostEqual(wav_duration(audio_path), 1.0)

    def test_ffmpeg_composes_playable_mp4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frame_path = root / "frame.png"
            Image.new("RGB", (320, 180), "#173b30").save(frame_path)
            audio_path = root / "audio.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 8000)
            output_path = root / "video.mp4"

            compose_video(
                root,
                [{"duration": 1.0}],
                [frame_path],
                audio_path,
                output_path,
            )

            self.assertGreater(output_path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
