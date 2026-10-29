# Video Memory Maker

複数の動画ファイルから、子供の顔が映っている重要なシーンを自動抽出し、連結してハイライト動画を作成するツールです。

## 月ごとの1秒動画（写真にも対応）

`monthly.py` は、撮影日で月別に整理し、最大20点を各1秒ずつつなぐダイジェストを作ります。
[みてねの開発者による月版の解説](https://gihyo.jp/article/2023/07/mitene-07-1sec-movie)を参考にしています。
みてねの公式機能や、内部の選定アルゴリズムを再現するものではありません。

- 動画を優先し、動画が20本未満の月は写真で補います。素材の重複を除き、撮影日が偏らないように選びます。
- 動画は最大12場面を調べ、顔の大きさ・鮮明さ・明るさから1秒を選びます。特定の人物の識別や笑顔判定は行いません。
- 写真はJPEG・PNG・HEIC・HEIF・WebP、動画はMP4・MOV・M4V・AVI・MTS・3GPに対応します。
- 元の縦横比を保ち、余白にぼかした背景を置きます。撮影日と冒頭の年月を表示します。
- 元動画の音は既定で20%に抑え、BGMを一定の聞きやすい音量に整えてミックスします。大きな元音声が入るとBGMも緩やかに下げます。
- 出力は540×960・30fps・H.264/AACです。短い動画は最後のフレームで1秒まで補います。
- 完成した動画は上書きしません。一時ファイルは実行ごとに分かれます。

FFmpegとuvがあれば、旧モードの顔識別モデルやGUIを導入せずに実行できます。
Python 3.12または3.13を使ってください。必要なライブラリはスクリプト先頭の定義からuvが専用環境へ導入します。

```bash
# まず素材選定だけ確認（BGM生成も行わない）
uv run --script monthly.py -i input -o output/monthly --month 2026-09 --plan-only

# 既存のBGMを使用
uv run --script monthly.py -i input -o output/monthly --month 2026-09 --audio bgm/family.wav

# 撮影日のある全月を、月ごとに別ファイルへ出力
uv run --script monthly.py -i input -o output/monthly --audio bgm/family.wav

# 元音声をさらに小さくする
uv run --script monthly.py -i input -o output/monthly --original-volume 0.12 --bgm-volume 0.8 --audio bgm/family.wav
```

出力は `output/monthly/2026-09-memories.mp4` です。
採用素材・撮影日・切り出し位置・除外理由は `selection-日時.json` に保存します。
読み込めない素材があっても残りは出力しますが、終了コードは0にせず、一部を除外したことを知らせます。

### みてねから取得した素材の撮影日

みてねのブラウザ版の正規の「ダウンロード」で保存したファイルを入力にしてください。
取得・認証の自動化はこのスクリプトに含めていません。保存先には専用の素材フォルダを選んでください。
共有URL、パスワード、ブラウザの認証情報をリポジトリへ保存する必要はありません。

撮影日はEXIF、動画の撮影日時タグ、ファイル名の `YYYYMMDD` または `YYYY-MM-DD` から判定します。
動画は元の撮影日時タグを優先し、写真はEXIFの時差情報も読み取って日本時間で扱います。
ダウンロード時に変わるファイル更新日時は撮影日として使いません。
日付が消えた素材や、編集で日時が変わった素材には、みてねの詳細画面にある撮影日をCSVで指定してください。
CSVを指定した場合は、そのCSVに記載した素材だけを処理します。相対パスはCSVの場所が基準です。

```csv
path,taken_at,start_seconds
materials/first.mp4,2026-09-03T10:30:00,2.5
materials/second.jpg,2026-09-12,
```

```bash
uv run --script monthly.py -i input -o output/monthly --manifest input/dates.csv --audio bgm/family.wav
```

### Audio Studio MCPでオリジナルBGMを生成

[Audio Studio MCP](https://github.com/kanaworksai-hue/audio-studio-mcp/blob/main/README.ja.md)を案内に沿って導入し、モデルを取得した後に実行します。
`--audio-studio-python` には、その専用環境にあるPythonの絶対パスを指定してください。
設定済みのMCPサーバー登録は不要です。スクリプトがstdioでサーバーを起動し、必要な長さの音楽を1曲生成します。

```bash
uv run --script monthly.py -i input -o output/monthly --month 2026-09 \
  --audio-studio-python /absolute/path/to/audio-studio-mcp/.venv/bin/python
```

生成するのは、ピアノとアコースティックギターを中心とする、温かい雰囲気のオリジナル曲です。
写真・動画を音楽生成サーバーへ渡すことはありません。みてねの既存BGMを取得・複製する機能ではありません。
曲と生成条件は出力先の `music/` に保存します。モデル導入と音楽生成にはAudio Studio MCP側の動作要件・ライセンスが適用されます。

### 月版の検証

```bash
uv run --no-project --python 3.12 --with pytest --with pillow --with numpy \
  --with 'opencv-python-headless>=4.13,<5' --with pillow-heif --with tzdata pytest tests -q
```

撮影日・タイムゾーン・動画優先・重複除外に加え、FFmpegで写真、無音動画、音声付き動画とBGMを実際に合成し、長さと元音声の減衰量を検証します。

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
- テロップ用フォント（`assets/NotoSansJP-Regular.ttf`）はリポジトリに含まれていません。日本語テロップを使う場合は、別途フォントファイルを用意して配置してください（無い場合は代替フォントで描画されます）
- BGM用の音声ファイルはリポジトリに含まれていません。使う場合は `bgm/` フォルダに用意してください
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
