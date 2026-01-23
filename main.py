"""動画ハイライト自動作成ツール - メインスクリプト"""

import argparse
import shutil
import sys
from pathlib import Path

from config import (
    DEFAULT_AUDIO_PATH,
    BGM_FOLDER,
    SUPPORTED_AUDIO_FORMATS,
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    CLIP_DURATION,
    FACE_DETECTION_INTERVAL,
    FACE_SCAN_INTERVAL,
    FACE_PREVIEW_DIR,
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
    add_title_overlay,
    generate_output_filename,
)
from modules.face_identifier import (
    FaceDetection,
    detect_faces_with_embeddings,
    cluster_faces,
    save_cluster_previews,
    get_videos_with_selected_faces,
    find_best_timestamp_for_person,
)
from modules.scan_cache import (
    save_scan_results,
    load_scan_results,
    is_cache_valid,
    get_cache_info,
    clear_cache,
)
from modules.face_selector_gui import show_face_selector_gui


def get_bgm_from_folder() -> Path | None:
    """
    BGMフォルダから音声ファイルを取得

    戻り値:
        音声ファイルのパス（見つからない場合はNone）
    """
    if not BGM_FOLDER.exists():
        return None

    # BGMフォルダ内の音声ファイルを検索
    audio_files = []
    for ext in SUPPORTED_AUDIO_FORMATS:
        audio_files.extend(BGM_FOLDER.glob(f"*{ext}"))

    if not audio_files:
        return None

    # ファイル名でソートして最初のファイルを返す（一貫性のため）
    audio_files.sort()
    return audio_files[0]


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
    # 顔選択モード関連
    parser.add_argument(
        "--select-faces",
        action="store_true",
        help="顔選択モードを有効化（2フェーズ処理）",
    )
    parser.add_argument(
        "--face-ids",
        type=str,
        help="対象人物ID（カンマ区切り、例: 0,1,2）",
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="キャッシュを無視して再スキャン",
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


def scan_videos_for_faces(video_files: list[str]) -> list[FaceDetection]:
    """
    全動画をスキャンして顔を検出

    引数:
        video_files: 動画ファイルパスのリスト
    戻り値:
        FaceDetectionのリスト
    """
    all_detections = []

    for idx, video_path in enumerate(video_files, 1):
        video_name = Path(video_path).name
        print(f"[{idx}/{len(video_files)}] スキャン中: {video_name}")

        try:
            # フレームを抽出（スキャン用の間隔）
            frames = extract_frames(video_path, interval=FACE_SCAN_INTERVAL)

            if not frames:
                print(f"  警告: フレームを抽出できませんでした")
                continue

            face_count = 0
            for timestamp, frame in frames:
                # 顔検出と埋め込み抽出
                faces = detect_faces_with_embeddings(frame)

                for face in faces:
                    detection = FaceDetection(
                        video_path=video_path,
                        timestamp=timestamp,
                        bbox=face["bbox"],
                        embedding=face["embedding"],
                        image=face["image"],
                    )
                    all_detections.append(detection)
                    face_count += 1

            if face_count > 0:
                print(f"  {face_count}個の顔を検出")
            else:
                print(f"  顔が検出されませんでした")

        except Exception as e:
            print(f"  エラー: {e}")
            continue

    return all_detections


def prompt_face_selection(clusters, output_folder: Path) -> list[int]:
    """
    ユーザーに顔選択を促す

    引数:
        clusters: PersonClusterのリスト
        output_folder: 出力フォルダ
    戻り値:
        選択されたクラスターIDのリスト
    """
    preview_dir = output_folder / FACE_PREVIEW_DIR

    print("\n" + "=" * 50)
    print("顔プレビュー画像が保存されました:")
    print(f"  {preview_dir}")
    print("=" * 50)
    print("\n検出された人物:")

    for cluster in clusters:
        video_count = len(cluster.video_appearances)
        print(f"  person_{cluster.cluster_id}.jpg - {cluster.face_count}回検出 ({video_count}本の動画)")

    print("\n対象の人物IDを入力してください")
    print("（カンマ区切りで複数指定可、例: 0,1）")
    print("（'all' で全員を対象）")

    while True:
        user_input = input("\n人物ID: ").strip()

        if user_input.lower() == "all":
            return [c.cluster_id for c in clusters]

        try:
            selected_ids = [int(x.strip()) for x in user_input.split(",")]
            valid_ids = [c.cluster_id for c in clusters]

            invalid = [i for i in selected_ids if i not in valid_ids]
            if invalid:
                print(f"エラー: 無効なID: {invalid}")
                print(f"有効なID: {valid_ids}")
                continue

            return selected_ids
        except ValueError:
            print("エラー: 数字をカンマ区切りで入力してください")


def process_with_face_selection(args, video_files: list[str], output_folder: Path, audio_path: Path | None):
    """
    顔選択モードでの処理（2フェーズ）

    引数:
        args: コマンドライン引数
        video_files: 動画ファイルリスト
        output_folder: 出力フォルダ
        audio_path: 音声ファイルパス
    """
    input_folder = Path(args.input)

    # Phase 1: スキャンとクラスタリング
    print("\n" + "=" * 50)
    print("Phase 1: 顔のスキャンとクラスタリング")
    print("=" * 50)

    # キャッシュの確認
    use_cache = False
    if not args.rescan and is_cache_valid(output_folder, input_folder):
        cache_info = get_cache_info(output_folder)
        if cache_info:
            print(f"\n有効なキャッシュが見つかりました:")
            print(f"  スキャン日時: {cache_info['scan_timestamp']}")
            print(f"  動画数: {cache_info['video_count']}")
            print(f"  検出顔数: {cache_info['face_count']}")
            print(f"  人物数: {cache_info['cluster_count']}")

            use_cache_input = input("\nキャッシュを使用しますか? (y/n): ").strip().lower()
            use_cache = use_cache_input == "y"

    if use_cache:
        # キャッシュから読み込み
        print("\nキャッシュを読み込み中...")
        cache_data = load_scan_results(output_folder)
        if cache_data:
            detection_dicts, cluster_dicts, embeddings = cache_data

            # FaceDetectionオブジェクトを再構築（埋め込みあり、画像なし）
            detections = []
            for i, d in enumerate(detection_dicts):
                import numpy as np
                emb = embeddings.get(str(i), np.zeros(128))
                detection = FaceDetection(
                    video_path=d["video_path"],
                    timestamp=d["timestamp"],
                    bbox=tuple(d["bbox"]),
                    embedding=emb,
                    image=np.zeros((1, 1, 3), dtype=np.uint8),  # ダミー画像
                    cluster_id=d["cluster_id"],
                )
                detections.append(detection)

            # クラスター情報を再構築
            from modules.face_identifier import PersonCluster
            clusters = []
            for c in cluster_dicts:
                import numpy as np
                cluster = PersonCluster(
                    cluster_id=c["cluster_id"],
                    representative_image=np.zeros((1, 1, 3), dtype=np.uint8),
                    face_count=c["face_count"],
                    video_appearances=c["video_appearances"],
                )
                clusters.append(cluster)
        else:
            print("キャッシュの読み込みに失敗しました。再スキャンします。")
            use_cache = False

    if not use_cache:
        # 新規スキャン
        print("\n全動画をスキャン中...")
        detections = scan_videos_for_faces(video_files)

        if not detections:
            print("\nエラー: 顔が検出されませんでした")
            sys.exit(1)

        print(f"\n合計 {len(detections)} 個の顔を検出しました")

        # クラスタリング
        print("\n顔をクラスタリング中...")
        clusters = cluster_faces(detections)

        if not clusters:
            print("\nエラー: クラスタリングできませんでした（顔の検出数が少なすぎる可能性）")
            sys.exit(1)

        print(f"{len(clusters)} 人の人物を識別しました")

        # プレビュー画像を保存
        print("\nプレビュー画像を保存中...")
        save_cluster_previews(clusters, output_folder)

        # キャッシュを保存
        embeddings_dict = {str(i): d.embedding for i, d in enumerate(detections)}
        save_scan_results(detections, clusters, embeddings_dict, output_folder)

    # Phase 1.5: 人物選択
    if args.face_ids:
        # コマンドラインで指定された場合
        if args.face_ids.lower() == "all":
            selected_ids = [c.cluster_id for c in clusters]
        else:
            selected_ids = [int(x.strip()) for x in args.face_ids.split(",")]
        print(f"\n選択された人物ID: {selected_ids}")
    else:
        # GUIで選択
        print("\n顔選択UIを起動中...")
        selected_ids = show_face_selector_gui(clusters, output_folder)

    print(f"\n対象人物: {selected_ids}")

    # Phase 2: 全動画からハイライト動画を作成
    print("\n" + "=" * 50)
    print("Phase 2: ハイライト動画の作成")
    print("=" * 50)

    # 選択された人物が映っている動画の情報を取得
    videos_with_faces = get_videos_with_selected_faces(detections, selected_ids)

    print(f"\n全{len(video_files)}本の動画から抽出します")
    print(f"  └ うち{len(videos_with_faces)}本に選択した人物が映っています")

    # 一時ディレクトリのセットアップ
    setup_temp_dir()

    try:
        clip_paths = []
        sorted_videos = sorted(video_files)

        for idx, video_path in enumerate(sorted_videos, 1):
            video_name = Path(video_path).name
            print(f"\n[{idx}/{len(sorted_videos)}] 処理中: {video_name}")

            try:
                # 選択された人物が映っている動画かチェック
                if video_path in videos_with_faces:
                    # 選択された人物が映っている → その人物のシーンを抽出
                    video_detections = videos_with_faces[video_path]
                    best_sec = find_best_timestamp_for_person(video_detections, selected_ids)
                    print(f"  選択した人物を検出 → 最適なフレーム: {best_sec:.1f}秒")
                else:
                    # 選択された人物が映っていない → 従来の顔検出ロジック
                    print("  フレームを抽出中...")
                    frames = extract_frames(video_path, interval=FACE_DETECTION_INTERVAL)
                    if not frames:
                        print(f"  警告: フレームを抽出できませんでした")
                        continue
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

        # 以降は通常処理と同じ
        finalize_video(args, clip_paths, output_folder, audio_path)

    finally:
        print("\n一時ファイルを削除中...")
        cleanup_temp_dir()


def process_without_face_selection(args, video_files: list[str], output_folder: Path, audio_path: Path | None):
    """
    通常モードでの処理（従来の動作）

    引数:
        args: コマンドライン引数
        video_files: 動画ファイルリスト
        output_folder: 出力フォルダ
        audio_path: 音声ファイルパス
    """
    setup_temp_dir()

    try:
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

        finalize_video(args, clip_paths, output_folder, audio_path)

    finally:
        print("\n一時ファイルを削除中...")
        cleanup_temp_dir()


def finalize_video(args, clip_paths: list[str], output_folder: Path, audio_path: Path | None):
    """
    動画の最終処理（テロップ追加、連結、音声追加）

    引数:
        args: コマンドライン引数
        clip_paths: クリップパスのリスト
        output_folder: 出力フォルダ
        audio_path: 音声ファイルパス
    """
    print(f"\n処理完了: {len(clip_paths)}本のクリップを抽出しました")

    # 動画を連結
    print("\n動画を連結中...")
    concatenated_path = str(TEMP_DIR / "concatenated.mp4")
    if not concatenate_clips(clip_paths, concatenated_path):
        print("エラー: 動画の連結に失敗しました")
        sys.exit(1)

    # テロップをオーバーレイ（指定されている場合）
    if args.title:
        print("\nテロップをオーバーレイ中...")
        titled_path = str(TEMP_DIR / "titled.mp4")
        if add_title_overlay(
            concatenated_path,
            titled_path,
            args.title,
            duration=args.title_duration,
            font_size=args.title_font_size,
            text_color=args.title_text_color,
        ):
            concatenated_path = titled_path
            print("テロップを追加しました")
        else:
            print("警告: テロップの追加に失敗しました")

    # 出力ファイル名を生成
    output_filename = generate_output_filename()
    output_path = str(output_folder / output_filename)

    # 音声を追加（音声ファイルがある場合）
    if audio_path:
        print("BGMを追加中...")
        if not add_audio(concatenated_path, str(audio_path), output_path):
            print("警告: BGMの追加に失敗しました。BGMなしで出力します。")
            shutil.copy2(concatenated_path, output_path)
    else:
        shutil.copy2(concatenated_path, output_path)

    print(f"\n完了! 出力ファイル: {output_path}")


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
        # コマンドラインで指定された場合
        audio_path = Path(args.audio)
        if not audio_path.exists():
            print(f"警告: 音声ファイルが見つかりません: {args.audio}")
            audio_path = None
    else:
        # 指定がない場合はBGMフォルダから自動選択
        audio_path = get_bgm_from_folder()
        if audio_path:
            print(f"BGMを自動選択: {audio_path.name}")
        elif DEFAULT_AUDIO_PATH.exists():
            # BGMフォルダにファイルがない場合は既定のBGMを使用
            audio_path = DEFAULT_AUDIO_PATH
            print(f"既定のBGMを使用: {audio_path.name}")

    # 動画ファイル一覧を取得
    print("動画ファイルを検索中...")
    video_files = get_video_files(str(input_folder))

    if not video_files:
        print(f"エラー: 動画ファイルが見つかりません: {input_folder}")
        sys.exit(1)

    print(f"見つかった動画ファイル: {len(video_files)}本")

    # 処理モードに応じて実行
    if args.select_faces:
        process_with_face_selection(args, video_files, output_folder, audio_path)
    else:
        process_without_face_selection(args, video_files, output_folder, audio_path)


if __name__ == "__main__":
    main()
