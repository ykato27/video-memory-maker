"""月別整理・選定・実際のFFmpeg出力を検証する。"""

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import monthly


def item(name, day, score=1, month=9):
    return monthly.Media(
        Path(name), datetime(2026, month, day), "manifest", True, 0, score
    )


def test_monthly_selection_spreads_days_and_preserves_order():
    media = [item(f"{day}-{n}.jpg", day, n) for day in range(1, 31) for n in range(3)]
    selected = monthly.select_month(media, 20)
    assert len(selected) == 20
    assert len({m.taken_at.day for m in selected}) == 20
    assert selected[0].taken_at.day == 1
    assert selected[-1].taken_at.day == 30
    assert all(m.score == 2 for m in selected)
    assert selected == sorted(selected, key=lambda m: (m.taken_at, str(m.path)))


def test_sparse_days_are_filled_without_repeating_media():
    media = [item(f"{day}-{n}.jpg", day, n) for day in (1, 15, 30) for n in range(10)]
    selected = monthly.select_month(media, 20)
    assert len(selected) == len({m.path for m in selected}) == 20
    assert {m.taken_at.day for m in selected} == {1, 15, 30}


def test_small_month_does_not_duplicate_or_invent_days():
    assert monthly.select_month([item("only.jpg", 17)], 20)[0].path == Path("only.jpg")


def test_videos_take_priority_over_higher_scoring_photos():
    videos = [
        monthly.Media(
            Path(f"v{d}.mp4"), datetime(2026, 9, d), "manifest", False, score=0
        )
        for d in range(1, 25)
    ]
    photos = [item(f"p{d}.jpg", d, score=10) for d in range(1, 25)]
    selected = monthly.select_month(videos + photos, 20)
    assert len(selected) == 20
    assert all(not m.photo for m in selected)


def test_photos_only_fill_missing_video_slots():
    videos = [
        monthly.Media(Path(f"v{d}.mp4"), datetime(2026, 9, d), "manifest", False)
        for d in range(1, 4)
    ]
    photos = [item(f"p{d}.jpg", d) for d in range(1, 25)]
    selected = monthly.select_month(videos + photos, 20)
    assert len(selected) == 20
    assert sum(not m.photo for m in selected) == 3


def test_capture_date_not_download_time(tmp_path):
    p = tmp_path / "random.jpg"
    exif = Image.Exif()
    exif[36867] = "2025:03:04 12:34:56"
    Image.new("RGB", (40, 60), "red").save(p, exif=exif)
    assert monthly.capture_date(p)[0] == datetime(2025, 3, 4, 12, 34, 56)
    unknown = tmp_path / "download.jpg"
    Image.new("RGB", (40, 60)).save(unknown)
    assert monthly.capture_date(unknown) is None


def test_filename_date_and_timezone():
    assert monthly.filename_date(Path("20260930_123456.JPG")) == datetime(
        2026, 9, 30, 12, 34, 56
    )
    assert monthly.parse_date("2026-09-30T23:30:00Z") == datetime(2026, 10, 1, 8, 30)
    assert monthly.filename_date(Path("bad-20261335.jpg")) is None


def test_video_original_date_has_priority_over_encoding_date():
    info = {
        "streams": [{"tags": {"creation_time": "2026-10-04T12:00:00Z"}}],
        "format": {
            "tags": {"com.apple.quicktime.creationdate": "2026-09-27T18:00:00+0900"}
        },
    }
    assert monthly.capture_date(Path("edited.mov"), info) == (
        datetime(2026, 9, 27, 18),
        "com.apple.quicktime.creationdate",
    )


def test_invalid_original_date_falls_back_to_creation_time():
    info = {
        "streams": [{"tags": {"creation_time": "2026-09-27T12:00:00Z"}}],
        "format": {"tags": {"com.apple.quicktime.creationdate": "invalid"}},
    }
    assert monthly.capture_date(Path("edited.mov"), info)[0] == datetime(
        2026, 9, 27, 21
    )


def test_photo_exif_offset_is_converted_to_japan_time(tmp_path):
    photo = tmp_path / "travel.jpg"
    exif = Image.Exif()
    exif[36867] = "2026:09:30 23:30:00"
    exif[36881] = "-07:00"  # OffsetTimeOriginal
    Image.new("RGB", (40, 60)).save(photo, exif=exif)
    assert monthly.capture_date(photo)[0] == datetime(2026, 10, 1, 15, 30)


def test_manifest_resolves_relative_paths_and_overrides_exif(tmp_path):
    image = tmp_path / "a.jpg"
    Image.new("RGB", (40, 60)).save(image)
    manifest = tmp_path / "dates.csv"
    manifest.write_text("path,taken_at,start_seconds\na.jpg,2026-09-03T12:00:00,0\n")
    media, skipped = monthly.scan_media(tmp_path, manifest=manifest)
    assert not skipped
    assert len(media) == 1
    assert media[0].taken_at == datetime(2026, 9, 3, 12)


def test_manifest_missing_file_is_error(tmp_path):
    manifest = tmp_path / "dates.csv"
    manifest.write_text("path,taken_at\nmissing.jpg,2026-09-03\n")
    with pytest.raises(ValueError, match="見つかりません"):
        monthly.scan_media(tmp_path, manifest=manifest)


def test_exact_duplicates_are_not_selected_twice(tmp_path):
    Image.new("RGB", (40, 60), "red").save(tmp_path / "20260901.jpg")
    shutil.copy2(tmp_path / "20260901.jpg", tmp_path / "20260902.jpg")
    media, skipped = monthly.scan_media(tmp_path)
    assert len(media) == 1
    assert any("重複" in s["reason"] for s in skipped)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpegが必要")
def test_real_render_mixed_stills_short_silent_video_and_audio(tmp_path):
    # 引用符・日本語を含むパスでも、音声の有無が混ざっても3秒になる。
    source = tmp_path / "家族's photos"
    source.mkdir()
    Image.new("RGB", (320, 180), "#cc8855").save(source / "20260901.JPG")
    video = source / "20260902.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x240:r=30:d=0.3",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
    )
    video2 = source / "20260903.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=240x160:r=30:d=1.3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(video2),
        ],
        check=True,
    )
    bgm = tmp_path / "bgm.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=0.5",
            str(bgm),
        ],
        check=True,
    )
    media, skipped = monthly.scan_media(source)
    assert not skipped
    out = tmp_path / "2026-09.mp4"
    monthly.render_month(media, out, audio=bgm, width=180, height=320)
    probe = monthly.probe(out)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (180, 320)
    assert int(v["nb_frames"]) == 90
    assert float(v["duration"]) == pytest.approx(3, abs=0.04)
    assert float(a["duration"]) == pytest.approx(3, abs=0.05)
    assert a["sample_rate"] == "48000"
    # 再実行で完成品を上書きしない。
    before = out.read_bytes()
    with pytest.raises(FileExistsError):
        monthly.render_month(media, out, audio=bgm, width=180, height=320)
    assert before == out.read_bytes()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpegが必要")
def test_original_sound_is_actually_quieter_than_full_volume(tmp_path):
    video = tmp_path / "20260901.mp4"
    bgm = tmp_path / "bgm.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x240:r=30:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=1.2",
            str(bgm),
        ],
        check=True,
    )
    media, _ = monthly.scan_media(tmp_path)
    amplitudes = []
    for volume in (1.0, 0.2):
        output = tmp_path / f"mix-{volume}.mp4"
        monthly.render_month(
            media, output, audio=bgm, width=180, height=320, original_volume=volume
        )
        raw = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output),
                "-ss",
                "0.2",
                "-t",
                "0.6",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-f",
                "f32le",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout
        samples = np.frombuffer(raw, dtype=np.float32)
        wave = np.exp(-2j * np.pi * 440 * np.arange(len(samples)) / 48000)
        amplitudes.append(abs((samples * wave).sum()))
    assert amplitudes[1] / amplitudes[0] == pytest.approx(0.2, abs=0.03)
