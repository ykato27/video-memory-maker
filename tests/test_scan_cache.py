"""modules/scan_cache.py の is_cache_valid 境界条件テスト。

is_cache_valid は内部で modules.video_loader.get_video_files を呼ぶが、
video_loader は cv2 に依存するため、テストでは sys.modules にスタブを
差し込んで scan_cache の判定ロジックだけを検証する。
"""

import json
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# modules/__init__.py は cv2 / mediapipe 等の重い依存を一括 import するため、
# テストでは __init__ を実行せず、scan_cache モジュールだけを直接読み込む。
import importlib.util  # noqa: E402

_pkg = types.ModuleType("modules")
_pkg.__path__ = [str(REPO_ROOT / "modules")]
sys.modules.setdefault("modules", _pkg)

_spec = importlib.util.spec_from_file_location(
    "modules.scan_cache", REPO_ROOT / "modules" / "scan_cache.py"
)
scan_cache = importlib.util.module_from_spec(_spec)
sys.modules["modules.scan_cache"] = scan_cache
_spec.loader.exec_module(scan_cache)


def _stub_video_loader(monkeypatch):
    fake = types.ModuleType("modules.video_loader")

    def get_video_files(folder_path: str):
        folder = Path(folder_path)
        return [str(p) for p in sorted(folder.glob("*.mp4"))]

    fake.get_video_files = get_video_files
    monkeypatch.setitem(sys.modules, "modules.video_loader", fake)



def _make_input_videos(input_dir: Path, count: int, mtime: datetime) -> list[Path]:
    input_dir.mkdir(parents=True, exist_ok=True)
    videos = []
    for i in range(count):
        p = input_dir / f"video_{i}.mp4"
        p.write_bytes(b"dummy")
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))
        videos.append(p)
    return videos


def _write_cache(
    output_dir: Path,
    *,
    video_count: int,
    cluster_count: int,
    timestamp: datetime,
    with_settings_hash: bool = True,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "scan_timestamp": timestamp.isoformat(),
        "video_count": video_count,
        "face_count": 3,
        "cluster_count": cluster_count,
        "detections": [],
        "clusters": [],
        "embeddings": {},
    }
    if with_settings_hash:
        data["settings_hash"] = scan_cache.settings_hash()
    cache_path = output_dir / scan_cache.SCAN_CACHE_FILE
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    # プレビュー画像を用意
    preview_dir = output_dir / scan_cache.FACE_PREVIEW_DIR
    preview_dir.mkdir(exist_ok=True)
    for i in range(cluster_count):
        (preview_dir / f"person_{i}.jpg").write_bytes(b"jpg")
    return cache_path


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    """動画2本・クラスタ1件の「本来は有効」なキャッシュ配置を作る。"""
    _stub_video_loader(monkeypatch)
    now = datetime.now()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _make_input_videos(input_dir, 2, now - timedelta(hours=2))
    _write_cache(
        output_dir,
        video_count=2,
        cluster_count=1,
        timestamp=now - timedelta(hours=1),
    )
    return input_dir, output_dir


def test_no_cache_file_is_invalid(tmp_path, monkeypatch):
    _stub_video_loader(monkeypatch)
    assert scan_cache.is_cache_valid(tmp_path / "out", tmp_path / "in") is False


def test_valid_cache(scenario):
    input_dir, output_dir = scenario
    assert scan_cache.is_cache_valid(output_dir, input_dir) is True


def test_settings_change_invalidates(scenario, monkeypatch):
    input_dir, output_dir = scenario
    monkeypatch.setattr(scan_cache, "FACE_CLUSTER_THRESHOLD", 0.99)
    assert scan_cache.is_cache_valid(output_dir, input_dir) is False


def test_settings_interval_change_invalidates(scenario, monkeypatch):
    input_dir, output_dir = scenario
    monkeypatch.setattr(scan_cache, "FACE_SCAN_INTERVAL", 9.9)
    assert scan_cache.is_cache_valid(output_dir, input_dir) is False


def test_legacy_cache_without_settings_hash_is_invalid(tmp_path, monkeypatch):
    _stub_video_loader(monkeypatch)
    now = datetime.now()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _make_input_videos(input_dir, 1, now - timedelta(hours=2))
    _write_cache(
        output_dir,
        video_count=1,
        cluster_count=0,
        timestamp=now - timedelta(hours=1),
        with_settings_hash=False,
    )
    assert scan_cache.is_cache_valid(output_dir, input_dir) is False


def test_video_count_mismatch_is_invalid(scenario):
    input_dir, output_dir = scenario
    # 3本目を追加（キャッシュは2本で作成）
    extra = input_dir / "video_2.mp4"
    extra.write_bytes(b"dummy")
    old = (datetime.now() - timedelta(hours=3)).timestamp()
    os.utime(extra, (old, old))
    assert scan_cache.is_cache_valid(output_dir, input_dir) is False


def test_newer_video_is_invalid(scenario):
    input_dir, output_dir = scenario
    newest = input_dir / "video_0.mp4"
    future = (datetime.now() + timedelta(hours=1)).timestamp()
    os.utime(newest, (future, future))
    assert scan_cache.is_cache_valid(output_dir, input_dir) is False


def test_missing_preview_is_invalid(scenario):
    input_dir, output_dir = scenario
    (output_dir / scan_cache.FACE_PREVIEW_DIR / "person_0.jpg").unlink()
    assert scan_cache.is_cache_valid(output_dir, input_dir) is False


def test_save_records_settings_hash(tmp_path, monkeypatch):
    _stub_video_loader(monkeypatch)

    class _Detection:
        video_path = "video_0.mp4"

        def to_dict(self):
            return {"video_path": self.video_path}

    class _Cluster:
        def to_dict(self):
            return {"cluster_id": 0}

    import numpy as np

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    cache_path = scan_cache.save_scan_results(
        [_Detection()], [_Cluster()], {"0": np.zeros(3)}, output_dir
    )
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["settings_hash"] == scan_cache.settings_hash()
