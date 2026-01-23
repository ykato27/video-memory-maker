# Video Memory Maker

複数の動画ファイルから、子供の顔が映っている重要なシーンを自動抽出し、連結してハイライト動画を作成するツールです。

## 機能

- **顔検出による自動抽出**: MediaPipeを使用して、各動画から子供の顔が最も大きく映っているシーンを自動検出
- **笑顔検出**: 表情豊かなシーンを優先的に抽出（笑顔スコアによる自動選別）
- **顔選択モード**: 動画に映っている人物を事前にスキャンし、特定の人物のみを対象にハイライト動画を作成
- **テロップ追加**: 動画冒頭にテロップをオーバーレイ表示（透過背景、日本語対応）
- **BGM追加**: 背景音楽を追加（元動画の音声とミックス、ループ再生、フェードアウト対応）
- **解像度統一**: 異なる解像度の動画を540x960（縦向き）に統一

## フォルダ構成

```
video-memory-maker/
├── main.py              # メインスクリプト
├── config.py            # 設定値
├── input/               # ★ 入力動画をここに入れる
├── output/              # ★ 出力動画がここに保存される
│   └── face_previews/   # 顔選択モード時のプレビュー画像
├── modules/             # 処理モジュール
│   ├── video_loader.py      # 動画読み込み
│   ├── face_detector.py     # 顔検出・笑顔検出（MediaPipe）
│   ├── face_identifier.py   # 顔識別・クラスタリング（InsightFace）
│   ├── video_composer.py    # 動画合成・テロップオーバーレイ
│   ├── title_generator.py   # テロップ生成
│   └── scan_cache.py        # スキャン結果キャッシュ
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

### 基本的な使い方

#### 1. 動画を配置

`input/` フォルダに処理したい動画ファイル（.mp4, .mov, .avi）を入れる

#### 2. 実行

```bash
# 基本（inputフォルダの動画を処理し、outputフォルダに保存）
uv run python main.py -i input -o output

# テロップ付き（動画に透過オーバーレイ表示）
uv run python main.py -i input -o output -t "2024年1月の思い出"

# 抽出時間を2秒に変更
uv run python main.py -i input -o output -d 2

# BGM付き（元動画の音声とミックス）
uv run python main.py -i input -o output -a "bgm.mp3"
```

#### 3. 出力を確認

`output/` フォルダに `YYYYMMDD_highlight_video.mp4` が生成される

### 顔選択モード

特定の人物（赤ちゃんなど）だけを対象にハイライト動画を作成できます。

```bash
# 顔選択モードで実行（対話形式）
uv run python main.py -i input -o output --select-faces
```

**処理の流れ:**

1. **Phase 1: スキャン** - 全動画をスキャンし、映っている人物を検出・クラスタリング
2. 検出された人物のプレビュー画像が `output/face_previews/` に保存される
3. 顔選択ウィンドウが表示されるので、対象の人物にチェックを入れて「決定」をクリック
4. **Phase 2: 抽出** - 選択した人物が映っている動画はその人物を優先、それ以外の動画も通常の顔検出でハイライト動画を生成（**全動画を活用**）

```bash
# 事前に人物IDを指定して実行
uv run python main.py -i input -o output --select-faces --face-ids 0,1

# スキャン結果のキャッシュを無視して再スキャン
uv run python main.py -i input -o output --select-faces --rescan

# 全員を対象（スキャン結果は保存）
uv run python main.py -i input -o output --select-faces --face-ids all
```

## フレーム選択アルゴリズム

各動画から最適なシーンを選択する際、以下の要素を総合的に評価します：

| 要素 | 重み | 説明 |
|------|------|------|
| 顔の大きさ | 35% | 顔が大きく映っているシーンを優先 |
| 笑顔スコア | 35% | 笑顔など表情豊かなシーンを優先 |
| 中央配置 | 20% | 顔がフレーム中央に近いシーンを優先 |
| 検出信頼度 | 10% | 顔検出の確信度が高いシーンを優先 |

## コマンドラインオプション

### 基本オプション

| オプション | 短縮形 | 必須 | 説明 | デフォルト |
|-----------|--------|------|------|-----------|
| `--input` | `-i` | ✓ | 入力動画フォルダ | - |
| `--output` | `-o` | | 出力フォルダ | 入力と同じ |
| `--audio` | `-a` | | BGMファイル | なし |
| `--title` | `-t` | | テロップテキスト | なし |
| `--clip-duration` | `-d` | | 抽出秒数 | 1.0 |
| `--title-duration` | | | テロップ表示秒数 | 3.0 |
| `--title-font-size` | | | フォントサイズ | 48 |
| `--title-text-color` | | | テロップ文字色 | #FFFFFF |

### 顔選択オプション

| オプション | 説明 |
|-----------|------|
| `--select-faces` | 顔選択モードを有効化 |
| `--face-ids` | 対象の人物ID（カンマ区切り、または 'all'） |
| `--rescan` | キャッシュを無視して再スキャン |

## 出力仕様

- **ファイル名**: `YYYYMMDD_highlight_video.mp4`
- **解像度**: 540x960 (縦向き)
- **フレームレート**: 30fps
- **音声**: 元動画の音声を保持（+ BGM指定時はミックス）

## 対応フォーマット

- MP4 (.mp4)
- MOV (.mov)
- AVI (.avi)

## 注意事項

- 初回実行時に以下のモデルが自動ダウンロードされます：
  - 顔検出モデル（約200KB）
  - 笑顔検出用ランドマークモデル（約4MB）
- 顔選択モード初回実行時にInsightFaceモデル（約300MB）が追加でダウンロードされます
- 処理時間目安：10本で約3〜5分（笑顔検出により若干増加）

## 依存ライブラリ

- **MediaPipe**: 顔検出・笑顔検出
- **InsightFace**: 顔識別・埋め込み抽出
- **scikit-learn**: DBSCANクラスタリング
- **OpenCV**: 画像処理
- **FFmpeg**: 動画処理

## ライセンス

MIT License
