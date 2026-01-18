"""動画ハイライト自動作成ツール - メインスクリプト"""

import argparse
import shutil
import sys
from pathlib import Path

from config import (
    DEFAULT_AUDIO_PATH,
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    CLIP_DURATION,
    FACE_DETECTION_INTERVAL,
    TITLE_DURATION,
    TITLE_FONT_SIZE,
    TITLE_BG_COLOR,
    TITLE_TEXT_COLOR,
    TEMP_DIR,
)
from modules.video_loader import get_video_files, extract_frames, extract_clip
from modules.face_detector import find_best_frame
from modules.title_generator import TitleConfig, generate_title_video
from modules.video_composer import (
    normalize_clip,
    concatenate_clips,
    add_audio,
    generate_output_filename,
)


def parse_args():
    """コマンドライン引数を解析"""
    parser = argparse.ArgumentParser(
        description="動画ハイライト自動作成ツール - 子供の顔が映っている瞬間を自動抽出してハイライト動画を作成します"
    )

    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="入力動画フォルダのパス",
    )
    parser.add_argument(
        "--audio",
        "-a",
        help="背景音楽ファイルのパス（省略時は既定の音声を使用）",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="出力フォルダのパス（省略時は入力フォルダと同じ場所）",
    )
    parser.add_argument(
        "--title",
        "-t",
        help="冒頭テロップのテキスト（複数行は「\\n」で区切る）",
    )
    parser.add_argument(
        "--title-duration",
        type=float,
        default=TITLE_DURATION,
        help=f"テロップ表示秒数（既定: {TITLE_DURATION}秒）",
    )
    parser.add_argument(
        "--title-font-size",
        type=int,
        default=TITLE_FONT_SIZE,
        help=f"テロップのフォントサイズ（既定: {TITLE_FONT_SIZE}）",
    )
    parser.add_argument(
        "--title-bg-color",
        default=TITLE_BG_COLOR,
        help=f"テロップの背景色（既定: {TITLE_BG_COLOR}）",
    )
    parser.add_argument(
        "--title-text-color",
        default=TITLE_TEXT_COLOR,
        help=f"テロップの文字色（既定: {TITLE_TEXT_COLOR}）",
    )
    parser.add_argument(
        "--clip-duration",
        "-d",
        type=float,
        default=CLIP_DURATION,
        help=f"各動画から抽出する秒数（既定: {CLIP_DURATION}秒）",
    )

    return parser.parse_args()


def setup_temp_dir():
    """一時ディレクトリをセットアップ"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    # 既存の一時ファイルをクリア
    for f in TEMP_DIR.iterdir():
        if f.is_file():
            f.unlink()


def cleanup_temp_dir():
    """一時ディレクトリをクリーンアップ"""
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)


def main():
    """メイン処理"""
    args = parse_args()

    # 入力フォルダの確認
    input_folder = Path(args.input)
    if not input_folder.exists():
        print(f"エラー: 入力フォルダが見つかりません: {args.input}")
        sys.exit(1)

    # 出力フォルダの設定
    output_folder = Path(args.output) if args.output else input_folder
    output_folder.mkdir(parents=True, exist_ok=True)

    # 音声ファイルの確認
    audio_path = None
    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.exists():
            print(f"警告: 音声ファイルが見つかりません: {args.audio}")
            audio_path = None
    elif DEFAULT_AUDIO_PATH.exists():
        audio_path = DEFAULT_AUDIO_PATH

    # 一時ディレクトリのセットアップ
    setup_temp_dir()

    try:
        # 動画ファイル一覧を取得
        print("動画ファイルを検索中...")
        video_files = get_video_files(str(input_folder))

        if not video_files:
            print(f"エラー: 動画ファイルが見つかりません: {input_folder}")
            sys.exit(1)

        print(f"見つかった動画ファイル: {len(video_files)}本")

        # 各動画からクリップを抽出
        clip_paths = []
        for idx, video_path in enumerate(video_files, 1):
            video_name = Path(video_path).name
            print(f"\n[{idx}/{len(video_files)}] 処理中: {video_name}")

            try:
                # フレームを抽出
                print("  フレームを抽出中...")
                frames = extract_frames(video_path, interval=FACE_DETECTION_INTERVAL)

                if not frames:
                    print(f"  警告: フレームを抽出できませんでした")
                    continue

                # 最適なフレームを見つける
                print("  顔検出を実行中...")
                best_sec = find_best_frame(frames)
                print(f"  最適なフレーム: {best_sec:.1f}秒")

                # クリップを抽出
                raw_clip_path = str(TEMP_DIR / f"raw_clip_{idx:04d}.mp4")
                print("  クリップを抽出中...")
                if not extract_clip(video_path, best_sec, args.clip_duration, raw_clip_path):
                    print(f"  警告: クリップの抽出に失敗しました")
                    continue

                # クリップを正規化
                normalized_clip_path = str(TEMP_DIR / f"clip_{idx:04d}.mp4")
                print("  クリップを正規化中...")
                if not normalize_clip(
                    raw_clip_path,
                    normalized_clip_path,
                    OUTPUT_WIDTH,
                    OUTPUT_HEIGHT,
                ):
                    print(f"  警告: クリップの正規化に失敗しました")
                    continue

                clip_paths.append(normalized_clip_path)
                print(f"  完了!")

            except Exception as e:
                print(f"  エラー: {e}")
                continue

        if not clip_paths:
            print("\nエラー: 処理できたクリップがありません")
            sys.exit(1)

        print(f"\n処理完了: {len(clip_paths)}本のクリップを抽出しました")

        # テロップ動画を生成（指定されている場合）
        all_clips = []
        if args.title:
            print("\nテロップ動画を生成中...")
            title_config = TitleConfig(
                text=args.title,
                duration=args.title_duration,
                width=OUTPUT_WIDTH,
                height=OUTPUT_HEIGHT,
                font_size=args.title_font_size,
                bg_color=args.title_bg_color,
                text_color=args.title_text_color,
            )
            title_path = str(TEMP_DIR / "title.mp4")
            if generate_title_video(title_config, title_path):
                all_clips.append(title_path)
                print("テロップ動画を生成しました")
            else:
                print("警告: テロップ動画の生成に失敗しました")

        # クリップを追加
        all_clips.extend(clip_paths)

        # 動画を連結
        print("\n動画を連結中...")
        concatenated_path = str(TEMP_DIR / "concatenated.mp4")
        if not concatenate_clips(all_clips, concatenated_path):
            print("エラー: 動画の連結に失敗しました")
            sys.exit(1)

        # 出力ファイル名を生成
        output_filename = generate_output_filename()
        output_path = str(output_folder / output_filename)

        # 音声を追加（音声ファイルがある場合）
        if audio_path:
            print("音声を追加中...")
            if not add_audio(concatenated_path, str(audio_path), output_path):
                print("警告: 音声の追加に失敗しました。音声なしで出力します。")
                shutil.copy2(concatenated_path, output_path)
        else:
            print("音声ファイルが指定されていないため、音声なしで出力します")
            shutil.copy2(concatenated_path, output_path)

        print(f"\n完了! 出力ファイル: {output_path}")

    finally:
        # 一時ファイルをクリーンアップ
        print("\n一時ファイルを削除中...")
        cleanup_temp_dir()


if __name__ == "__main__":
    main()
