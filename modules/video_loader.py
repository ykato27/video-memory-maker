"""動画ファイルの読み込みとフレーム抽出モジュール"""

import cv2
import numpy as np
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SUPPORTED_FORMATS, OUTPUT_FPS


def get_video_files(folder_path: str) -> list[str]:
    """
    指定フォルダ内の動画ファイル一覧を取得

    引数:
        folder_path: フォルダパス
    戻り値:
        動画ファイルのパスリスト（撮影日時順にソート）
    """
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"フォルダが見つかりません: {folder_path}")

    video_files = []
    for ext in SUPPORTED_FORMATS:
        video_files.extend(folder.glob(f"*{ext}"))
        video_files.extend(folder.glob(f"*{ext.upper()}"))

    # ファイル名でソート（通常は日時が含まれているため）
    video_files = sorted(video_files, key=lambda x: x.name)

    return [str(f) for f in video_files]


def extract_frames(
    video_path: str, interval: float = 1.0
) -> list[tuple[float, np.ndarray]]:
    """
    動画から一定間隔でフレームを抽出

    引数:
        video_path: 動画ファイルパス
        interval: 抽出間隔（秒）
    戻り値:
        (秒数, フレーム画像)のリスト
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"動画を開けません: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = OUTPUT_FPS  # フォールバック

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    frames = []
    current_sec = 0.0

    while current_sec < duration:
        frame_number = int(current_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()

        if not ret:
            break

        frames.append((current_sec, frame))
        current_sec += interval

    cap.release()
    return frames


def extract_clip(
    video_path: str, start_sec: float, duration: float, output_path: str
) -> bool:
    """
    動画から指定秒数のクリップを抽出（音声付き）

    引数:
        video_path: 元動画のパス
        start_sec: 開始秒数
        duration: 抽出する長さ（秒）
        output_path: 出力パス
    戻り値:
        成功したかどうか
    """
    import ffmpeg

    try:
        # 入力動画の情報を取得
        probe = ffmpeg.probe(video_path)
        video_info = next(
            (s for s in probe["streams"] if s["codec_type"] == "video"), None
        )

        if video_info is None:
            print(f"警告: 動画ストリームが見つかりません: {video_path}")
            return False

        # クリップを抽出（音声も含む）
        stream = ffmpeg.input(video_path, ss=start_sec, t=duration)

        # 出力（コーデックをコピーして高速処理、ただしre-encodeが必要な場合もある）
        stream = ffmpeg.output(
            stream,
            output_path,
            vcodec="libx264",
            acodec="aac",
            preset="fast",
            crf=23,
        )

        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        return True

    except ffmpeg.Error as e:
        print(f"FFmpegエラー: {e}")
        return False
    except Exception as e:
        print(f"クリップ抽出エラー: {e}")
        return False


def get_video_duration(video_path: str) -> float:
    """
    動画の長さを取得

    引数:
        video_path: 動画ファイルパス
    戻り値:
        動画の長さ（秒）
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = OUTPUT_FPS

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    return total_frames / fps


def get_video_info(video_path: str) -> dict:
    """
    動画の情報を取得

    引数:
        video_path: 動画ファイルパス
    戻り値:
        動画情報の辞書
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {}

    info = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "duration": 0.0,
    }

    if info["fps"] > 0:
        info["duration"] = info["frame_count"] / info["fps"]

    cap.release()
    return info
