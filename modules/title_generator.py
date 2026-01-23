"""テロップ（タイトル）動画生成モジュール"""

import cv2
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    OUTPUT_FPS,
    TITLE_DURATION,
    TITLE_FONT_PATH,
    TITLE_FONT_SIZE,
    TITLE_BG_COLOR,
    TITLE_TEXT_COLOR,
)


@dataclass
class TitleConfig:
    """テロップ設定を保持するクラス"""

    text: str  # 表示テキスト（複数行対応）
    duration: float = TITLE_DURATION  # 表示秒数
    width: int = OUTPUT_WIDTH  # 動画幅
    height: int = OUTPUT_HEIGHT  # 動画高さ
    fps: int = OUTPUT_FPS  # フレームレート
    font_path: str = None  # フォントファイルパス
    font_size: int = TITLE_FONT_SIZE  # フォントサイズ
    bg_color: str = TITLE_BG_COLOR  # 背景色
    text_color: str = TITLE_TEXT_COLOR  # 文字色

    def __post_init__(self):
        if self.font_path is None:
            self.font_path = str(TITLE_FONT_PATH)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """
    16進数カラーコードをRGB形式に変換

    引数:
        hex_color: "#FFFFFF"形式のカラーコード
    戻り値:
        (R, G, B)のタプル
    """
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    """
    16進数カラーコードをBGR形式に変換

    引数:
        hex_color: "#FFFFFF"形式のカラーコード
    戻り値:
        (B, G, R)のタプル
    """
    r, g, b = hex_to_rgb(hex_color)
    return (b, g, r)


def create_title_frame(config: TitleConfig) -> np.ndarray:
    """
    テロップ用の1フレーム画像を生成

    引数:
        config: テロップ設定
    戻り値:
        フレーム画像（numpy配列、BGR形式）
    """
    # 背景色でPIL画像を作成
    bg_rgb = hex_to_rgb(config.bg_color)
    image = Image.new("RGB", (config.width, config.height), bg_rgb)
    draw = ImageDraw.Draw(image)

    # フォントを読み込み
    try:
        font = ImageFont.truetype(config.font_path, config.font_size)
    except (IOError, OSError):
        # フォントが見つからない場合はデフォルトフォントを使用
        print(f"警告: フォントが見つかりません: {config.font_path}")
        print("システムのデフォルトフォントを使用します。")
        try:
            # Windows向け日本語フォント
            font = ImageFont.truetype("msgothic.ttc", config.font_size)
        except (IOError, OSError):
            # 最終フォールバック
            font = ImageFont.load_default()

    # テキストを行に分割
    lines = config.text.replace("\\n", "\n").split("\n")

    # 各行のサイズを計算
    text_color = hex_to_rgb(config.text_color)
    line_heights = []
    line_widths = []

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    # 行間を設定
    line_spacing = config.font_size * 0.3
    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)

    # 開始Y座標（中央揃え）
    start_y = (config.height - total_height) / 2

    # 各行を描画
    current_y = start_y
    for i, line in enumerate(lines):
        # X座標（中央揃え）
        x = (config.width - line_widths[i]) / 2
        draw.text((x, current_y), line, font=font, fill=text_color)
        current_y += line_heights[i] + line_spacing

    # PIL画像をOpenCV形式（numpy配列、BGR）に変換
    frame = np.array(image)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    return frame


def generate_title_video(config: TitleConfig, output_path: str) -> bool:
    """
    テロップ動画を生成

    引数:
        config: テロップ設定
        output_path: 出力ファイルパス
    戻り値:
        成功したかどうか
    """
    try:
        # テロップフレームを生成
        frame = create_title_frame(config)

        # フレーム数を計算
        total_frames = int(config.fps * config.duration)

        # VideoWriterを設定
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(
            output_path, fourcc, config.fps, (config.width, config.height)
        )

        if not out.isOpened():
            print(f"エラー: VideoWriterを開けません: {output_path}")
            return False

        # 同じフレームを必要な回数書き込む
        for _ in range(total_frames):
            out.write(frame)

        out.release()

        # cv2.VideoWriterでは音声がないため、FFmpegで再エンコード
        _reencode_with_ffmpeg(output_path)

        return True

    except Exception as e:
        print(f"テロップ動画生成エラー: {e}")
        return False


def _reencode_with_ffmpeg(video_path: str) -> bool:
    """
    FFmpegで動画を再エンコード（互換性向上のため）
    無音の音声トラックを追加して、concat時に他のクリップの音声が失われないようにする

    引数:
        video_path: 動画ファイルパス
    戻り値:
        成功したかどうか
    """
    import ffmpeg
    from pathlib import Path

    try:
        temp_path = str(Path(video_path).with_suffix(".temp.mp4"))

        # 動画の長さを取得
        probe = ffmpeg.probe(video_path)
        duration = float(probe["format"]["duration"])

        # 入力: 動画ファイル
        video_input = ffmpeg.input(video_path)

        # 無音音声を生成（anullsrc: 無音の音声ストリームを生成）
        # 動画と同じ長さで、標準的なオーディオパラメータを使用
        silent_audio = ffmpeg.input(
            "anullsrc=r=44100:cl=stereo",
            f="lavfi",
            t=duration
        )

        # 出力（H.264でエンコード + 無音音声を追加）
        output = ffmpeg.output(
            video_input.video,
            silent_audio.audio,
            temp_path,
            vcodec="libx264",
            acodec="aac",
            preset="fast",
            crf=23,
            pix_fmt="yuv420p",
        )

        ffmpeg.run(output, overwrite_output=True, quiet=True)

        # 一時ファイルを元のファイルに置き換え
        Path(video_path).unlink()
        Path(temp_path).rename(video_path)

        return True

    except Exception as e:
        print(f"再エンコードエラー: {e}")
        # エラーが発生しても元のファイルは残す
        temp_path_obj = Path(video_path).with_suffix(".temp.mp4")
        if temp_path_obj.exists():
            temp_path_obj.unlink()
        return False
