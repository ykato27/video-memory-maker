# Video Memory Maker

複数の動画ファイルから、子供の顔が映っている重要なシーンを自動抽出し、連結してハイライト動画を作成するツールです。

## 機能

- **顔検出による自動抽出**: MediaPipeを使用して、各動画から子供の顔が最も大きく映っているシーンを自動検出
- **テロップ追加**: 動画の冒頭にタイトルテロップを挿入（日本語対応）
- **BGM追加**: 背景音楽を追加（ループ再生、フェードアウト対応）
- **解像度統一**: 異なる解像度の動画を540x960（縦向き）に統一

## フォルダ構成

```
video-memory-maker/
├── main.py              # メインスクリプト
├── config.py            # 設定値
├── input/               # ★ 入力動画をここに入れる
├── output/              # ★ 出力動画がここに保存される
├── modules/             # 処理モジュール
└── assets/              # フォント等のリソース
```

## 必要条件

- Python 3.12以上
- [uv](https://github.com/astral-sh/uv) (Pythonパッケージマネージャー)
- [FFmpeg](https://ffmpeg.org/)

## インストール

### 1. FFmpegのインストール

**Windows (winget):**
```bash
winget install Gyan.FFmpeg
```

### 2. プロジェクトのセットアップ

```bash
git clone https://github.com/yourusername/video-memory-maker.git
cd video-memory-maker
uv sync
```

## 使用方法

### 1. 動画を配置

`input/` フォルダに処理したい動画ファイル（.mp4, .mov, .avi）を入れる

### 2. 実行

```bash
# 基本（inputフォルダの動画を処理し、outputフォルダに保存）
uv run python main.py -i input -o output

# テロップ付き
uv run python main.py -i input -o output -t "2024年1月の思い出"

# 抽出時間を2秒に変更
uv run python main.py -i input -o output -d 2

# BGM付き
uv run python main.py -i input -o output -a "bgm.mp3"
```

### 3. 出力を確認

`output/` フォルダに `YYYYMMDD_highlight_video.mp4` が生成される

## コマンドラインオプション

| オプション | 短縮形 | 必須 | 説明 | デフォルト |
|-----------|--------|------|------|-----------|
| `--input` | `-i` | ✓ | 入力動画フォルダ | - |
| `--output` | `-o` | | 出力フォルダ | 入力と同じ |
| `--audio` | `-a` | | BGMファイル | なし |
| `--title` | `-t` | | テロップテキスト | なし |
| `--clip-duration` | `-d` | | 抽出秒数 | 1.0 |
| `--title-duration` | | | テロップ表示秒数 | 3.0 |
| `--title-font-size` | | | フォントサイズ | 48 |
| `--title-bg-color` | | | テロップ背景色 | #FFFFFF |
| `--title-text-color` | | | テロップ文字色 | #000000 |

## 出力仕様

- **ファイル名**: `YYYYMMDD_highlight_video.mp4`
- **解像度**: 540x960 (縦向き)
- **フレームレート**: 30fps

## 対応フォーマット

- MP4 (.mp4)
- MOV (.mov)
- AVI (.avi)

## 注意事項

- 初回実行時に顔検出モデル（約200KB）が自動ダウンロードされます
- 処理時間目安：10本で約2〜3分

## ライセンス

MIT License
