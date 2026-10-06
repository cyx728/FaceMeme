from copy import deepcopy
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from common import ROOT, read_json, write_json
from run_all import config_errors, merge_defaults, prepare_config, process_videos


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.defaults = read_json(ROOT / "config.example.json")

    def valid_config(self):
        config = deepcopy(self.defaults)
        config["api"]["api_key"] = "offline-key"
        return config

    def test_completion_preserves_api_and_rejects_invalid_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_json(path, {"api": {"api_key": "offline-key", "model": "custom-vision"}})
            config = prepare_config(path, interactive=False)
            self.assertEqual(config["api"]["model"], "custom-vision")
            self.assertEqual(config["api"]["api_key"], "offline-key")
            self.assertEqual(config["export"]["formats"], ["jpg", "gif"])
        config = self.valid_config()
        config["selection"]["sample_every"] = True
        config["api"]["base_url"] = "https://example.com/v1/chat/completions"
        config["export"]["formats"] = ["unsupported"]
        self.assertEqual(len(config_errors(config)), 3)

    def test_malformed_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_config(path, False)
            self.assertEqual(path.read_text(), "{broken")

    def test_batch_continues_after_failure_and_resumes_changed_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            for name in ("失败.mp4", "成功.mov"):
                (source / name).write_bytes(b"fixture")
            (root / "step1.py").write_text("fixture")
            config = self.valid_config()
            config_path = root / "config.json"
            write_json(config_path, config)
            calls = []

            def fake_checked(command, **kwargs):
                calls.append(command)
                if Path(command[2]).name == "step1.py":
                    if Path(command[3]).stem == "失败":
                        raise subprocess.CalledProcessError(1, "offline-step1")
                    output = Path(command[command.index("--output") + 1])
                    write_json(output / "frames.json", {"frames": []})

            with patch("run_all.ROOT", root), patch("run_all.checked_call", side_effect=fake_checked), patch("run_all.subprocess.run") as fake_caption:
                fake_caption.return_value.returncode = 1
                self.assertEqual(process_videos("python", config_path, config, source), 1)
                report = read_json(root / "output" / "batch_report.json")
                self.assertEqual([row["status"] for row in report], ["failed", "partial"])
                self.assertIn("--allow-partial", calls[-1])
                before = sum(Path(command[2]).name == "step1.py" for command in calls)
                fake_caption.return_value.returncode = 0
                process_videos("python", config_path, config, source)
                # Only failed video reruns step1; successful video resumes.
                after = sum(Path(command[2]).name == "step1.py" for command in calls)
                self.assertEqual(after - before, 1)
                config["selection"]["top_n"] = 10
                process_videos("python", config_path, config, source)
                report = read_json(root / "output" / "batch_report.json")
                alternate = report[1]["output"]
                self.assertNotEqual(alternate, str(root / "output" / "成功"))
                process_videos("python", config_path, config, source)
                self.assertEqual(read_json(root / "output" / "batch_report.json")[1]["output"], alternate)

    def test_duplicate_stems_rejected_before_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("same.mp4", "Same.mov"):
                (root / name).write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "重复"):
                process_videos("python", root / "config.json", self.valid_config(), root)


if __name__ == "__main__":
    unittest.main()
