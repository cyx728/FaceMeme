import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def default_font():
    candidates = [Path("C:/Windows/Fonts/msyh.ttc"),
                  Path("/System/Library/Fonts/PingFang.ttc"),
                  Path("/System/Library/Fonts/STHeiti Medium.ttc"),
                  Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")]
    return next((path for path in candidates if path.is_file()), None)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_config(path):
    return read_json(path)


def positive(value, name):
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def image_path(manifest_path, item):
    return Path(manifest_path).resolve().parent / item["image"]


def video_output_dir(video):
    return ROOT / "output" / Path(video).stem


def resolve_manifest(manifest=None, video=None):
    if manifest and video:
        raise ValueError("Use either a video name or --manifest, not both")
    if manifest:
        return Path(manifest).resolve()
    if video:
        named_directory = ROOT / "output" / Path(video).name
        if (named_directory / "frames.json").is_file():
            return named_directory / "frames.json"
        return video_output_dir(video) / "frames.json"
    candidates = sorted((ROOT / "output").glob("*/frames.json"))
    if len(candidates) != 1:
        raise ValueError("Specify a video name or --manifest; automatic selection requires exactly one video output directory")
    return candidates[0]
