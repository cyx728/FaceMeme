import argparse
import base64
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import numpy as np

from PIL import Image

from common import default_font, write_json, read_json, resolve_manifest, video_output_dir
from step1 import expression_score, select_frames, rotate_face, original_box, score_faces
from step2 import run as caption_run, validate_caption
from step3 import STYLES, render, run as export_run

FONT = str(default_font())


class PipelineTests(unittest.TestCase):
    def test_video_output_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch("common.ROOT", Path(directory)):
            root = Path(directory) / "output"
            self.assertEqual(video_output_dir("D:/videos/测试.2026.mp4"), root / "测试.2026")
            manifest = root / "测试.2026" / "frames.json"
            write_json(manifest, {"frames": []})
            self.assertEqual(resolve_manifest(video="测试.2026.mp4"), manifest)
            self.assertEqual(resolve_manifest(video="测试.2026"), manifest)
            self.assertEqual(resolve_manifest(), manifest)
            write_json(root / "second" / "frames.json", {"frames": []})
            with self.assertRaisesRegex(ValueError, "Specify a video name"):
                resolve_manifest()
            with self.assertRaises(ValueError):
                resolve_manifest(str(manifest), "second")

    def test_caption_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "face.png"
            background = (120, 170, 200)
            for size in ((320, 240), (160, 400), (400, 100)):
                Image.new("RGB", size, background).save(source)
                for style in STYLES:
                    with self.subTest(size=size, style=style):
                        picture = render(source, "懂了但没完全懂", FONT, 48, 768, style=style)
                        self.assertEqual(max(picture.size), 768)
                        if style != "bottom_bar":
                            self.assertLessEqual(abs(picture.width * size[1] - picture.height * size[0]), max(size))
                            self.assertEqual(picture.getpixel((0, 0)), background)
                            pixels = list(picture.getdata())
                            if style == "red_box":
                                self.assertIn((255, 59, 48), pixels)
                                self.assertIn((0, 0, 0), pixels)
                            else:
                                color = (255, 255, 255) if style == "white_text" else (0, 0, 0)
                                self.assertIn(color, pixels)
                                self.assertNotIn((255, 59, 48), pixels)

    def test_face_rotation_and_coordinate_mapping(self):
        image = np.arange(6).reshape(2, 3)
        np.testing.assert_array_equal(rotate_face(rotate_face(image, 90), -90), image)
        self.assertEqual(original_box([10, 20, 30, 40], 90, 100, 80), [20, 50, 40, 70])
        self.assertEqual(original_box([10, 20, 30, 40], -90, 100, 80), [60, 10, 80, 30])
        # One sideways face found in two orientations must be exported only once.
        outputs = [[dict(score=70, bbox=[20, 50, 40, 70], roll_degrees=-90)],
                   [], [dict(score=75, bbox=[50, 60, 70, 80], roll_degrees=0)], []]
        with patch("step1.score_oriented_faces", side_effect=outputs):
            faces = score_faces(np.zeros((80, 100, 3), dtype=np.uint8), None, None, 5, 10)
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0]["rotation_degrees"], -90)
        self.assertEqual(faces[0]["score"], 75)

    def test_rotation_rejects_inverted_and_uncertain_detections(self):
        self.assertEqual(original_box([10, 20, 30, 40], 180, 100, 80), [70, 40, 90, 60])
        frame = np.zeros((80, 100, 3), dtype=np.uint8)
        for roll in (58.8, 137.9, 176.0, float("nan")):
            with self.subTest(roll=roll), patch("step1.score_oriented_faces", side_effect=[
                    [dict(score=95, bbox=[10, 10, 30, 30], roll_degrees=roll)], [], [], []]):
                self.assertEqual(score_faces(frame, None, None, 5, 10), [])
        with patch("step1.score_oriented_faces", side_effect=[
                [dict(score=95, bbox=[10, 10, 30, 30], roll_degrees=0, upright_geometry=False)], [], [], []]):
            self.assertEqual(score_faces(frame, None, None, 5, 10), [])
        # A sideways trial must not replace an already confirmed upright face.
        with patch("step1.score_oriented_faces", side_effect=[
                [dict(score=70, bbox=[20, 50, 40, 70], roll_degrees=15)],
                [dict(score=95, bbox=[10, 20, 30, 40], roll_degrees=0)], [], []]):
            faces = score_faces(frame, None, None, 5, 10)
            self.assertEqual(len(faces), 1)
            self.assertEqual(faces[0]["rotation_degrees"], 0)
        with patch("step1.score_oriented_faces", side_effect=[[], [], [],
                [dict(score=70, bbox=[10, 20, 30, 40], roll_degrees=0)]]):
            self.assertEqual(score_faces(frame, None, None, 5, 10)[0]["rotation_degrees"], -180)

    def test_score_and_selection(self):
        neutral, _ = expression_score({})
        exaggerated, _ = expression_score({"jawOpen": 1, "eyeWideLeft": 1,
                                            "mouthLeft": 1, "eyeBlinkLeft": 1})
        self.assertEqual(neutral, 0)
        self.assertGreater(exaggerated, 70)
        rows = [dict(frame_index=i, timestamp_seconds=t, score=s)
                for i, t, s in ((0, 0, 90), (1, 0.2, 95), (2, 2, 70), (3, 3, 60))]
        self.assertEqual([r["frame_index"] for r in select_frames(rows, 2, None, 1)], [1, 2])
        self.assertEqual(len(select_frames(rows, 1, 70, 0)), 3)

    def test_reject_invalid_caption(self):
        for content in ('{"caption":""}', '{"caption":"太长了吧"}', '{"caption":"a\\nb"}'):
            with self.assertRaises(ValueError):
                validate_caption(content, 3)

    def test_caption_resume_and_export(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(payload)
                self.assert_request = self.path
                image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
                Image.open(io.BytesIO(base64.b64decode(image_url.split(",", 1)[1]))).verify()
                data = json.dumps({"choices": [{"message": {"content": '{"caption":"瞅你咋地"}'}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "face.png"
                Image.new("RGB", (200, 300), "#c3e6cb").save(source)
                manifest = root / "frames.json"
                write_json(manifest, {"frames": [{"id": "frame_00000000", "image": "face.png",
                                                  "score": 78, "timestamp_seconds": 0}]})
                config = root / "config.json"
                write_json(config, {"api": {"base_url": f"http://127.0.0.1:{server.server_port}/v1",
                                            "api_key": "offline-test", "model": "fake-vision"},
                                    "export": {"font_path": FONT, "style": "bottom_bar", "formats": ["png"]}})
                args = argparse.Namespace(config=str(config), manifest=str(manifest), output=None, force=False)
                self.assertEqual(caption_run(args), 0)
                self.assertEqual(caption_run(args), 0)
                self.assertEqual(len(calls), 1)
                export_args = argparse.Namespace(config=str(config), manifest=str(manifest), captions=None,
                                                 output=None, font=None, allow_partial=False)
                export_run(export_args)
                with Image.open(root / "memes" / "frame_00000000.png") as picture:
                    self.assertLessEqual(max(picture.size), 768)
                    self.assertGreater(picture.height, 300)
                    self.assertGreater(picture.width, 200)
                    self.assertEqual(max(picture.size), 768)
                self.assertEqual(read_json(root / "memes" / "index.json")["memes"][0]["caption"], "瞅你咋地")
                settings = read_json(config)
                settings["export"].pop("formats")
                settings["export"].pop("style")
                write_json(config, settings)
                export_run(export_args)
                index = read_json(root / "memes" / "index.json")
                self.assertEqual(index["formats"], ["jpg", "gif"])
                self.assertEqual(index["style"], "red_box")
                self.assertEqual(index["memes"][0]["files"], ["frame_00000000.jpg", "frame_00000000.gif"])
                for extension, expected in (("jpg", "JPEG"), ("gif", "GIF")):
                    with Image.open(root / "memes" / f"frame_00000000.{extension}") as picture:
                        self.assertEqual(picture.format, expected)
                        self.assertEqual(picture.size, (512, 768))
                        self.assertEqual(getattr(picture, "n_frames", 1), 1)
                source.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "Image changed"):
                    export_run(export_args)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
