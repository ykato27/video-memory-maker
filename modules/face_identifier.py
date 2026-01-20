"""顔識別とクラスタリングモジュール（InsightFace使用）"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from sklearn.cluster import DBSCAN
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    FACE_CLUSTER_THRESHOLD,
    FACE_MIN_CLUSTER_SIZE,
    FACE_PREVIEW_SIZE,
    FACE_PREVIEW_DIR,
)

# InsightFaceアプリケーションのグローバルインスタンス
_face_app = None


def _get_face_app():
    """InsightFace アプリケーションのシングルトンを取得"""
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis

        # buffalo_l モデルを使用（高精度）
        _face_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


@dataclass
class FaceDetection:
    """顔検出情報を格納するデータクラス"""

    video_path: str
    timestamp: float
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    embedding: np.ndarray
    image: np.ndarray  # クロップされた顔画像
    cluster_id: int = -1

    def to_dict(self) -> dict:
        """JSON保存用に辞書に変換"""
        return {
            "video_path": self.video_path,
            "timestamp": self.timestamp,
            "bbox": list(self.bbox),
            "cluster_id": self.cluster_id,
        }


@dataclass
class PersonCluster:
    """人物クラスター情報を格納するデータクラス"""

    cluster_id: int
    representative_image: np.ndarray
    face_count: int
    video_appearances: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON保存用に辞書に変換"""
        return {
            "cluster_id": self.cluster_id,
            "face_count": self.face_count,
            "video_appearances": self.video_appearances,
        }


def detect_faces_with_embeddings(frame: np.ndarray) -> list[dict]:
    """
    フレーム内のすべての顔を検出し、埋め込みを抽出

    引数:
        frame: BGR画像
    戻り値:
        顔情報のリスト [{"bbox": (x,y,w,h), "embedding": array, "image": array}, ...]
    """
    app = _get_face_app()

    # InsightFaceはRGB入力を期待
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 顔検出と埋め込み抽出
    faces = app.get(rgb_frame)

    results = []
    for face in faces:
        # bboxを(x, y, w, h)形式に変換
        # InsightFaceは[x1, y1, x2, y2]形式
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        bbox = (x1, y1, x2 - x1, y2 - y1)

        # 顔画像をクロップ（元のBGR画像から）
        face_image = frame[max(0, y1) : y2, max(0, x1) : x2].copy()

        # 埋め込みベクトル（512次元）
        embedding = face.embedding

        if embedding is not None and face_image.size > 0:
            results.append(
                {
                    "bbox": bbox,
                    "embedding": embedding,
                    "image": face_image,
                }
            )

    return results


def cluster_faces(detections: list[FaceDetection]) -> list[PersonCluster]:
    """
    顔検出結果をクラスタリングして人物ごとにグループ化

    引数:
        detections: FaceDetectionのリスト
    戻り値:
        PersonClusterのリスト
    """
    if not detections:
        return []

    # 埋め込みベクトルを集める
    embeddings = np.array([d.embedding for d in detections])

    # 埋め込みを正規化（コサイン類似度のため）
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings_normalized = embeddings / (norms + 1e-10)

    # DBSCANでクラスタリング（コサイン距離を使用）
    # InsightFaceの埋め込みは正規化されているので、ユークリッド距離 ≈ コサイン距離
    clustering = DBSCAN(
        eps=FACE_CLUSTER_THRESHOLD,
        min_samples=FACE_MIN_CLUSTER_SIZE,
        metric="euclidean",
    )
    labels = clustering.fit_predict(embeddings_normalized)

    # 各検出にクラスターIDを割り当て
    for i, detection in enumerate(detections):
        detection.cluster_id = int(labels[i])

    # クラスターごとに情報をまとめる
    cluster_dict: dict[int, list[FaceDetection]] = {}
    for detection in detections:
        cid = detection.cluster_id
        if cid not in cluster_dict:
            cluster_dict[cid] = []
        cluster_dict[cid].append(detection)

    # PersonClusterを作成
    clusters = []
    for cid, faces in cluster_dict.items():
        if cid == -1:
            # ノイズ（どのクラスターにも属さない）はスキップ
            continue

        # 代表画像を選択（最も大きい顔画像）
        best_face = max(faces, key=lambda f: f.image.shape[0] * f.image.shape[1])

        # 出現動画のリストを作成
        video_set = set(f.video_path for f in faces)

        clusters.append(
            PersonCluster(
                cluster_id=cid,
                representative_image=best_face.image,
                face_count=len(faces),
                video_appearances=list(video_set),
            )
        )

    # 出現回数でソート（多い順）
    clusters.sort(key=lambda c: c.face_count, reverse=True)

    # クラスターIDを振り直し（0から連番）
    id_mapping = {c.cluster_id: i for i, c in enumerate(clusters)}
    for c in clusters:
        c.cluster_id = id_mapping[c.cluster_id]
    for d in detections:
        if d.cluster_id in id_mapping:
            d.cluster_id = id_mapping[d.cluster_id]

    return clusters


def save_cluster_previews(
    clusters: list[PersonCluster], output_dir: Path
) -> list[Path]:
    """
    各クラスターの代表顔画像をファイルに保存

    引数:
        clusters: PersonClusterのリスト
        output_dir: 出力ディレクトリ
    戻り値:
        保存したファイルのパスリスト
    """
    preview_dir = output_dir / FACE_PREVIEW_DIR
    preview_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for cluster in clusters:
        # 画像が有効かチェック
        if cluster.representative_image.size == 0:
            continue

        # 画像をリサイズ
        resized = cv2.resize(
            cluster.representative_image,
            FACE_PREVIEW_SIZE,
            interpolation=cv2.INTER_AREA,
        )

        # ファイル保存
        filename = f"person_{cluster.cluster_id}.jpg"
        filepath = preview_dir / filename
        cv2.imwrite(str(filepath), resized)
        saved_paths.append(filepath)

    return saved_paths


def get_detections_by_cluster_ids(
    detections: list[FaceDetection], cluster_ids: list[int]
) -> list[FaceDetection]:
    """
    指定されたクラスターIDに属する検出結果をフィルタリング

    引数:
        detections: FaceDetectionのリスト
        cluster_ids: 対象のクラスターIDリスト
    戻り値:
        フィルタリングされたFaceDetectionのリスト
    """
    return [d for d in detections if d.cluster_id in cluster_ids]


def get_videos_with_selected_faces(
    detections: list[FaceDetection], cluster_ids: list[int]
) -> dict[str, list[FaceDetection]]:
    """
    選択された人物が映っている動画とその検出情報を取得

    引数:
        detections: FaceDetectionのリスト
        cluster_ids: 対象のクラスターIDリスト
    戻り値:
        {video_path: [FaceDetection, ...]} の辞書
    """
    filtered = get_detections_by_cluster_ids(detections, cluster_ids)

    video_dict: dict[str, list[FaceDetection]] = {}
    for d in filtered:
        if d.video_path not in video_dict:
            video_dict[d.video_path] = []
        video_dict[d.video_path].append(d)

    return video_dict


def find_best_timestamp_for_person(
    detections: list[FaceDetection], cluster_ids: list[int]
) -> float:
    """
    選択された人物が最も大きく映っているタイムスタンプを取得

    引数:
        detections: 同一動画のFaceDetectionリスト
        cluster_ids: 対象のクラスターIDリスト
    戻り値:
        最適なタイムスタンプ（秒）
    """
    filtered = [d for d in detections if d.cluster_id in cluster_ids]

    if not filtered:
        # 対象人物がいない場合は最初のフレームを返す
        return detections[0].timestamp if detections else 0.0

    # 顔の面積が最大のものを選択
    best = max(filtered, key=lambda d: d.bbox[2] * d.bbox[3])
    return best.timestamp
