"""Interactive configuration, venv bootstrap and sequential video batch runner."""
import argparse
from copy import deepcopy
from datetime import datetime
from getpass import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

from common import ROOT, default_font, read_json, write_json

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".wmv", ".flv", ".mts", ".m2ts"}
MODULES = ("mediapipe", "cv2", "numpy", "PIL", "requests", "tqdm")


def merge_defaults(current, defaults):
    if not isinstance(current, dict):
        raise ValueError("config.json 必须是 JSON 对象")
    for key, value in defaults.items():
        if key not in current:
            current[key] = deepcopy(value)
        elif isinstance(value, dict):
            if not isinstance(current[key], dict):
                raise ValueError(f"配置分组 {key} 必须是 JSON 对象")
            merge_defaults(current[key], value)
    return current


def config_errors(config):
    errors = []
    def number(section, field, minimum, integer=False, nullable=False, maximum=None):
        value = config[section].get(field)
        if nullable and value is None:
            return
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value < minimum or (integer and not isinstance(value, int)) or
                (maximum is not None and value > maximum)):
            errors.append(f"{section}.{field}: 需要{'整数' if integer else '数字'}，范围 {minimum} 至 {maximum or '不限'}")
    api = config["api"]
    url = urlparse(api.get("base_url", "") if isinstance(api.get("base_url"), str) else "")
    if url.scheme not in ("http", "https") or not url.netloc or url.path.rstrip("/").endswith("/chat/completions"):
        errors.append("api.base_url: 需要有效接口基础地址，不包含 /chat/completions")
    for field in ("api_key", "model"):
        value = api.get(field)
        if not isinstance(value, str) or not value.strip() or value == "YOUR_API_KEY":
            errors.append(f"api.{field}: 必须填写")
    number("api", "timeout_seconds", 1)
    number("api", "max_retries", 0, True)
    for field in ("sample_every", "top_n", "max_faces", "min_face_size"):
        number("selection", field, 1, True)
    number("selection", "threshold", 0, nullable=True, maximum=100)
    number("selection", "min_gap_seconds", 0)
    for field in ("crop_before_scoring", "export_face_crop", "auto_rotate_faces"):
        if not isinstance(config["selection"].get(field), bool):
            errors.append(f"selection.{field}: 需要 true 或 false")
    number("caption", "max_chars", 1, True)
    if not isinstance(config["caption"].get("context"), str):
        errors.append("caption.context: 需要字符串")
    prompt = config["caption"].get("prompt")
    if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
        errors.append("caption.prompt: 需要非空字符串或 null")
    export = config["export"]
    if export.get("style") not in ("red_box", "bottom_bar", "white_text", "black_text"):
        errors.append("export.style: 请选择 red_box/bottom_bar/white_text/black_text")
    for field in ("font_size", "red_box_font_size"):
        number("export", field, 12, True)
    number("export", "max_side", 128, True)
    for field in ("corner_radius", "text_margin", "stroke_width"):
        number("export", field, 0, True)
    formats = export.get("formats")
    if not isinstance(formats, list) or not formats or any(fmt not in ("jpg", "jpeg", "gif", "png", "webp") for fmt in formats):
        errors.append("export.formats: 需要非空格式列表，如 [\"jpg\", \"gif\"]")
    color = export.get("background_color")
    if not isinstance(color, str) or len(color) != 7 or not color.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
        errors.append("export.background_color: 需要 #RRGGBB 颜色")
    font = export.get("font_path")
    if font is not None:
        if not isinstance(font, str):
            errors.append("export.font_path: 需要字体路径或 null")
        else:
            path = Path(font)
            if not path.is_absolute():
                path = ROOT / path
            if not path.is_file():
                errors.append("export.font_path: 字体文件不存在，可设 null 自动选择系统中文字体")
    elif default_font() is None:
        errors.append("export.font_path: 未找到中文字体，请填写 .ttf/.ttc 文件路径")
    return errors


def prepare_config(path, interactive=True):
    defaults = read_json(ROOT / "config.example.json")
    if path.exists():
        config = read_json(path)  # Invalid JSON is never silently overwritten.
    else:
        config = {}
    original = deepcopy(config)
    # Preserve legacy single-format choices when completing the configuration.
    if isinstance(config.get("export"), dict) and "format" in config["export"] and "formats" not in config["export"]:
        config["export"]["formats"] = [config["export"]["format"]]
    merge_defaults(config, defaults)
    font = config["export"].get("font_path")
    if isinstance(font, str) and font and not Path(font).is_absolute():
        config["export"]["font_path"] = str((path.parent / font).resolve())
    if interactive:
        for field, label in (("base_url", "API 基础地址"), ("api_key", "API key（输入隐藏）"), ("model", "视觉模型名")):
            value = original.get("api", {}).get(field)
            if not isinstance(value, str) or not value.strip() or value == "YOUR_API_KEY":
                entered = getpass(f"{label}: ") if field == "api_key" else input(f"{label} [{config['api'][field]}]: ").strip()
                if entered.strip():
                    config["api"][field] = entered.strip()
        font = config["export"].get("font_path")
        if isinstance(font, str) and not (Path(font) if Path(font).is_absolute() else ROOT / font).is_file() and default_font():
            print("原字体路径在此系统不存在，已改为自动选择系统中文字体。")
            config["export"]["font_path"] = None
    if config != original or not path.exists():
        write_json(path, config)
        print(f"配置已补全并保存：{path}（已有 API 配置保留）")
    while errors := config_errors(config):
        print("配置需要修正：\n- " + "\n- ".join(errors))
        if not interactive:
            raise ValueError("配置检查失败；请修正 config.json，或不带 --non-interactive 运行向导")
        print("输入字段路径可直接修改（如 selection.top_n），或输入 q 退出后编辑文件。")
        field_path = input("要修改的字段: ").strip()
        if field_path.lower() == "q":
            raise ValueError("请修改配置后重新运行")
        try:
            section, field = field_path.split(".", 1)
            if section not in defaults or field not in defaults[section]:
                raise ValueError()
            value = getpass("API key: ") if field == "api_key" else input("新值（字符串可直接输入；数字/布尔/列表/null 用 JSON）: ")
            string_fields = {"base_url", "api_key", "model", "context", "style", "background_color"}
            config[section][field] = value if field in string_fields else (value if field in ("font_path", "prompt") and value != "null" else json.loads(value))
            write_json(path, config)
        except (ValueError, KeyError):
            print("字段或值格式不正确，请重试。")
    print("配置检查通过。")
    return config


def checked_call(command, **kwargs):
    subprocess.run([str(item) for item in command], check=True, cwd=ROOT, **kwargs)


def ensure_environment():
    venv_dir = ROOT / ".venv"
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    probe = "import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) and sys.prefix != sys.base_prefix else 1)"
    if python.exists():
        if subprocess.run([str(python), "-c", probe], capture_output=True).returncode:
            raise ValueError("现有 .venv 无法使用，请将其重命名为备份后重新运行")
    else:
        if venv_dir.exists():
            raise ValueError(".venv 与当前系统不兼容，请将其重命名为备份后重新运行")
        print("创建 Python 虚拟环境…")
        checked_call([sys.executable, "-m", "venv", venv_dir])
    fingerprint = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    marker = venv_dir / ".facememe-requirements"
    import_probe = "import mediapipe, cv2, numpy, PIL, requests, tqdm"
    ready = subprocess.run([str(python), "-c", import_probe], capture_output=True).returncode == 0
    if not ready or not marker.exists() or marker.read_text().strip() != fingerprint:
        print("安装/检查运行依赖（首次可能需要几分钟，保留安装进度）…")
        checked_call([python, "-m", "pip", "install", "--disable-pip-version-check", "--retries", "2", "--timeout", "60", "-r", ROOT / "requirements.txt"])
        checked_call([python, "-c", import_probe])
        marker.write_text(fingerprint)
    return python


def video_digest(video):
    digest = hashlib.sha256()
    with video.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def process_videos(python, config_path, config, input_dir):
    from tqdm import tqdm
    videos = sorted((p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS), key=lambda p: p.name.casefold())
    if not videos:
        print(f"未发现视频。请把视频放到 {input_dir} 后重新运行。")
        return 0
    names = [video.stem.casefold() for video in videos]
    if len(names) != len(set(names)):
        raise ValueError("input 内有重复视频名（忽略扩展名和大小写），请重命名后运行")
    # Verify colors and actual font loading before performing any paid API calls.
    from PIL import ImageColor, ImageFont
    ImageColor.getrgb(config["export"]["background_color"])
    font = config["export"].get("font_path")
    font = (Path(font) if Path(font).is_absolute() else ROOT / font) if font else default_font()
    ImageFont.truetype(str(font), 16)
    report = []
    for video in tqdm(videos, desc="All videos", unit="video"):
        output = ROOT / "output" / video.stem
        stage = "step1"
        tqdm.write(f"\n开始处理：{video.name}")
        try:
            identity = dict(video_sha256=video_digest(video), selection=config["selection"],
                            step1_sha256=hashlib.sha256((ROOT / "step1.py").read_bytes()).hexdigest())
            for state_path in sorted((ROOT / "output").glob("*/batch_state.json"), reverse=True):
                if state_path.parent.name != video.stem and not state_path.parent.name.startswith(video.stem + "_"):
                    continue
                try:
                    if read_json(state_path) == identity and (state_path.parent / "frames.json").is_file():
                        output = state_path.parent
                        break
                except (OSError, ValueError):
                    continue
            if (output / "frames.json").exists():
                if not (output / "batch_state.json").exists() or read_json(output / "batch_state.json") != identity:
                    # Never reuse old frames for changed videos/settings or overwrite manual runs.
                    output = output.with_name(output.name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
                    tqdm.write(f"已有结果不匹配或来自手动运行，新结果保存到：{output}")
                else:
                    frame_manifest = read_json(output / "frames.json")
                    if any(not (output / item["image"]).is_file() for item in frame_manifest["frames"]):
                        output = output.with_name(output.name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            if not (output / "frames.json").exists():
                checked_call([python, "-u", ROOT / "step1.py", video, "--config", config_path, "--output", output])
                write_json(output / "batch_state.json", identity)
            else:
                tqdm.write("step1：复用同一视频、同一筛选配置的完整抽帧结果。")
            stage = "step2"
            command = [python, "-u", ROOT / "step2.py", "--manifest", output / "frames.json", "--config", config_path]
            caption_code = subprocess.run([str(item) for item in command], cwd=ROOT).returncode
            if caption_code not in (0, 1):
                raise RuntimeError(f"step2 退出码 {caption_code}")
            # If some captions failed, preserve successes and export those images.
            stage = "step3"
            command = [python, "-u", ROOT / "step3.py", "--manifest", output / "frames.json", "--config", config_path]
            if caption_code:
                command.append("--allow-partial")
            checked_call(command)
            status = "partial" if caption_code else "ok"
            report.append(dict(video=video.name, output=str(output), status=status))
            tqdm.write(f"{'部分完成（有配文失败）' if caption_code else '完成'}：{output / 'memes'}")
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            # Avoid printing provider responses or any configuration values.
            tqdm.write(f"{video.name} 的 {stage} 失败（{type(error).__name__}）；继续下一个视频。")
            report.append(dict(video=video.name, output=str(output), status="failed", stage=stage))
        write_json(ROOT / "output" / "batch_report.json", report)
    failed = sum(item["status"] != "ok" for item in report)
    print(f"处理结束：{len(report) - failed} 个完整成功，{failed} 个失败或部分成功。报告：output/batch_report.json")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--input", default=str(ROOT / "input"))
    parser.add_argument("--non-interactive", action="store_true", help="Validate configuration without asking questions")
    parser.add_argument("--check-config", action="store_true", help="Only complete and validate configuration")
    args = parser.parse_args()
    if sys.version_info[:2] not in ((3, 11), (3, 12)):
        print("请安装并使用 Python 3.11 或 3.12（推荐3.11）。")
        return 1
    try:
        config_path = Path(args.config).resolve()
        input_dir = Path(args.input).resolve()
        input_dir.mkdir(parents=True, exist_ok=True)
        config = prepare_config(config_path, not args.non_interactive and sys.stdin.isatty())
        if args.check_config:
            return 0
        python = ensure_environment()
        return process_videos(python, config_path, config, input_dir)
    except KeyboardInterrupt:
        print("\n已中断。已保存结果保留，可再次运行继续。")
        return 130
    except (OSError, ValueError, EOFError, subprocess.CalledProcessError) as error:
        print(f"启动失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
