"""Rank sampled video frames using local MediaPipe expression blendshapes.

注：画面中人脸可能不止一个，逐脸评分，帧得分及默认裁剪取最高分人脸。
"""
import argparse
import bisect
import json
import math
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
from tqdm import tqdm

from common import ROOT, load_config, positive, video_output_dir, write_json

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
DETECTOR_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"


def expression_score(values):
    def v(name):
        return max(0.0, min(1.0, values.get(name, 0.0)))

    mouth = max(v("jawOpen"), (v("mouthFunnel") + v("mouthPucker")) / 2)
    distortion = max(v("mouthLeft"), v("mouthRight"), v("mouthStretchLeft"),
                     v("mouthStretchRight"), v("mouthRollLower"), v("mouthRollUpper"))
    eyes = max(v("eyeWideLeft"), v("eyeWideRight"),
               v("eyeSquintLeft"), v("eyeSquintRight"))
    brows = max(v("browInnerUp"), v("browOuterUpLeft"), v("browOuterUpRight"),
                v("browDownLeft"), v("browDownRight"))
    asymmetry = max(abs(v(prefix + "Left") - v(prefix + "Right"))
                    for prefix in ("eyeBlink", "eyeSquint", "mouthSmile", "mouthFrown", "browDown"))
    smile = (v("mouthSmileLeft") + v("mouthSmileRight")) / 2
    components = dict(mouth=mouth, distortion=distortion, eyes=eyes,
                      brows=brows, asymmetry=asymmetry, smile=smile)
    score = 100 * (0.28 * mouth + 0.22 * distortion + 0.16 * eyes
                   + 0.12 * brows + 0.17 * asymmetry + 0.05 * smile)
    return round(score, 3), components


def select_frames(candidates, top_n, threshold, gap):
    selected, times = [], []
    for item in sorted(candidates, key=lambda r: (-r["score"], r["frame_index"])):
        if threshold is not None and item["score"] < threshold:
            continue
        t = item["timestamp_seconds"]
        pos = bisect.bisect_left(times, t)
        if ((pos and t - times[pos - 1] < gap) or
                (pos < len(times) and times[pos] - t < gap)):
            continue
        selected.append(item)
        times.insert(pos, t)
        if threshold is None and len(selected) >= top_n:
            break
    return selected


def ensure_model(path, url=MODEL_URL):
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".download")
    tqdm.write(f"Downloading Google's {path.name} model (first run only)...")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as target:
            total_bytes = int(response.headers.get("Content-Length", 0)) or None
            with tqdm(total=total_bytes, desc="Model download", unit="B", unit_scale=True) as progress:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
                    progress.update(len(chunk))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def crop_bounds(box, width, height):
    x1, y1, x2, y2 = box
    dx, dy = int((x2 - x1) * 0.45), int((y2 - y1) * 0.40)
    return max(0, x1 - dx), max(0, y1 - dy), min(width, x2 + dx), min(height, y2 + dy)


def rotate_face(image, degrees):
    rotations = {90: cv2.ROTATE_90_CLOCKWISE, -90: cv2.ROTATE_90_COUNTERCLOCKWISE,
                 180: cv2.ROTATE_180, -180: cv2.ROTATE_180}
    return cv2.rotate(image, rotations[degrees]) if degrees in rotations else image


def original_box(box, degrees, width, height):
    x1, y1, x2, y2 = box
    if degrees == 90:
        return [y1, height - x2, y2, height - x1]
    if degrees == -90:
        return [width - y2, x1, width - y1, x2]
    if abs(degrees) == 180:
        return [width - x2, height - y2, width - x1, height - y1]
    return box


def box_iou(first, second):
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(0, min(first[3], second[3]) - max(first[1], second[1]))
    areas = [(box[2] - box[0]) * (box[3] - box[1]) for box in (first, second)]
    return overlap / max(1, sum(areas) - overlap)


def score_faces(frame, landmarker, face_detector, max_faces, min_face_size, auto_rotate=True):
    height, width = frame.shape[:2]
    faces = []
    for degrees in ((0, 90, -90, 180) if auto_rotate else (0,)):
        oriented = rotate_face(frame, degrees)
        for face in score_oriented_faces(oriented, landmarker, face_detector, max_faces, min_face_size):
            roll = face.pop("roll_degrees")
            upright = face.pop("upright_geometry", True)
            # A trial rotation is usable only when the model sees an upright face.
            # Adding a rounded residual roll can turn a bad detection upside down.
            if auto_rotate and (not math.isfinite(roll) or abs(roll) > 40 or not upright):
                continue
            face["bbox"] = original_box(face["bbox"], degrees, width, height)
            face["rotation_degrees"] = ((degrees + 180) % 360) - 180
            face["orientation_error"] = abs(roll)
            duplicate = next((i for i, known in enumerate(faces) if box_iou(face["bbox"], known["bbox"]) >= 0.4), None)
            if duplicate is None:
                faces.append(face)
            elif (faces[duplicate]["rotation_degrees"] != 0 and
                  face["orientation_error"] < faces[duplicate]["orientation_error"]):
                faces[duplicate] = face
    return sorted(faces, key=lambda face: -face["score"])[:max_faces]


def score_oriented_faces(frame, landmarker, face_detector, max_faces, min_face_size):
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    regions = [(0, 0, w, h)]
    if face_detector is not None:
        detection = face_detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        boxes = sorted(detection.detections, key=lambda d: d.categories[0].score, reverse=True)
        regions = []
        for face in boxes[:max_faces]:
            box = face.bounding_box
            if min(box.width, box.height) < min_face_size:
                continue
            regions.append(crop_bounds([box.origin_x, box.origin_y,
                                        box.origin_x + box.width, box.origin_y + box.height], w, h))
    faces = []
    for left, top, right, bottom in regions:
        if right <= left or bottom <= top:
            continue
        region = rgb[top:bottom, left:right].copy()
        result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=region))
        rh, rw = region.shape[:2]
        for landmarks, categories in zip(result.face_landmarks, result.face_blendshapes):
            x1 = max(0, min(w - 1, left + int(min(p.x for p in landmarks) * rw)))
            y1 = max(0, min(h - 1, top + int(min(p.y for p in landmarks) * rh)))
            x2 = max(0, min(w, left + int(max(p.x for p in landmarks) * rw) + 1))
            y2 = max(0, min(h, top + int(max(p.y for p in landmarks) * rh) + 1))
            if min(x2 - x1, y2 - y1) < min_face_size:
                continue
            values = {c.category_name: float(c.score) for c in categories}
            score, parts = expression_score(values)
            forehead, chin = landmarks[10], landmarks[152]
            roll = math.degrees(math.atan2((chin.x - forehead.x) * rw, (chin.y - forehead.y) * rh))
            eye_y = sum(landmarks[i].y for i in (33, 133, 362, 263)) / 4
            mouth_y = sum(landmarks[i].y for i in (13, 14, 61, 291)) / 4
            upright = (mouth_y - eye_y) * rh > (y2 - y1) * 0.08
            faces.append(dict(score=score, bbox=[x1, y1, x2, y2], components=parts,
                              blendshapes=values, roll_degrees=roll, upright_geometry=upright))
    return faces


def run(args):
    settings = load_config(args.config).get("selection", {})
    every = positive(args.sample_every if args.sample_every is not None else settings.get("sample_every", 5), "sample_every")
    top_n = positive(args.top_n if args.top_n is not None else settings.get("top_n", 20), "top_n")
    threshold = (None if args.top_n is not None else
                 args.threshold if args.threshold is not None else settings.get("threshold"))
    gap = args.min_gap if args.min_gap is not None else settings.get("min_gap_seconds", 1.0)
    if gap < 0 or (threshold is not None and not 0 <= threshold <= 100):
        raise ValueError("gap must be >= 0; threshold must be between 0 and 100")
    model = Path(args.model).resolve()
    ensure_model(model)
    video = Path(args.video).resolve()
    output = Path(args.output).resolve() if args.output else video_output_dir(video)
    if (output / "frames.json").exists():
        raise ValueError("Output already contains frames.json; choose a new --output directory")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps <= 0:
        cap.release()
        raise ValueError("Video does not report a usable FPS")
    output.mkdir(parents=True, exist_ok=True)
    crop_first = settings.get("crop_before_scoring", False)
    export_crop = settings.get("export_face_crop", True)
    auto_rotate = settings.get("auto_rotate_faces", True)
    max_faces = positive(settings.get("max_faces", 5), "max_faces")
    min_face_size = positive(settings.get("min_face_size", 40), "min_face_size")
    if not all(isinstance(value, bool) for value in (crop_first, export_crop, auto_rotate)):
        cap.release()
        raise ValueError("crop_before_scoring, export_face_crop and auto_rotate_faces must be JSON booleans")
    face_detector = None
    if crop_first:
        detector_model = model.parent / "blaze_face_short_range.tflite"
        ensure_model(detector_model, DETECTOR_URL)
        face_detector = mp.tasks.vision.FaceDetector.create_from_options(
            mp.tasks.vision.FaceDetectorOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(detector_model)),
                running_mode=mp.tasks.vision.RunningMode.IMAGE))
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_faces=1 if crop_first else max_faces,
        output_face_blendshapes=True)
    candidates, index, sampled = [], 0, 0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    total_samples = math.ceil(frame_count / every) if math.isfinite(frame_count) and frame_count > 0 else None
    try:
        with mp.tasks.vision.FaceLandmarker.create_from_options(options) as detector, (output / "scores.jsonl").open("w", encoding="utf-8") as log, tqdm(total=total_samples, desc="Step 1: scoring", unit="sample") as progress:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if index % every == 0:
                    sampled += 1
                    faces = score_faces(frame, detector, face_detector, max_faces, min_face_size, auto_rotate)
                    row = dict(frame_index=index, timestamp_seconds=index / fps,
                               score=max((f["score"] for f in faces), default=None), faces=faces)
                    log.write(json.dumps(row) + "\n")
                    if faces:
                        best = max(faces, key=lambda f: f["score"])
                        candidates.append(dict(frame_index=index, timestamp_seconds=index / fps,
                                               score=best["score"], face=best, face_count=len(faces)))
                    progress.update(1)
                    progress.set_postfix(faces=len(faces), refresh=False)
                index += 1
    finally:
        cap.release()
        if face_detector is not None:
            face_detector.close()
    selected = select_frames(candidates, top_n, threshold, gap)
    wanted = {r["frame_index"]: r for r in selected}
    (output / "frames").mkdir(exist_ok=True)
    # Decode again in order so exported frames exactly match the scored indices.
    cap = cv2.VideoCapture(str(video))
    try:
        for i in tqdm(range(max(wanted, default=-1) + 1), desc="Step 1: exporting", unit="frame"):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Video ended while exporting selected frames")
            if i in wanted:
                item = wanted[i]
                h, w = frame.shape[:2]
                x1, y1, x2, y2 = crop_bounds(item["face"]["bbox"], w, h)
                crop = frame[y1:y2, x1:x2] if export_crop else frame
                rotation = item["face"]["rotation_degrees"] if export_crop and auto_rotate else 0
                crop = rotate_face(crop, rotation)
                name = f"frame_{i:08d}"
                for suffix, pixels in (("", crop), ("_full", frame)):
                    cv2.imencode(".png", pixels)[1].tofile(str(output / "frames" / f"{name}{suffix}.png"))
                item.update(id=name, image=f"frames/{name}.png", full_image=f"frames/{name}_full.png",
                            rotation_degrees=rotation)
    finally:
        cap.release()
    manifest = dict(schema_version=1, video=str(video), fps=fps, decoded_frames=index,
                    sampled_frames=sampled, selection=dict(sample_every=every, top_n=top_n,
                    threshold=threshold, min_gap_seconds=gap, crop_before_scoring=crop_first,
                    export_face_crop=export_crop, auto_rotate_faces=auto_rotate), frames=selected)
    write_json(output / "frames.json", manifest)
    print(f"Selected {len(selected)} frames from {sampled} samples: {output / 'frames.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--output", help="Override default output: <project>/output/<video stem>/")
    parser.add_argument("--model", default=str(ROOT / "models" / "face_landmarker.task"))
    parser.add_argument("--sample-every", type=int)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--top-n", type=int)
    group.add_argument("--threshold", type=float)
    parser.add_argument("--min-gap", type=float)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
