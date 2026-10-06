"""Render selected images and captions into chat-ready meme files."""
import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from tqdm import tqdm

from common import ROOT, default_font, image_path, load_config, positive, read_json, resolve_manifest, write_json

STYLES = ("red_box", "bottom_bar", "white_text", "black_text")


def fit_caption(text, width, font_path, preferred_size, max_height=None, stroke_width=0):
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(preferred_size, 11, -1):
        font = ImageFont.truetype(str(font_path), size)
        lines, current = [], ""
        for character in text:
            bounds = scratch.textbbox((0, 0), current + character, font=font, stroke_width=stroke_width)
            if bounds[2] - bounds[0] > width:
                if not current:
                    break
                lines.append(current)
                current = character
            else:
                current += character
        else:
            if current:
                lines.append(current)
            heights = [font.getbbox(line, stroke_width=stroke_width)[3] -
                       font.getbbox(line, stroke_width=stroke_width)[1] for line in lines]
            total_height = sum(heights) + max(0, len(lines) - 1) * 4
            if len(lines) <= 2 and (max_height is None or total_height <= max_height):
                return font, lines
    raise ValueError("Caption is too long to fit; shorten it or increase export.max_side")


def render(source, caption, font_path, font_size, max_side, style="red_box",
           background_color="#ff3b30", corner_radius=12, text_margin=12, stroke_width=0):
    if style not in STYLES:
        raise ValueError(f"Unknown style: {style}; choose from {', '.join(STYLES)}")
    if min(corner_radius, text_margin, stroke_width) < 0:
        raise ValueError("corner_radius, text_margin and stroke_width must be >= 0")
    with Image.open(source) as original:
        picture = original.convert("RGB")
    if style != "bottom_bar":
        picture = ImageOps.contain(picture, (max_side, max_side), method=Image.Resampling.LANCZOS)
        width, height = picture.size
        margin = max(4, min(text_margin, min(width, height) // 8))
        box_padding = margin if style == "red_box" else 0
        font, lines = fit_caption(caption, width - 2 * (margin + box_padding), font_path,
                                  font_size, height - 2 * (margin + box_padding), stroke_width)
        draw = ImageDraw.Draw(picture)
        bounds = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width) for line in lines]
        line_heights = [box[3] - box[1] for box in bounds]
        text_height = sum(line_heights) + 4 * (len(lines) - 1)
        text_width = max(box[2] - box[0] for box in bounds)
        top = height - margin - box_padding - text_height
        if style == "red_box":
            draw.rounded_rectangle((max(0, (width - text_width) / 2 - box_padding),
                                    top - box_padding,
                                    min(width - 1, (width + text_width) / 2 + box_padding),
                                    height - margin), radius=corner_radius, fill=background_color)
        color = "white" if style == "white_text" else "black"
        outline = "black" if color == "white" else "white"
        for line, box, line_height in zip(lines, bounds, line_heights):
            draw.text(((width - (box[2] - box[0])) / 2 - box[0], top - box[1]),
                      line, font=font, fill=color, stroke_width=stroke_width, stroke_fill=outline)
            top += line_height + 4
        return picture
    # Reserve space for a caption while keeping the complete output within max_side.
    picture.thumbnail((max_side, max(32, max_side - font_size * 3)))
    width = max(picture.width, min(max_side, 256))
    padding = max(8, width // 32)
    font, lines = fit_caption(caption, width - padding * 2, font_path, font_size)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 4
    band = line_height * len(lines) + padding * 2
    canvas = Image.new("RGB", (width, picture.height + band), "white")
    canvas.paste(picture, ((width - picture.width) // 2, 0))
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        draw.text((width / 2, picture.height + padding + line_height * index),
                  line, font=font, fill="black", anchor="mt")
    return ImageOps.contain(canvas, (max_side, max_side), method=Image.Resampling.LANCZOS)


def run(args):
    config = load_config(args.config).get("export", {})
    manifest_path = resolve_manifest(args.manifest, getattr(args, "video", None))
    manifest = read_json(manifest_path)
    captions_path = Path(args.captions).resolve() if args.captions else manifest_path.parent / "captions.json"
    captions = read_json(captions_path)["captions"]
    output = Path(args.output).resolve() if args.output else manifest_path.parent / "memes"
    font_value = args.font or config.get("font_path")
    font_path = Path(font_value) if font_value else default_font()
    if font_path is None:
        raise ValueError("Chinese font not found; set export.font_path or --font")
    if not font_path.is_absolute():
        font_path = Path(args.config).resolve().parent / font_path
    if not font_path.is_file():
        raise ValueError("Chinese font not found; set export.font_path or --font")
    max_side = int(config.get("max_side", 768))
    if max_side < 128:
        raise ValueError("max_side must be >= 128")
    formats = config.get("formats", [config["format"]] if "format" in config else ["jpg", "gif"])
    if not isinstance(formats, list) or not formats or not all(isinstance(fmt, str) for fmt in formats):
        raise ValueError("export.formats must be a nonempty list of format names")
    formats = list(dict.fromkeys(fmt.lower() for fmt in formats))
    if any(fmt not in ("png", "jpg", "jpeg", "webp", "gif") for fmt in formats):
        raise ValueError("formats must contain only png, jpg, jpeg, webp or gif")
    style = getattr(args, "style", None) or config.get("style", "red_box")
    if style not in STYLES:
        raise ValueError(f"Unknown export.style: {style}")
    font_size_key = "red_box_font_size" if style == "red_box" else "font_size"
    font_size = positive(int(config.get(font_size_key, 48)), font_size_key)
    # if font_size < 12:
    #     raise ValueError(f"{font_size_key} must be >= 12")
    style_options = dict(style=style, background_color=config.get("background_color", "#ff3b30"),
                         corner_radius=int(config.get("corner_radius", 12)),
                         text_margin=int(config.get("text_margin", 12)),
                         stroke_width=int(config.get("stroke_width", 0)))
    ready, missing = [], []
    for item in manifest["frames"]:
        entry = captions.get(item["id"])
        if entry is None:
            missing.append(item["id"])
            continue
        source = image_path(manifest_path, item)
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry.get("image_sha256"):
            raise ValueError(f"Image changed since captioning: {item['id']}; rerun step2")
        if not isinstance(entry.get("caption"), str) or not entry["caption"].strip():
            raise ValueError(f"Invalid caption: {item['id']}")
        ready.append((item, source, entry["caption"]))
    if missing and not args.allow_partial:
        raise ValueError(f"{len(missing)} captions missing; rerun step2 or use --allow-partial")
    output.mkdir(parents=True, exist_ok=True)
    exported = []
    for item, source, caption in tqdm(ready, desc="Step 3: memes", unit="image"):
        picture = render(source, caption, font_path, font_size, max_side, **style_options)
        files = []
        for fmt in formats:
            destination = output / f"{item['id']}.{fmt}"
            if fmt == "gif":
                picture.convert("P", palette=Image.Palette.ADAPTIVE).save(destination, optimize=True)
            else:
                picture.save(destination, **({"quality": 95} if fmt != "png" else {}))
            files.append(destination.name)
        exported.append(dict(id=item["id"], file=files[0], files=files, caption=caption,
                             score=item["score"], timestamp_seconds=item["timestamp_seconds"]))
    write_json(output / "index.json", dict(style=style, formats=formats, memes=exported, missing_captions=missing))
    print(f"Exported {len(exported)} memes ({len(exported) * len(formats)} files): {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", help="Video path/name used in step1 (extension optional)")
    parser.add_argument("--manifest", help="Explicit frames.json path")
    parser.add_argument("--captions")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--output")
    parser.add_argument("--font")
    parser.add_argument("--style", choices=STYLES, help="Override export.style")
    parser.add_argument("--allow-partial", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
