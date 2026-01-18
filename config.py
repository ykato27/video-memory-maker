"""設定値を一元管理するモジュール"""

from pathlib import Path
import tempfile

# プロジェクトルートディレクトリ
PROJECT_ROOT = Path(__file__).parent

# 既定の音声ファイルパス
DEFAULT_AUDIO_PATH = PROJECT_ROOT / "assets" / "default_bgm.aac"

# 出力設定
OUTPUT_WIDTH = 540
OUTPUT_HEIGHT = 960
OUTPUT_FPS = 30

# 各動画から抽出する秒数
CLIP_DURATION = 1.0

# 対応する動画形式
SUPPORTED_FORMATS = [".mp4", ".mov", ".avi"]

# 顔検出設定
FACE_DETECTION_INTERVAL = 1.0  # 何秒おきにフレームを解析するか
MIN_FACE_SIZE = (30, 30)  # 検出する最小の顔サイズ

# テロップ設定
TITLE_DURATION = 3.0  # 既定の表示秒数
TITLE_FONT_PATH = PROJECT_ROOT / "assets" / "NotoSansJP-Regular.ttf"  # 日本語フォント
TITLE_FONT_SIZE = 48  # 既定のフォントサイズ
TITLE_BG_COLOR = "#FFFFFF"  # 既定の背景色
TITLE_TEXT_COLOR = "#000000"  # 既定の文字色

# 一時ファイルディレクトリ（システムの一時ディレクトリを使用）
TEMP_DIR = Path(tempfile.gettempdir()) / "video_memory_maker"
