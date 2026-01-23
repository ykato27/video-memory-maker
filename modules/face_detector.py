"""顔検出と最適フレーム選定モジュール（笑顔検出機能付き）"""

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pathlib import Path
import urllib.request
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MIN_FACE_SIZE, PROJECT_ROOT

# モデルファイルのパス
MODEL_PATH = PROJECT_ROOT / "assets" / "blaze_face_short_range.tflite"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"

# 顔ランドマークモデル（笑顔検出用）
LANDMARKER_PATH = PROJECT_ROOT / "assets" / "face_landmarker.task"
LANDMARKER_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"


def _ensure_model_exists():
    """モデルファイルが存在することを確認し、なければダウンロードする"""
    if not MODEL_PATH.exists():
        print(f"顔検出モデルをダウンロード中...")
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print(f"モデルをダウンロードしました: {MODEL_PATH}")

    # Windows日本語パス対策: ファイルをバイトとして読み込んで返す
    with open(MODEL_PATH, 'rb') as f:
        return f.read()


def _ensure_landmarker_exists():
    """顔ランドマークモデルが存在することを確認し、なければダウンロードする"""
    if not LANDMARKER_PATH.exists():
        print(f"顔ランドマークモデルをダウンロード中...")
        LANDMARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(LANDMARKER_URL, LANDMARKER_PATH)
        print(f"モデルをダウンロードしました: {LANDMARKER_PATH}")

    with open(LANDMARKER_PATH, 'rb') as f:
        return f.read()


def calculate_smile_score(frame: np.ndarray) -> float:
    """
    フレーム内の笑顔スコアを計算

    MediaPipe FaceLandmarkerのblendshapesを使用して笑顔を検出
    
    引数:
        frame: 画像データ (BGR形式)
    戻り値:
        笑顔スコア (0.0〜1.0、高いほど笑顔)
    """
    try:
        # モデルファイルの確認
        model_data = _ensure_landmarker_exists()

        # FaceLandmarker の設定
        base_options = python.BaseOptions(model_asset_buffer=model_data)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_face_blendshapes=True,  # 表情のブレンドシェイプを出力
            num_faces=5,  # 最大5人まで検出
        )

        # BGRからRGBに変換
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            result = landmarker.detect(mp_image)

            if not result.face_blendshapes:
                return 0.0

            # 全ての顔の笑顔スコアの最大値を返す
            max_smile_score = 0.0
            
            for face_blendshapes in result.face_blendshapes:
                smile_score = 0.0
                
                for blendshape in face_blendshapes:
                    # 笑顔関連のブレンドシェイプを確認
                    name = blendshape.category_name
                    score = blendshape.score
                    
                    # 口角の上がり（笑顔の主要指標）
                    if name == "mouthSmileLeft" or name == "mouthSmileRight":
                        smile_score += score * 0.4
                    # 頬の上がり
                    elif name == "cheekSquintLeft" or name == "cheekSquintRight":
                        smile_score += score * 0.1
                
                max_smile_score = max(max_smile_score, min(smile_score, 1.0))

            return max_smile_score

    except Exception as e:
        # エラー時は笑顔スコア0を返す（処理を継続）
        return 0.0


def detect_faces(frame: np.ndarray) -> list[dict]:
    """
    フレーム内の顔を検出

    引数:
        frame: 画像データ (BGR形式)
    戻り値:
        検出された顔の情報リスト
        [{"bbox": (x, y, w, h), "area": int, "confidence": float}, ...]
    """
    faces = []
    height, width = frame.shape[:2]

    # モデルファイルの確認（バイトデータとして取得）
    model_data = _ensure_model_exists()

    # MediaPipe Face Detector の設定（バッファから読み込み）
    base_options = python.BaseOptions(model_asset_buffer=model_data)
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        min_detection_confidence=0.5,
    )

    # BGRからRGBに変換
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # MediaPipe Image を作成
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

    with vision.FaceDetector.create_from_options(options) as detector:
        # 顔検出を実行
        detection_result = detector.detect(mp_image)

        for detection in detection_result.detections:
            bbox = detection.bounding_box

            # バウンディングボックスの座標を取得
            x = bbox.origin_x
            y = bbox.origin_y
            w = bbox.width
            h = bbox.height

            # 最小サイズチェック
            if w < MIN_FACE_SIZE[0] or h < MIN_FACE_SIZE[1]:
                continue

            # 座標の境界チェック
            x = max(0, x)
            y = max(0, y)
            w = min(w, width - x)
            h = min(h, height - y)

            area = w * h
            confidence = detection.categories[0].score if detection.categories else 0.5

            faces.append(
                {
                    "bbox": (x, y, w, h),
                    "area": area,
                    "confidence": confidence,
                }
            )

    return faces


def calculate_frame_score(
    face_info: dict, frame: np.ndarray, frame_center: tuple[int, int], smile_score: float = 0.0
) -> float:
    """
    フレームのスコアを計算（顔の大きさ、中央配置、笑顔を考慮）

    引数:
        face_info: 顔検出情報
        frame: フレーム画像
        frame_center: フレームの中央座標 (cx, cy)
        smile_score: 笑顔スコア（0.0〜1.0）
    戻り値:
        スコア（大きいほど良い）
    """
    x, y, w, h = face_info["bbox"]
    area = face_info["area"]
    confidence = face_info["confidence"]

    # 顔の中心座標
    face_cx = x + w // 2
    face_cy = y + h // 2

    # フレーム中心からの距離（正規化）
    frame_h, frame_w = frame.shape[:2]
    max_distance = np.sqrt(frame_w**2 + frame_h**2) / 2
    distance = np.sqrt(
        (face_cx - frame_center[0]) ** 2 + (face_cy - frame_center[1]) ** 2
    )
    center_score = 1.0 - (distance / max_distance)

    # 面積のスコア（フレーム全体に対する比率）
    frame_area = frame_w * frame_h
    area_score = min(area / frame_area * 10, 1.0)  # 正規化（最大1.0）

    # 総合スコア（重み付け）
    # 顔の大きさ、笑顔、中央配置、信頼度を考慮
    score = (
        area_score * 0.35 +      # 顔の大きさ: 35%
        smile_score * 0.35 +     # 笑顔: 35%
        center_score * 0.20 +    # 中央配置: 20%
        confidence * 0.10        # 信頼度: 10%
    )

    return score


def find_best_frame(frames: list[tuple[float, np.ndarray]]) -> float:
    """
    表情豊かで子供の顔が大きく映っているフレームを特定

    引数:
        frames: (秒数, フレーム画像)のリスト
    戻り値:
        最適なフレームの秒数
    """
    if not frames:
        return 0.0

    best_sec = frames[0][0]  # デフォルトは最初のフレーム
    best_score = -1.0

    for sec, frame in frames:
        faces = detect_faces(frame)

        if not faces:
            continue

        # 笑顔スコアを計算（フレーム全体で1回だけ）
        smile_score = calculate_smile_score(frame)

        # フレームの中央座標
        h, w = frame.shape[:2]
        center = (w // 2, h // 2)

        # 各顔のスコアを計算し、最も高いものを採用
        for face in faces:
            score = calculate_frame_score(face, frame, center, smile_score)
            if score > best_score:
                best_score = score
                best_sec = sec

    # 顔が検出されなかった場合、動画の中央付近を返す
    if best_score < 0:
        middle_idx = len(frames) // 2
        best_sec = frames[middle_idx][0]

    return best_sec


def is_child_face(face_info: dict, frame: np.ndarray) -> bool:
    """
    検出された顔が子供かどうかを判定
    （顔のサイズ比率や位置から推定）

    注: この関数は将来の拡張用。現在は単純な推定のみ。

    引数:
        face_info: 顔検出情報
        frame: 元のフレーム画像
    戻り値:
        子供の顔と判定されたかどうか
    """
    # 現在の実装では、顔の比率から大まかに判定
    # 子供の顔は一般的に丸みがあり、横幅と高さの比率が1に近い

    x, y, w, h = face_info["bbox"]

    # アスペクト比（子供の顔は1.0に近い傾向）
    aspect_ratio = w / h if h > 0 else 0

    # 子供の顔の特徴として、比率が0.8〜1.2程度
    if 0.7 <= aspect_ratio <= 1.3:
        return True

    return False


def get_face_count(frame: np.ndarray) -> int:
    """
    フレーム内の顔の数を取得

    引数:
        frame: 画像データ
    戻り値:
        検出された顔の数
    """
    faces = detect_faces(frame)
    return len(faces)
