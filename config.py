"""設定値を一元管理するモジュール"""

from pathlib import Path
import tempfile

# プロジェクトルートディレクトリ
PROJECT_ROOT = Path(__file__).parent

# BGMフォルダ
BGM_FOLDER = PROJECT_ROOT / "bgm"

# 既定の音声ファイルパス（後方互換性のため残す）
DEFAULT_AUDIO_PATH = PROJECT_ROOT / "assets" / "default_bgm.aac"

# 対応する音声形式
SUPPORTED_AUDIO_FORMATS = [".mp3", ".aac", ".wav", ".m4a", ".flac"]

# 出力設定
OUTPUT_WIDTH = 540
OUTPUT_HEIGHT = 960
OUTPUT_FPS = "30000/1001"  # 29.97 fps (標準的な値)

# 動画エンコード設定
VIDEO_BITRATE = "4500k"  # みてねに合わせて4.5Mbps
VIDEO_PROFILE = "main"  # H.264 Main Profile（互換性優先）
VIDEO_PRESET = "medium"  # エンコード速度と品質のバランス
VIDEO_CRF = None  # ビットレート指定時はCRFを使用しない

# 音声エンコード設定
AUDIO_SAMPLE_RATE = 48000  # 48kHz（プロ標準）
AUDIO_BITRATE = "192k"  # 192kbps

# 各動画から抽出する秒数
CLIP_DURATION = 1.0

# 対応する動画形式
SUPPORTED_FORMATS = [".mp4", ".mov", ".avi"]

# 顔検出設定
FACE_DETECTION_INTERVAL = 1.0  # 何秒おきにフレームを解析するか
MIN_FACE_SIZE = (30, 30)  # 検出する最小の顔サイズ

# 顔識別・クラスタリング設定
FACE_SCAN_INTERVAL = 2.0  # スキャン時のフレーム間隔（秒）
FACE_CLUSTER_THRESHOLD = 0.5  # DBSCANのeps（顔埋め込み距離の閾値）
FACE_MIN_CLUSTER_SIZE = 2  # クラスターを形成する最小顔数
FACE_PREVIEW_SIZE = (150, 150)  # プレビュー画像サイズ
FACE_PREVIEW_DIR = "face_previews"  # プレビュー画像のディレクトリ名
SCAN_CACHE_FILE = "scan_cache.json"  # スキャンキャッシュファイル名

# テロップ設定
TITLE_DURATION = 3.0  # 既定の表示秒数
TITLE_FONT_PATH = PROJECT_ROOT / "assets" / "NotoSansJP-Regular.ttf"  # 日本語フォント
TITLE_FONT_SIZE = 48  # 既定のフォントサイズ
TITLE_BG_COLOR = "#FFFFFF"  # 既定の背景色（現在未使用）
TITLE_TEXT_COLOR = "#FFFFFF"  # 白文字（みてねスタイル）

# 一時ファイルディレクトリ（システムの一時ディレクトリを使用）
TEMP_DIR = Path(tempfile.gettempdir()) / "video_memory_maker"
