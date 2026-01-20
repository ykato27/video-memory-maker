"""動画クリップの連結と音声合成モジュール"""

import ffmpeg
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS


def normalize_clip(input_path: str, output_path: str, width: int = None, height: int = None) -> bool:
    """
    動画クリップを指定解像度に正規化
    アスペクト比を維持しつつ、指定サイズに収まるようにスケーリングし、
    余白は黒で埋める（パディング）

    引数:
        input_path: 入力動画パス
        output_path: 出力動画パス
        width: 出力幅（デフォルト: OUTPUT_WIDTH）
        height: 出力高さ（デフォルト: OUTPUT_HEIGHT）
    戻り値:
        成功したかどうか
    """
    if width is None:
        width = OUTPUT_WIDTH
    if height is None:
        height = OUTPUT_HEIGHT

    try:
        # 入力動画の情報を取得
        probe = ffmpeg.probe(input_path)
        video_info = next(
            (s for s in probe["streams"] if s["codec_type"] == "video"), None
        )

        if video_info is None:
            print(f"警告: 動画ストリームが見つかりません: {input_path}")
            return False

        # 元の動画サイズを取得
        orig_width = int(video_info.get("width", 0))
        orig_height = int(video_info.get("height", 0))

        # 回転情報を確認（スマートフォンで撮影した動画など）
        rotation = 0
        if "tags" in video_info and "rotate" in video_info["tags"]:
            rotation = int(video_info["tags"]["rotate"])

        # 回転している場合は幅と高さを入れ替え
        if rotation in [90, 270]:
            orig_width, orig_height = orig_height, orig_width

        # FFmpegフィルターを構築
        stream = ffmpeg.input(input_path)

        # ビデオストリームを取得
        video = stream.video

        # 回転を適用（必要な場合）
        if rotation == 90:
            video = video.filter("transpose", 1)
        elif rotation == 180:
            video = video.filter("transpose", 2).filter("transpose", 2)
        elif rotation == 270:
            video = video.filter("transpose", 2)

        # アスペクト比を維持してスケーリング + パディング
        # scale: 指定サイズに収まるようにスケール
        # pad: 余白を黒で埋める
        video = video.filter(
            "scale",
            w=f"if(gt(iw/ih,{width}/{height}),{width},-2)",
            h=f"if(gt(iw/ih,{width}/{height}),-2,{height})",
        ).filter(
            "pad",
            w=width,
            h=height,
            x="(ow-iw)/2",
            y="(oh-ih)/2",
            color="black",
        ).filter(
            "fps", fps=OUTPUT_FPS
        ).filter(
            "setsar", sar="1"
        )

        # 音声ストリームを取得（存在する場合）
        has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])

        if has_audio:
            audio = stream.audio
            output = ffmpeg.output(
                video,
                audio,
                output_path,
                vcodec="libx264",
                acodec="aac",
                preset="fast",
                crf=23,
                pix_fmt="yuv420p",
            )
        else:
            output = ffmpeg.output(
                video,
                output_path,
                vcodec="libx264",
                preset="fast",
                crf=23,
                pix_fmt="yuv420p",
            )

        ffmpeg.run(output, overwrite_output=True, quiet=True)
        return True

    except ffmpeg.Error as e:
        print(f"FFmpegエラー (normalize): {e}")
        return False
    except Exception as e:
        print(f"正規化エラー: {e}")
        return False


def concatenate_clips(clip_paths: list[str], output_path: str) -> bool:
    """
    複数の動画クリップを連結

    引数:
        clip_paths: クリップのパスリスト
        output_path: 出力パス
    戻り値:
        成功したかどうか
    """
    if not clip_paths:
        print("エラー: 連結するクリップがありません")
        return False

    if len(clip_paths) == 1:
        # クリップが1つの場合はコピーのみ
        import shutil
        shutil.copy2(clip_paths[0], output_path)
        return True

    try:
        # concat demuxerを使用するためのファイルリストを作成
        temp_list_path = Path(output_path).parent / "concat_list.txt"

        with open(temp_list_path, "w", encoding="utf-8") as f:
            for clip_path in clip_paths:
                # パスをエスケープ
                escaped_path = str(Path(clip_path).absolute()).replace("\\", "/")
                f.write(f"file '{escaped_path}'\n")

        # FFmpegで連結
        stream = ffmpeg.input(str(temp_list_path), format="concat", safe=0)
        output = ffmpeg.output(
            stream,
            output_path,
            c="copy",  # 再エンコードなしでコピー
        )

        ffmpeg.run(output, overwrite_output=True, quiet=True)

        # 一時ファイルを削除
        temp_list_path.unlink()

        return True

    except ffmpeg.Error as e:
        print(f"FFmpegエラー (concatenate): {e}")
        return False
    except Exception as e:
        print(f"連結エラー: {e}")
        return False


def add_audio(video_path: str, audio_path: str, output_path: str, bgm_volume: float = 0.3) -> bool:
    """
    動画にBGMを追加（元の動画音声とミックス、ループ再生、フェードアウト付き）

    引数:
        video_path: 動画ファイルパス
        audio_path: BGM音声ファイルパス
        output_path: 出力パス
        bgm_volume: BGMの音量（0.0〜1.0、デフォルト0.3）
    戻り値:
        成功したかどうか
    """
    try:
        # 動画の長さを取得
        video_probe = ffmpeg.probe(video_path)
        video_duration = float(video_probe["format"]["duration"])

        # 動画に音声があるか確認
        has_video_audio = any(s["codec_type"] == "audio" for s in video_probe["streams"])

        # 入力ストリーム
        video_input = ffmpeg.input(video_path)
        video_stream = video_input.video

        # BGMをループさせて動画の長さに合わせる
        # atrim: 動画の長さでトリム
        # volume: BGMの音量を調整
        # afade: 最後の2秒でフェードアウト
        bgm_input = ffmpeg.input(audio_path, stream_loop=-1)
        bgm_stream = bgm_input.audio.filter(
            "atrim", duration=video_duration
        ).filter(
            "volume", volume=bgm_volume
        ).filter(
            "afade", type="out", start_time=max(0, video_duration - 2), duration=2
        )

        if has_video_audio:
            # 動画の元音声を取得
            original_audio = video_input.audio

            # 元音声とBGMをミックス
            mixed_audio = ffmpeg.filter([original_audio, bgm_stream], "amix", inputs=2, duration="first")

            # 出力
            output = ffmpeg.output(
                video_stream,
                mixed_audio,
                output_path,
                vcodec="copy",
                acodec="aac",
                audio_bitrate="192k",
            )
        else:
            # 動画に音声がない場合はBGMのみ
            output = ffmpeg.output(
                video_stream,
                bgm_stream,
                output_path,
                vcodec="copy",
                acodec="aac",
                audio_bitrate="192k",
            )

        ffmpeg.run(output, overwrite_output=True, quiet=True)
        return True

    except ffmpeg.Error as e:
        print(f"FFmpegエラー (add_audio): {e}")
        return False
    except Exception as e:
        print(f"音声追加エラー: {e}")
        return False


def generate_output_filename() -> str:
    """
    出力ファイル名を生成（YYYYMMDD_highlight_video.mp4形式）

    戻り値:
        ファイル名
    """
    today = datetime.now().strftime("%Y%m%d")
    return f"{today}_highlight_video.mp4"


def get_total_duration(video_paths: list[str]) -> float:
    """
    複数の動画の合計時間を取得

    引数:
        video_paths: 動画ファイルパスのリスト
    戻り値:
        合計時間（秒）
    """
    total = 0.0
    for path in video_paths:
        try:
            probe = ffmpeg.probe(path)
            duration = float(probe["format"]["duration"])
            total += duration
        except Exception:
            pass
    return total
