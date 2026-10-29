# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow>=12", "pillow-heif>=1", "numpy>=2", "opencv-python-headless>=4.13,<5", "mcp>=2.3,<3", "tzdata>=2025.2; sys_platform == 'win32'"]
# ///
"""みてねの月版の考え方を参考に、写真と動画から月ごとの1秒ダイジェストを作る。

uv run --script monthly.py -i input -o output --month 2026-09 --audio bgm.wav
既存のmain.pyの顔識別用モデルやGUIを読み込まずに実行できる。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
PHOTOS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEOS = {".mp4", ".mov", ".m4v", ".avi", ".mts", ".3gp"}
JST = ZoneInfo("Asia/Tokyo")
MUSIC_PROMPT = (
    "Warm intimate acoustic family memories instrumental, gentle felt piano melody, "
    "soft fingerpicked acoustic guitar, delicate glockenspiel, light brushed percussion, "
    "tender joyful nostalgic mood, natural acoustic sound, simple coherent melody, "
    "gentle beginning and peaceful resolved ending, no vocals"
)


@dataclass
class Media:
    path: Path
    taken_at: datetime
    date_source: str
    photo: bool
    start: float = 0.0
    score: float = 0.0


def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} が失敗しました:\n{result.stderr[-3000:]}")
    return result.stdout


def probe(path):
    return json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                path,
            ]
        )
    )


def parse_date(value):
    value = value.strip()
    # EXIFとISO 8601の両方を受け取る。
    if re.match(r"^\d{4}:\d{2}:\d{2}", value):
        value = value[:10].replace(":", "-") + value[10:]
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(JST).replace(tzinfo=None) if dt.tzinfo else dt


def filename_date(path):
    match = re.search(
        r"(?<!\d)(20\d{2})[-_]?(\d{2})[-_]?(\d{2})(?:[T _-]?(\d{2})(\d{2})(\d{2}))?(?!\d)",
        path.stem,
    )
    if match:
        try:
            return datetime(*[int(v or 0) for v in match.groups()])
        except ValueError:
            pass
    return None


def capture_date(path, info=None):
    if path.suffix.lower() in PHOTOS:
        with Image.open(path) as image:
            exif = image.getexif()
            tags = dict(exif)
            if 34665 in exif:
                tags.update(exif.get_ifd(34665))
            for tag, offset_tag in ((36867, 36881), (36868, 36882), (306, 36880)):
                if tags.get(tag):
                    try:
                        value = str(tags[tag])
                        offset = str(tags.get(offset_tag, "")).strip()
                        if re.fullmatch(r"[+-]\d{2}:\d{2}", offset):
                            value += offset
                        return parse_date(value), "exif"
                    except ValueError:
                        continue
    else:
        info = info or probe(path)
        tag_sets = [s.get("tags", {}) for s in info.get("streams", [])] + [
            info.get("format", {}).get("tags", {})
        ]
        # ストリームのcreation_timeが編集・書き出し日時の場合もあるため、
        # 元の撮影日時タグを、全タグ集合から先に探す。
        for key in ("com.apple.quicktime.creationdate", "creation_time", "date"):
            for tags in tag_sets:
                if tags.get(key):
                    try:
                        return parse_date(tags[key]), key
                    except ValueError:
                        continue
    dt = filename_date(path)
    return (dt, "filename") if dt else None


def frame_score(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (240, max(1, round(gray.shape[0] * 240 / gray.shape[1]))))
    sharp = min(math.log1p(cv2.Laplacian(gray, cv2.CV_64F).var()) / 9, 1)
    exposure = 1 - abs(float(gray.mean()) - 128) / 128
    if not hasattr(frame_score, "detector"):
        frame_score.detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    faces = frame_score.detector.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24)
    )
    area = max((w * h for x, y, w, h in faces), default=0) / gray.size
    return sharp * 0.25 + exposure * 0.15 + min(area * 5, 1) * 0.6


def best_scene(path, photo, duration=0):
    if photo:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((480, 480))
            return 0.0, frame_score(cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR))
    cap = cv2.VideoCapture(str(path))
    best = (0.0, -1.0)
    try:
        # 長い動画でも最大12場面。最後の1秒を確保してから選定する。
        for start in np.linspace(
            0, max(0, duration - 1), min(12, max(1, math.ceil(duration)))
        ):
            cap.set(
                cv2.CAP_PROP_POS_MSEC, (float(start) + min(0.5, duration / 2)) * 1000
            )
            ok, frame = cap.read()
            if ok:
                score = frame_score(frame)
                if score > best[1]:
                    best = (float(start), score)
    finally:
        cap.release()
    if best[1] < 0:
        raise ValueError("動画をデコードできません")
    return best


def read_manifest(path):
    records = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"path", "taken_at"}.issubset(reader.fieldnames or []):
            raise ValueError("CSVにはpath,taken_at列が必要です")
        for row in reader:
            p = Path(row["path"]).expanduser()
            p = (path.parent / p).resolve() if not p.is_absolute() else p.resolve()
            if not p.is_file():
                raise ValueError(f"素材が見つかりません: {p}")
            start = float(row["start_seconds"]) if row.get("start_seconds") else None
            if start is not None and (not math.isfinite(start) or start < 0):
                raise ValueError("start_secondsは0以上の有限数にしてください")
            if p in records:
                raise ValueError(f"CSV内で素材が重複しています: {p.name}")
            records[p] = (parse_date(row["taken_at"]), start)
    return records


def scan_media(folder, manifest=None, exclude=None):
    folder = folder.resolve()
    overrides = read_manifest(manifest.resolve()) if manifest else {}
    paths = sorted(overrides) if manifest else sorted(folder.rglob("*"))
    media, skipped, hashes = [], [], set()
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in PHOTOS | VIDEOS:
            continue
        if exclude and path.resolve().is_relative_to(exclude.resolve()):
            continue
        try:
            info = None if path.suffix.lower() in PHOTOS else probe(path)
            dated = (
                (overrides[path][0], "manifest")
                if path in overrides
                else capture_date(path, info)
            )
            if not dated:
                raise ValueError(
                    "撮影日不明。みてねの撮影日をCSVのtaken_at列に指定してください（更新日時は使いません）"
                )
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest in hashes:
                raise ValueError("同じ内容の素材が重複しています")
            photo = path.suffix.lower() in PHOTOS
            duration = 0 if photo else float(info["format"]["duration"])
            start, score = best_scene(path, photo, duration)
            if path in overrides and overrides[path][1] is not None:
                start = overrides[path][1]
                if not photo and start >= duration:
                    raise ValueError("start_secondsが動画の長さ以上です")
            hashes.add(digest)
            media.append(Media(path, *dated, photo, start, score))
        except (ValueError, OSError, RuntimeError, KeyError) as exc:
            skipped.append({"path": str(path), "reason": str(exc)})
    return media, skipped


def evenly(items, count):
    if count >= len(items):
        return items
    if count == 1:
        return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def select_month(media, limit=20):
    if limit < 1:
        raise ValueError("素材数は1以上にしてください")
    # 動画を基本にする。写真は動画が不足する分だけ補う。
    videos = [m for m in media if not m.photo]
    photos = [m for m in media if m.photo]
    if videos and photos:
        chosen = select_month(videos, limit)
        if len(chosen) < limit:
            chosen += select_month(photos, limit - len(chosen))
        return sorted(chosen, key=lambda m: (m.taken_at, str(m.path)))
    days = defaultdict(list)
    for m in sorted(media, key=lambda m: (m.taken_at, str(m.path))):
        days[m.taken_at.date()].append(m)
    representatives = [max(items, key=lambda m: m.score) for items in days.values()]
    chosen = evenly(representatives, limit)
    if len(chosen) < min(limit, len(media)):
        used = {m.path for m in chosen}
        rest = sorted(
            (m for m in media if m.path not in used),
            key=lambda m: (m.taken_at, str(m.path)),
        )
        chosen += evenly(rest, min(limit - len(chosen), len(rest)))
    return sorted(chosen, key=lambda m: (m.taken_at, str(m.path)))


def font(size):
    for p in (
        Path(__file__).parent / "assets/NotoSansJP-Regular.ttf",
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def overlay_png(path, width, height, date, title=None):
    overlay = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(overlay)
    margin = round(width * 0.06)
    draw.text(
        (margin, height - margin),
        date.strftime("%Y.%m.%d"),
        anchor="ls",
        fill="white",
        font=font(max(12, round(width * 0.033))),
        stroke_width=1,
        stroke_fill="#00000090",
    )
    if title:
        draw.text(
            (width // 2, round(height * 0.1)),
            title,
            anchor="mt",
            fill="white",
            font=font(round(width * 0.075)),
            stroke_width=1,
            stroke_fill="#00000090",
        )
    overlay.save(path)


def render_clip(item, output, work, index, width, height):
    source = item.path
    if item.photo:
        # HEICとEXIF回転をPillow側で正規化し、FFmpegの環境差を避ける。
        source = work / f"still-{index}.png"
        with Image.open(item.path) as im:
            ImageOps.exif_transpose(im).convert("RGB").save(source)
        input_args = ["-loop", "1", "-framerate", "30", "-i", source]
        has_audio = False
    else:
        input_args = ["-ss", item.start, "-i", source]
        has_audio = any(s["codec_type"] == "audio" for s in probe(source)["streams"])
    caption = work / f"caption-{index}.png"
    overlay_png(
        caption,
        width,
        height,
        item.taken_at,
        item.taken_at.strftime("%Y / %m") if index < 2 else None,
    )
    inputs = input_args + ["-loop", "1", "-framerate", "30", "-i", caption]
    if not has_audio:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    audio = "0:a" if has_audio else "2:a"
    # 背景だけを切り抜き、手前の写真・動画は全体を見せる。
    graph = (
        "[0:v]setpts=PTS-STARTPTS,split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=20:2,setsar=1[blur];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[front];"
        "[blur][front]overlay=(W-w)/2:(H-h)/2,"
        "fps=30,tpad=stop_mode=clone:stop_duration=1,trim=duration=1,setpts=PTS-STARTPTS[base];"
        "[base][1:v]overlay=0:0,format=yuv420p[v];"
        f"[{audio}]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration=1[a]"
    )
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-n",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-video_track_timescale",
            "30000",
            output,
        ]
    )


def render_month(
    media,
    output,
    audio=None,
    width=540,
    height=960,
    original_volume=0.2,
    bgm_volume=0.8,
):
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"既存の動画は上書きしません: {output}")
    if not media:
        raise ValueError("対象素材がありません")
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (original_volume, bgm_volume)):
        raise ValueError("音量は0〜1の有限数にしてください")
    if audio and not audio.is_file():
        raise ValueError(f"BGMが見つかりません: {audio}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # 同時実行で他の処理の一時ファイルを消さない。完成したファイルだけを移す。
    with tempfile.TemporaryDirectory(prefix="monthly-", dir=output.parent) as td:
        work = Path(td)
        for index, item in enumerate(media):
            print(f"  {index + 1}/{len(media)}: {item.path.name}", flush=True)
            render_clip(item, work / f"clip-{index:03}.mov", work, index, width, height)
        concat = work / "clips.txt"
        concat.write_text(
            "".join(f"file 'clip-{i:03}.mov'\n" for i in range(len(media))),
            encoding="utf-8",
        )
        joined = work / "joined.mp4"
        # 映像は全クリップ同一設定。音声は連結時にサンプル数も合わせる。
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-n",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat,
                "-c:v",
                "copy",
                "-af",
                "aresample=48000:async=1:first_pts=0,apad",
                "-c:a",
                "aac",
                "-t",
                len(media),
                "-movflags",
                "+faststart",
                joined,
            ]
        )
        final = joined
        if audio:
            final = work / "final.mp4"
            duration = len(media)
            fade = min(2, duration / 2)
            graph = (
                f"[0:a]volume={original_volume},asplit=2[voice][key];"
                "[1:a]aresample=48000,loudnorm=I=-20:TP=-2:LRA=7,"
                f"atrim=duration={duration},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d={min(0.5, fade)},afade=t=out:st={duration-fade}:d={fade},volume={bgm_volume}[bgm];"
                "[bgm][key]sidechaincompress=threshold=0.03:ratio=2:attack=80:release=400:level_sc=1[ducked];"
                "[voice][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,aresample=48000[a]"
            )
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-n",
                    "-i",
                    joined,
                    "-stream_loop",
                    "-1",
                    "-i",
                    audio,
                    "-filter_complex",
                    graph,
                    "-map",
                    "0:v",
                    "-map",
                    "[a]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-ar",
                    "48000",
                    "-t",
                    duration,
                    "-movflags",
                    "+faststart",
                    final,
                ]
            )
        # コピー中の失敗や並行実行でも既存成果物を上書きしない。
        if not audio and original_volume != 1:
            final = work / "quiet.mp4"
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-n",
                    "-i",
                    joined,
                    "-c:v",
                    "copy",
                    "-af",
                    f"volume={original_volume}",
                    "-c:a",
                    "aac",
                    "-t",
                    len(media),
                    "-movflags",
                    "+faststart",
                    final,
                ]
            )
        os.link(final, output)


async def generate_bgm(python, output, seconds, seed=42):
    from mcp import Client, StdioServerParameters

    output = output.resolve()
    params = StdioServerParameters(
        command=str(python.resolve()),
        args=["-m", "audio_studio_mcp"],
        env={**os.environ, "AUDIO_STUDIO_OUTPUT_DIR": str(output)},
    )
    async with Client(params, read_timeout_seconds=1800) as client:
        result = await client.call_tool(
            "generate_audio",
            {
                "prompt": MUSIC_PROMPT,
                "audio_type": "music",
                "duration_seconds": seconds,
                "bpm": 90,
                "seed": seed,
                "title": "family-memories",
                "original_idea": "家族の月ごとの思い出を振り返る、温かいオリジナルBGM",
            },
        )
        content = "".join(getattr(c, "text", "") for c in result.content)
        if result.is_error:
            raise RuntimeError(f"BGM生成に失敗しました: {content}")
        generated = Path(json.loads(content)["candidates"][0]["path"])
        if not generated.is_file():
            raise RuntimeError("BGM生成結果のファイルがありません")
        await client.call_tool("unload_models", {})
        return generated


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-i", "--input", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--month", help="YYYY-MM。省略すると撮影日のある全月")
    parser.add_argument("--max-clips", type=int, default=20)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="みてねの撮影日を保存したCSV（path,taken_at,start_seconds）",
    )
    parser.add_argument("-a", "--audio", type=Path)
    parser.add_argument(
        "--audio-studio-python", type=Path, help="Audio Studio MCP導入済み環境のPython"
    )
    parser.add_argument(
        "--original-volume",
        type=float,
        default=0.2,
        help="元音声の音量（0〜1、既定0.2）",
    )
    parser.add_argument(
        "--bgm-volume",
        type=float,
        default=0.8,
        help="音量を整えたBGMの音量（0〜1、既定0.8）",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="選定結果だけ保存し、動画・BGMは生成しない",
    )
    args = parser.parse_args()
    if not args.input.is_dir():
        parser.error("入力フォルダがありません")
    if (
        args.input.resolve() == args.output.resolve()
        or args.input.resolve().is_relative_to(args.output.resolve())
    ):
        parser.error("出力は入力と分けてください（入力の親フォルダも不可）")
    if args.max_clips < 1:
        parser.error("--max-clipsは1以上にしてください")
    if not all(
        math.isfinite(v) and 0 <= v <= 1
        for v in (args.original_volume, args.bgm_volume)
    ):
        parser.error("音量は0〜1の有限数にしてください")
    if args.month:
        try:
            if datetime.strptime(args.month, "%Y-%m").strftime("%Y-%m") != args.month:
                raise ValueError
        except ValueError:
            parser.error("--monthはYYYY-MMで指定してください")
    if args.audio and args.audio_studio_python:
        parser.error("--audioと--audio-studio-pythonはどちらか一方を指定してください")
    if args.audio and not args.audio.is_file():
        parser.error("指定したBGMファイルがありません")
    if args.audio_studio_python and not args.audio_studio_python.is_file():
        parser.error("Audio Studio MCPのPythonがありません")
    if not all(shutil.which(c) for c in ("ffmpeg", "ffprobe")):
        parser.error("ffmpegとffprobeが必要です")
    args.output.mkdir(parents=True, exist_ok=True)
    media, skipped = scan_media(args.input, manifest=args.manifest, exclude=args.output)
    groups = defaultdict(list)
    for m in media:
        month = m.taken_at.strftime("%Y-%m")
        if not args.month or month == args.month:
            groups[month].append(m)
    if not groups:
        print(json.dumps({"skipped": skipped}, ensure_ascii=False, indent=2))
        parser.error(
            "指定月の素材がありません。撮影日不明の場合は--manifestで指定してください"
        )
    plans = {
        month: select_month(items, args.max_clips)
        for month, items in sorted(groups.items())
    }
    report = {
        "reference": "https://gihyo.jp/article/2023/07/mitene-07-1sec-movie",
        "selection": "撮影日の分散、顔の大きさ、鮮明さ、明るさ。みてね内部の選定アルゴリズムとは異なります。",
        "skipped": skipped,
        "months": {
            month: [
                {
                    "path": str(m.path),
                    "taken_at": m.taken_at.isoformat(),
                    "date_source": m.date_source,
                    "start_seconds": m.start,
                    "score": round(m.score, 4),
                }
                for m in items
            ]
            for month, items in plans.items()
        },
    }
    stamp = datetime.now(JST).strftime("%Y%m%d-%H%M%S-%f")
    report_path = args.output / f"selection-{stamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"選定結果: {report_path} / 除外: {len(skipped)}点", flush=True)
    if args.plan_only:
        return
    for month in plans:
        if (args.output / f"{month}-memories.mp4").exists():
            raise FileExistsError(
                f"既存の{month}の動画は上書きしません。別の出力フォルダを指定してください"
            )
    audio = args.audio
    if args.audio_studio_python:
        print("オリジナルBGMを生成中...", flush=True)
        audio = asyncio.run(
            generate_bgm(
                args.audio_studio_python,
                args.output / "music",
                max(map(len, plans.values())),
            )
        )
    for month, items in plans.items():
        output = args.output / f"{month}-memories.mp4"
        print(f"{month}: {len(items)}場面 / {len(items)}秒", flush=True)
        render_month(
            items,
            output,
            audio=audio,
            original_volume=args.original_volume,
            bgm_volume=args.bgm_volume,
        )
        print(f"保存: {output}", flush=True)
    if skipped:
        raise SystemExit(
            "一部の素材は除外されました。選定結果のskipped欄を確認してください。"
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileExistsError) as exc:
        raise SystemExit(str(exc))
