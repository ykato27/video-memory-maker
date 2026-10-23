"""スキャン結果のキャッシュ管理モジュール"""

import hashlib
import json
import numpy as np
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    SCAN_CACHE_FILE,
    FACE_PREVIEW_DIR,
    FACE_SCAN_INTERVAL,
    FACE_CLUSTER_THRESHOLD,
    FACE_MIN_CLUSTER_SIZE,
    FACE_DETECTION_INTERVAL,
    MIN_FACE_SIZE,
    FACE_PREVIEW_SIZE,
)


def _scan_settings() -> dict:
    """スキャン結果の同一性に影響する設定値を返す。

    これらを変えると検出・クラスタリング結果が変わるため、キャッシュの
    有効性判定に含める。主要な設定を変えたら再スキャンが必要。
    """
    return {
        "FACE_SCAN_INTERVAL": FACE_SCAN_INTERVAL,
        "FACE_CLUSTER_THRESHOLD": FACE_CLUSTER_THRESHOLD,
        "FACE_MIN_CLUSTER_SIZE": FACE_MIN_CLUSTER_SIZE,
        "FACE_DETECTION_INTERVAL": FACE_DETECTION_INTERVAL,
        "MIN_FACE_SIZE": list(MIN_FACE_SIZE),
        "FACE_PREVIEW_SIZE": list(FACE_PREVIEW_SIZE),
    }


def settings_hash() -> str:
    """現在のスキャン設定のハッシュ（キャッシュキー用）"""
    payload = json.dumps(_scan_settings(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_scan_results(
    detections: list,
    clusters: list,
    embeddings: dict[str, np.ndarray],
    output_dir: Path,
) -> Path:
    """
    スキャン結果をJSONファイルに保存

    引数:
        detections: FaceDetectionのリスト
        clusters: PersonClusterのリスト
        embeddings: {検出インデックス: 埋め込みベクトル} の辞書
        output_dir: 出力ディレクトリ
    戻り値:
        保存したキャッシュファイルのパス
    """
    cache_path = output_dir / SCAN_CACHE_FILE

    # 埋め込みベクトルをBase64エンコード
    embeddings_encoded = {}
    for idx, emb in embeddings.items():
        embeddings_encoded[str(idx)] = emb.tolist()

    cache_data = {
        "scan_timestamp": datetime.now().isoformat(),
        "settings_hash": settings_hash(),
        "video_count": len(set(d.video_path for d in detections)),
        "face_count": len(detections),
        "cluster_count": len(clusters),
        "detections": [d.to_dict() for d in detections],
        "clusters": [c.to_dict() for c in clusters],
        "embeddings": embeddings_encoded,
    }

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    return cache_path


def load_scan_results(output_dir: Path) -> tuple[list[dict], list[dict], dict] | None:
    """
    キャッシュされたスキャン結果を読み込み

    引数:
        output_dir: 出力ディレクトリ
    戻り値:
        (detections_dicts, clusters_dicts, embeddings) または None
    """
    cache_path = output_dir / SCAN_CACHE_FILE

    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # 埋め込みベクトルをnumpy配列に復元
        embeddings = {}
        for idx, emb_list in cache_data.get("embeddings", {}).items():
            embeddings[idx] = np.array(emb_list)

        return (
            cache_data.get("detections", []),
            cache_data.get("clusters", []),
            embeddings,
        )
    except (json.JSONDecodeError, KeyError):
        return None


def is_cache_valid(output_dir: Path, input_folder: Path) -> bool:
    """
    キャッシュが有効かどうかをチェック

    引数:
        output_dir: 出力ディレクトリ
        input_folder: 入力動画フォルダ
    戻り値:
        キャッシュが有効な場合True
    """
    cache_path = output_dir / SCAN_CACHE_FILE

    if not cache_path.exists():
        return False

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # スキャン設定が変わっていたら無効（設定変更が結果に反映されない
        # 問題の修正）。settings_hash を持たない旧キャッシュも無効とし、
        # 一度だけ再スキャンさせる。
        if cache_data.get("settings_hash") != settings_hash():
            return False

        # キャッシュのタイムスタンプを取得
        cache_time = datetime.fromisoformat(cache_data["scan_timestamp"])

        # 入力フォルダ内の動画ファイルをチェック
        from modules.video_loader import get_video_files

        video_files = get_video_files(str(input_folder))

        # 動画数が変わっていないか
        if cache_data.get("video_count", 0) != len(video_files):
            return False

        # キャッシュより新しい動画がないか
        for video_path in video_files:
            video_mtime = datetime.fromtimestamp(Path(video_path).stat().st_mtime)
            if video_mtime > cache_time:
                return False

        # プレビュー画像が存在するか
        preview_dir = output_dir / FACE_PREVIEW_DIR
        if not preview_dir.exists():
            return False

        cluster_count = cache_data.get("cluster_count", 0)
        for i in range(cluster_count):
            preview_path = preview_dir / f"person_{i}.jpg"
            if not preview_path.exists():
                return False

        return True

    except (json.JSONDecodeError, KeyError, OSError):
        return False


def get_cache_info(output_dir: Path) -> dict | None:
    """
    キャッシュの概要情報を取得

    引数:
        output_dir: 出力ディレクトリ
    戻り値:
        キャッシュ情報の辞書 または None
    """
    cache_path = output_dir / SCAN_CACHE_FILE

    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        return {
            "scan_timestamp": cache_data.get("scan_timestamp"),
            "settings_hash": cache_data.get("settings_hash"),
            "video_count": cache_data.get("video_count", 0),
            "face_count": cache_data.get("face_count", 0),
            "cluster_count": cache_data.get("cluster_count", 0),
        }
    except (json.JSONDecodeError, KeyError):
        return None


def clear_cache(output_dir: Path) -> None:
    """
    キャッシュとプレビュー画像を削除

    引数:
        output_dir: 出力ディレクトリ
    """
    cache_path = output_dir / SCAN_CACHE_FILE
    if cache_path.exists():
        cache_path.unlink()

    preview_dir = output_dir / FACE_PREVIEW_DIR
    if preview_dir.exists():
        import shutil

        shutil.rmtree(preview_dir)
