"""顔選択GUI モジュール"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from pathlib import Path
from dataclasses import dataclass
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FACE_PREVIEW_DIR


@dataclass
class FaceOption:
    """顔選択オプション"""
    cluster_id: int
    face_count: int
    video_count: int
    preview_image: Image.Image


def show_face_selector_gui(clusters, output_folder: Path) -> list[int]:
    """
    顔選択GUIを表示してユーザーに選択させる

    引数:
        clusters: PersonClusterのリスト
        output_folder: 出力フォルダ（プレビュー画像の場所）
    戻り値:
        選択されたクラスターIDのリスト
    """
    preview_dir = output_folder / FACE_PREVIEW_DIR
    
    # 選択結果を格納するリスト
    selected_ids = []
    
    # ウィンドウ作成
    root = tk.Tk()
    root.title("顔選択 - Video Memory Maker")
    root.configure(bg="#2b2b2b")
    
    # ウィンドウを画面中央に配置
    window_width = 600
    window_height = 500
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    # ヘッダー
    header = tk.Label(
        root,
        text="ハイライト動画に含める人物を選択してください",
        font=("Yu Gothic UI", 14, "bold"),
        fg="white",
        bg="#2b2b2b",
        pady=15,
    )
    header.pack()
    
    # サブヘッダー
    subheader = tk.Label(
        root,
        text="選択した人物が映っているシーンを優先的に抽出します\n（選択しなかった場合は全員を対象にします）",
        font=("Yu Gothic UI", 10),
        fg="#aaaaaa",
        bg="#2b2b2b",
    )
    subheader.pack()
    
    # スクロール可能なフレーム
    canvas = tk.Canvas(root, bg="#2b2b2b", highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg="#2b2b2b")
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # マウスホイールでスクロール
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
    canvas.pack(side="left", fill="both", expand=True, padx=20, pady=10)
    scrollbar.pack(side="right", fill="y")
    
    # チェックボックスの状態を保持
    check_vars = {}
    photo_images = []  # 参照を保持（GC防止）
    
    # 顔プレビューをグリッド表示
    cols = 3
    for idx, cluster in enumerate(clusters):
        row = idx // cols
        col = idx % cols
        
        # フレーム（カード風）
        card = tk.Frame(scrollable_frame, bg="#3c3c3c", padx=10, pady=10)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        
        # プレビュー画像を読み込み
        preview_path = preview_dir / f"person_{cluster.cluster_id}.jpg"
        if preview_path.exists():
            img = Image.open(preview_path)
            img = img.resize((120, 120), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            photo_images.append(photo)
            
            img_label = tk.Label(card, image=photo, bg="#3c3c3c")
            img_label.pack()
        
        # 情報ラベル
        video_count = len(cluster.video_appearances)
        info_text = f"ID: {cluster.cluster_id}\n{cluster.face_count}回検出\n{video_count}本の動画"
        info_label = tk.Label(
            card,
            text=info_text,
            font=("Yu Gothic UI", 9),
            fg="white",
            bg="#3c3c3c",
            justify="center",
        )
        info_label.pack(pady=5)
        
        # チェックボックス
        var = tk.BooleanVar(value=True)  # デフォルトで選択
        check_vars[cluster.cluster_id] = var
        
        check = tk.Checkbutton(
            card,
            text="選択",
            variable=var,
            font=("Yu Gothic UI", 10),
            fg="white",
            bg="#3c3c3c",
            selectcolor="#4a4a4a",
            activebackground="#3c3c3c",
            activeforeground="white",
        )
        check.pack()
    
    # ボタンフレーム
    button_frame = tk.Frame(root, bg="#2b2b2b", pady=15)
    button_frame.pack(fill="x")
    
    def on_confirm():
        """決定ボタンクリック時"""
        nonlocal selected_ids
        selected_ids = [cid for cid, var in check_vars.items() if var.get()]
        root.destroy()
    
    def on_select_all():
        """全選択"""
        for var in check_vars.values():
            var.set(True)
    
    def on_deselect_all():
        """全解除"""
        for var in check_vars.values():
            var.set(False)
    
    # ボタンスタイル
    button_style = {
        "font": ("Yu Gothic UI", 11),
        "padx": 20,
        "pady": 8,
        "cursor": "hand2",
    }
    
    # 全選択・全解除ボタン
    select_all_btn = tk.Button(
        button_frame,
        text="全選択",
        command=on_select_all,
        bg="#555555",
        fg="white",
        **button_style,
    )
    select_all_btn.pack(side="left", padx=10)
    
    deselect_all_btn = tk.Button(
        button_frame,
        text="全解除",
        command=on_deselect_all,
        bg="#555555",
        fg="white",
        **button_style,
    )
    deselect_all_btn.pack(side="left", padx=10)
    
    # 決定ボタン
    confirm_btn = tk.Button(
        button_frame,
        text="決定",
        command=on_confirm,
        bg="#4CAF50",
        fg="white",
        **button_style,
    )
    confirm_btn.pack(side="right", padx=20)
    
    # ウィンドウを閉じた場合は全選択として扱う
    def on_close():
        nonlocal selected_ids
        selected_ids = list(check_vars.keys())
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    
    # メインループ
    root.mainloop()
    
    # 何も選択されていない場合は全選択
    if not selected_ids:
        selected_ids = [c.cluster_id for c in clusters]
    
    return selected_ids
