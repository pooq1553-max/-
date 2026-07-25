"""Native desktop face-swap app (tkinter).

Three tabs: 사진 스왑, 동영상 스왑, 동영상 다운로드. No browser, no Gradio.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    Entry,
    Frame,
    Label,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    ttk,
)

import cv2
import numpy as np
from PIL import Image, ImageTk

from faceswap.pipeline import FaceSwapPipeline
from faceswap.video import probe_video, swap_video, trim_video


def _parse_time(text: str) -> float:
    text = text.strip()
    if not text:
        raise ValueError("시간이 비어있어요")
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        raise ValueError("시간 형식이 이상해요")
    return float(text)


def _format_time(sec: float) -> str:
    sec = max(0.0, sec)
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m}:{s:05.2f}"

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "inswapper_128.onnx"
THUMB = 300


def _imread_unicode(path: str):
    with open(path, "rb") as f:
        data = np.frombuffer(f.read(), np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _imwrite_unicode(path: str, img) -> bool:
    p = Path(path)
    ext = p.suffix if p.suffix else ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        f.write(buf.tobytes())
    return True


class FaceSwapApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("FaceSwap")
        self.root.geometry("1080x780")
        self.root.minsize(920, 700)

        self.pipeline: FaceSwapPipeline | None = None
        self._cancel = False

        # photo state
        self.source_path: str | None = None
        self.target_path: str | None = None
        self.result_bgr = None
        self.replace_all_photo = BooleanVar(value=False)
        self.status_var = StringVar(value="사진 두 장을 선택한 뒤 '스왑 실행' 버튼을 누르세요.")

        # video state
        self.v_source_path: str | None = None
        self.v_target_path: str | None = None
        self.v_output_path: str | None = None
        self.v_replace_all = BooleanVar(value=False)
        self.v_target_info = StringVar(value="선택된 동영상 없음")
        self.v_output_info = StringVar(value="선택된 저장 경로 없음")
        self.v_status = StringVar(value="사진 + 동영상 + 저장 경로 선택 후 시작.")
        self.v_running = False

        # download state
        default_dl = Path.home() / "Downloads"
        self.dl_url = StringVar(value="")
        self.dl_folder = StringVar(value=str(default_dl))
        self.dl_status = StringVar(value="URL 붙여넣고 다운로드 시작.")
        self.dl_running = False
        self.dl_last_file: str | None = None
        self.dl_send_after = BooleanVar(value=True)
        self.dl_browser = StringVar(value="없음")

        # trim state
        self.tr_input_path: str | None = None
        self.tr_output_path: str | None = None
        self.tr_input_info = StringVar(value="선택된 동영상 없음")
        self.tr_output_info = StringVar(value="선택된 저장 경로 없음")
        self.tr_start = StringVar(value="0:00")
        self.tr_end = StringVar(value="0:10")
        self.tr_reencode = BooleanVar(value=False)
        self.tr_send_after = BooleanVar(value=True)
        self.tr_status = StringVar(value="동영상 선택 → 시작/끝 시간 입력 → 자르기.")
        self.tr_duration_sec = 0.0

        self._build_ui()

    # ------------------------------------------------------------ UI --------
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.notebook = nb
        self.photo_tab = Frame(nb)
        self.video_tab = Frame(nb)
        self.download_tab = Frame(nb)
        self.trim_tab = Frame(nb)
        nb.add(self.photo_tab, text="  사진 스왑  ")
        nb.add(self.video_tab, text="  동영상 스왑  ")
        nb.add(self.download_tab, text="  동영상 다운로드  ")
        nb.add(self.trim_tab, text="  동영상 자르기  ")

        self._build_photo_tab(self.photo_tab)
        self._build_video_tab(self.video_tab)
        self._build_download_tab(self.download_tab)
        self._build_trim_tab(self.trim_tab)

        note = Label(
            self.root,
            text="주의: 등장 인물의 동의가 있는 사진/영상에만 사용하세요.",
            fg="#888",
            font=("Segoe UI", 9),
        )
        note.pack(side="bottom", pady=6)

    def _build_photo_tab(self, parent: Frame) -> None:
        panels = Frame(parent, padx=8, pady=8)
        panels.pack(fill="both", expand=True)

        self.src_canvas = self._make_panel(panels, "소스 (얼굴 가져올 사진)", self._pick_source, 0)
        self.tgt_canvas = self._make_panel(panels, "타깃 (얼굴 바꿀 사진)", self._pick_target, 1)
        self.res_canvas, self.save_btn = self._make_result_panel(panels, 2)

        for i in range(3):
            panels.columnconfigure(i, weight=1)

        ctrl = Frame(parent, padx=8, pady=4)
        ctrl.pack(fill="x")
        Checkbutton(
            ctrl,
            text="타깃의 모든 얼굴 교체 (기본: 가장 큰 얼굴만)",
            variable=self.replace_all_photo,
        ).pack(side="left")

        self.swap_btn = Button(
            parent,
            text="스왑 실행",
            command=self._run_photo_swap,
            font=("Segoe UI", 13, "bold"),
            bg="#2e7d32", fg="white", padx=24, pady=10, relief="flat",
            activebackground="#256428", activeforeground="white",
        )
        self.swap_btn.pack(pady=(4, 4))

        self.progress = ttk.Progressbar(parent, mode="indeterminate", length=400)
        self.progress.pack(pady=4)

        Label(parent, textvariable=self.status_var, fg="#555").pack(pady=(2, 8))

    def _build_video_tab(self, parent: Frame) -> None:
        top = Frame(parent, padx=8, pady=8)
        top.pack(fill="both", expand=True)

        # left: source photo
        left = Frame(top, padx=6, pady=6)
        left.grid(row=0, column=0, sticky="nsew")
        Label(left, text="소스 (얼굴 가져올 사진)", font=("Segoe UI", 11, "bold")).pack()
        self.v_src_canvas = Canvas(left, width=THUMB, height=THUMB, bg="#f0f0f0",
                                    highlightthickness=1, highlightbackground="#ccc")
        self.v_src_canvas.pack(pady=6)
        Button(left, text="사진 선택...", command=self._v_pick_source, padx=12, pady=4).pack()

        # right: video target + output
        right = Frame(top, padx=6, pady=6)
        right.grid(row=0, column=1, sticky="nsew")
        Label(right, text="타깃 (얼굴 바꿀 동영상)", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(right, textvariable=self.v_target_info, fg="#333", wraplength=460, justify="left").pack(anchor="w", pady=4)
        Button(right, text="동영상 선택...", command=self._v_pick_target, padx=12, pady=4).pack(anchor="w")

        Label(right, text="").pack()
        Label(right, text="저장 경로", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(right, textvariable=self.v_output_info, fg="#333", wraplength=460, justify="left").pack(anchor="w", pady=4)
        Button(right, text="저장 위치 지정...", command=self._v_pick_output, padx=12, pady=4).pack(anchor="w")

        top.columnconfigure(0, weight=0)
        top.columnconfigure(1, weight=1)

        ctrl = Frame(parent, padx=8, pady=4)
        ctrl.pack(fill="x")
        Checkbutton(
            ctrl,
            text="영상 속 모든 얼굴 교체 (기본: 프레임마다 가장 큰 얼굴만)",
            variable=self.v_replace_all,
        ).pack(side="left")

        btns = Frame(parent)
        btns.pack(pady=(4, 4))
        self.v_start_btn = Button(
            btns, text="동영상 스왑 시작", command=self._run_video_swap,
            font=("Segoe UI", 13, "bold"),
            bg="#1565c0", fg="white", padx=24, pady=10, relief="flat",
            activebackground="#0d47a1", activeforeground="white",
        )
        self.v_start_btn.pack(side="left", padx=4)
        self.v_cancel_btn = Button(
            btns, text="취소", command=self._request_cancel,
            padx=16, pady=8, state="disabled",
        )
        self.v_cancel_btn.pack(side="left", padx=4)

        self.v_progress = ttk.Progressbar(parent, mode="determinate", length=520, maximum=100)
        self.v_progress.pack(pady=6)
        Label(parent, textvariable=self.v_status, fg="#555").pack(pady=(2, 8))

    def _make_panel(self, parent: Frame, title: str, pick_cb, col: int) -> Canvas:
        frame = Frame(parent, padx=6, pady=6)
        frame.grid(row=0, column=col, sticky="nsew")
        Label(frame, text=title, font=("Segoe UI", 11, "bold")).pack()
        canvas = Canvas(frame, width=THUMB, height=THUMB, bg="#f0f0f0",
                        highlightthickness=1, highlightbackground="#ccc")
        canvas.pack(pady=6)
        Button(frame, text="사진 선택...", command=pick_cb, padx=12, pady=4).pack()
        return canvas

    def _make_result_panel(self, parent: Frame, col: int) -> tuple[Canvas, Button]:
        frame = Frame(parent, padx=6, pady=6)
        frame.grid(row=0, column=col, sticky="nsew")
        Label(frame, text="결과", font=("Segoe UI", 11, "bold")).pack()
        canvas = Canvas(frame, width=THUMB, height=THUMB, bg="#f0f0f0",
                        highlightthickness=1, highlightbackground="#ccc")
        canvas.pack(pady=6)
        save_btn = Button(frame, text="결과 저장...", command=self._save_result, padx=12, pady=4, state="disabled")
        save_btn.pack()
        return canvas, save_btn

    # ---------------------------------------------------------- pipeline ---
    def _ensure_pipeline(self, status_setter) -> FaceSwapPipeline:
        if self.pipeline is None:
            status_setter("모델 준비 중... (첫 실행이면 몇 분 걸릴 수 있음)")
            if not DEFAULT_MODEL_PATH.exists():
                raise FileNotFoundError(f"스왑 모델이 없어요: {DEFAULT_MODEL_PATH}\nsetup.bat 또는 download_models.py 를 먼저 실행하세요.")
            self.pipeline = FaceSwapPipeline(swap_model_path=DEFAULT_MODEL_PATH)
        return self.pipeline

    # ------------------------------------------------------- photo helpers -
    def _pick_source(self) -> None:
        path = filedialog.askopenfilename(title="소스 사진 선택",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")])
        if path:
            self.source_path = path
            self._show_file(self.src_canvas, path)

    def _pick_target(self) -> None:
        path = filedialog.askopenfilename(title="타깃 사진 선택",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")])
        if path:
            self.target_path = path
            self._show_file(self.tgt_canvas, path)

    def _show_file(self, canvas: Canvas, path: str) -> None:
        img = Image.open(path)
        img.thumbnail((THUMB, THUMB))
        photo = ImageTk.PhotoImage(img)
        canvas.image = photo
        canvas.delete("all")
        canvas.create_image(THUMB // 2, THUMB // 2, image=photo, anchor="center")

    def _show_bgr(self, canvas: Canvas, img_bgr) -> None:
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        pil_img.thumbnail((THUMB, THUMB))
        photo = ImageTk.PhotoImage(pil_img)
        canvas.image = photo
        canvas.delete("all")
        canvas.create_image(THUMB // 2, THUMB // 2, image=photo, anchor="center")

    def _run_photo_swap(self) -> None:
        if not self.source_path:
            messagebox.showwarning("사진 필요", "소스 사진(얼굴 가져올 사진)을 먼저 선택하세요.")
            return
        if not self.target_path:
            messagebox.showwarning("사진 필요", "타깃 사진(얼굴 바꿀 사진)을 먼저 선택하세요.")
            return
        self.swap_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.progress.start(10)
        self.status_var.set("처리 중...")
        threading.Thread(target=self._photo_worker, daemon=True).start()

    def _photo_worker(self) -> None:
        try:
            pipe = self._ensure_pipeline(lambda s: self.root.after(0, self.status_var.set, s))

            self.root.after(0, self.status_var.set, "얼굴 검출 중...")
            src_img = _imread_unicode(self.source_path)
            tgt_img = _imread_unicode(self.target_path)
            if src_img is None:
                raise RuntimeError("소스 사진을 열 수 없어요.")
            if tgt_img is None:
                raise RuntimeError("타깃 사진을 열 수 없어요.")

            src_faces = pipe.detector.detect(src_img)
            tgt_faces = pipe.detector.detect(tgt_img)
            if not src_faces:
                raise RuntimeError("소스 사진에서 얼굴을 찾지 못했어요.")
            if not tgt_faces:
                raise RuntimeError("타깃 사진에서 얼굴을 찾지 못했어요.")

            src_face = pipe.detector.select(src_faces, "largest")
            to_replace = (tgt_faces if self.replace_all_photo.get()
                          else [pipe.detector.select(tgt_faces, "largest")])
            self.root.after(0, self.status_var.set, f"스왑 중... ({len(to_replace)}개 얼굴)")
            result = tgt_img.copy()
            for tf in to_replace:
                result = pipe.swapper.swap(result, tf, src_face)

            self.result_bgr = result
            self.root.after(0, self._on_photo_done, result, None)
        except Exception as e:
            self.root.after(0, self._on_photo_done, None, str(e))

    def _on_photo_done(self, result, error) -> None:
        self.progress.stop()
        self.swap_btn.config(state="normal")
        if error:
            self.status_var.set("에러 발생")
            messagebox.showerror("에러", error)
            return
        self._show_bgr(self.res_canvas, result)
        self.save_btn.config(state="normal")
        self.status_var.set("완료. '결과 저장...' 버튼으로 파일 저장.")

    def _save_result(self) -> None:
        if self.result_bgr is None:
            return
        path = filedialog.asksaveasfilename(title="결과 저장", defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")], initialfile="faceswap_result.jpg")
        if path:
            if not _imwrite_unicode(path, self.result_bgr):
                messagebox.showerror("저장 실패", f"파일 저장에 실패했어요: {path}")
                return
            messagebox.showinfo("저장 완료", f"저장됨:\n{path}")

    # -------------------------------------------------------- video handlers
    def _v_pick_source(self) -> None:
        path = filedialog.askopenfilename(title="소스 사진 선택",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")])
        if path:
            self.v_source_path = path
            self._show_file(self.v_src_canvas, path)

    def _v_pick_target(self) -> None:
        path = filedialog.askopenfilename(title="타깃 동영상 선택",
            filetypes=[("동영상", "*.mp4 *.mov *.avi *.mkv *.webm"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            info = probe_video(path)
            dur = info["duration_sec"]
            m, s = divmod(int(dur), 60)
            self.v_target_info.set(
                f"{Path(path).name}\n"
                f"{info['width']}x{info['height']} · {info['fps']:.1f} fps · "
                f"{info['frames']} frames · {m}:{s:02d}"
            )
            self.v_target_path = path
        except Exception as e:
            messagebox.showerror("동영상 오류", str(e))

    def _v_pick_output(self) -> None:
        path = filedialog.asksaveasfilename(title="결과 동영상 저장 경로",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4")], initialfile="faceswap_result.mp4")
        if path:
            self.v_output_path = path
            self.v_output_info.set(path)

    def _request_cancel(self) -> None:
        self._cancel = True
        self.v_status.set("취소 요청됨... 현재 프레임 처리 후 중단.")

    def _run_video_swap(self) -> None:
        if not self.v_source_path:
            messagebox.showwarning("사진 필요", "소스 사진을 먼저 선택하세요.")
            return
        if not self.v_target_path:
            messagebox.showwarning("동영상 필요", "타깃 동영상을 먼저 선택하세요.")
            return
        if not self.v_output_path:
            messagebox.showwarning("저장 경로 필요", "결과 저장 경로를 지정하세요.")
            return
        self.v_running = True
        self._cancel = False
        self.v_start_btn.config(state="disabled")
        self.v_cancel_btn.config(state="normal")
        self.v_progress.config(mode="determinate", value=0)
        self.v_status.set("시작 중...")
        threading.Thread(target=self._video_worker, daemon=True).start()

    def _video_progress(self, done: int, total: int, msg: str) -> None:
        pct = (done / total * 100) if total > 0 else 0
        self.root.after(0, lambda: (self.v_progress.config(value=pct),
                                     self.v_status.set(f"{msg} · {pct:.1f}%")))

    def _video_worker(self) -> None:
        start = time.time()
        try:
            pipe = self._ensure_pipeline(lambda s: self.root.after(0, self.v_status.set, s))
            swap_video(
                pipeline=pipe,
                source_image_path=self.v_source_path,
                target_video_path=self.v_target_path,
                output_video_path=self.v_output_path,
                replace_all=self.v_replace_all.get(),
                progress=self._video_progress,
                cancel=lambda: self._cancel,
            )
            elapsed = time.time() - start
            self.root.after(0, self._on_video_done, None, elapsed)
        except Exception as e:
            self.root.after(0, self._on_video_done, str(e), None)

    def _on_video_done(self, error, elapsed) -> None:
        self.v_running = False
        self.v_start_btn.config(state="normal")
        self.v_cancel_btn.config(state="disabled")
        if error:
            self.v_progress.config(value=0)
            self.v_status.set("에러 또는 취소됨")
            messagebox.showerror("동영상 스왑 실패", error)
            return
        self.v_progress.config(value=100)
        m, s = divmod(int(elapsed), 60)
        self.v_status.set(f"완료 · 소요 {m}분 {s}초 · 저장 위치: {self.v_output_path}")
        messagebox.showinfo("동영상 스왑 완료",
            f"저장됨:\n{self.v_output_path}\n\n소요 시간: {m}분 {s}초")

    # ---------------------------------------------------------- download UI
    def _build_download_tab(self, parent: Frame) -> None:
        wrap = Frame(parent, padx=16, pady=16)
        wrap.pack(fill="both", expand=True)

        Label(wrap, text="동영상 URL", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(wrap, text="X(Twitter), YouTube, Instagram, TikTok 등 대부분 지원",
              fg="#666", font=("Segoe UI", 9)).pack(anchor="w")
        url_row = Frame(wrap)
        url_row.pack(fill="x", pady=(4, 8))
        entry = Entry(url_row, textvariable=self.dl_url, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        Button(url_row, text="클립보드에서 붙여넣기", command=self._dl_paste, padx=8).pack(side="left", padx=(6, 0))

        Label(wrap, text="").pack()
        Label(wrap, text="저장 폴더", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        folder_row = Frame(wrap)
        folder_row.pack(fill="x", pady=(4, 8))
        Entry(folder_row, textvariable=self.dl_folder, state="readonly", font=("Segoe UI", 10)).pack(
            side="left", fill="x", expand=True, ipady=4
        )
        Button(folder_row, text="폴더 선택...", command=self._dl_pick_folder, padx=8).pack(side="left", padx=(6, 0))

        Label(wrap, text="").pack()
        Label(wrap, text="로그인 필요한 트윗일 때만 사용 (브라우저에 X 로그인 되어 있어야 함)",
              font=("Segoe UI", 9), fg="#666").pack(anchor="w")
        browser_row = Frame(wrap)
        browser_row.pack(fill="x", pady=(2, 8))
        Label(browser_row, text="브라우저 쿠키:").pack(side="left")
        ttk.Combobox(
            browser_row,
            textvariable=self.dl_browser,
            values=["없음", "chrome", "edge", "firefox", "brave", "opera", "vivaldi"],
            state="readonly",
            width=12,
        ).pack(side="left", padx=(6, 0))

        Checkbutton(
            wrap,
            text="다운로드 완료 후 자동으로 '동영상 스왑' 탭에 이 파일 설정",
            variable=self.dl_send_after,
        ).pack(anchor="w")

        btns = Frame(wrap)
        btns.pack(pady=(12, 4))
        self.dl_start_btn = Button(
            btns, text="다운로드 시작", command=self._run_download,
            font=("Segoe UI", 13, "bold"),
            bg="#6a1b9a", fg="white", padx=24, pady=10, relief="flat",
            activebackground="#4a0072", activeforeground="white",
        )
        self.dl_start_btn.pack(side="left", padx=4)
        self.dl_open_btn = Button(
            btns, text="저장 폴더 열기", command=self._dl_open_folder, padx=16, pady=8,
        )
        self.dl_open_btn.pack(side="left", padx=4)

        self.dl_progress = ttk.Progressbar(wrap, mode="determinate", length=520, maximum=100)
        self.dl_progress.pack(pady=6, fill="x")
        Label(wrap, textvariable=self.dl_status, fg="#555", wraplength=800, justify="left").pack(anchor="w", pady=(2, 8))

    def _dl_paste(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
            if text:
                self.dl_url.set(text)
        except Exception:
            messagebox.showinfo("붙여넣기", "클립보드에 텍스트가 없어요.")

    def _dl_pick_folder(self) -> None:
        path = filedialog.askdirectory(title="저장 폴더 선택", initialdir=self.dl_folder.get())
        if path:
            self.dl_folder.set(path)

    def _dl_open_folder(self) -> None:
        folder = self.dl_folder.get()
        if folder and Path(folder).exists():
            try:
                os.startfile(folder)
            except Exception:
                messagebox.showinfo("폴더", folder)

    def _run_download(self) -> None:
        if self.dl_running:
            return
        url = self.dl_url.get().strip()
        folder = self.dl_folder.get().strip()
        if not url:
            messagebox.showwarning("URL 필요", "동영상 URL을 붙여넣으세요.")
            return
        if not folder:
            messagebox.showwarning("폴더 필요", "저장 폴더를 지정하세요.")
            return
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.dl_running = True
        self.dl_start_btn.config(state="disabled", text="다운로드 중...")
        self.dl_progress.config(value=0)
        self.dl_status.set("시작 중...")
        threading.Thread(target=self._dl_worker, args=(url, folder), daemon=True).start()

    def _dl_worker(self, url: str, folder: str) -> None:
        try:
            try:
                import yt_dlp
            except ImportError:
                raise RuntimeError(
                    "yt-dlp가 설치되지 않았어요. PowerShell에서 다음을 실행:\n"
                    "  .\\.venv\\Scripts\\python.exe -m pip install yt-dlp"
                )

            import shutil
            ffmpeg_path = None
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                ffmpeg_path = shutil.which("ffmpeg")

            def hook(d):
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    done = d.get("downloaded_bytes", 0)
                    speed = d.get("speed") or 0
                    eta = d.get("eta") or 0
                    pct = (done / total * 100) if total else 0
                    speed_mb = speed / (1024 * 1024) if speed else 0
                    msg = (
                        f"다운로드 중 · {done / 1e6:.1f} / "
                        f"{total / 1e6:.1f} MB · {speed_mb:.1f} MB/s · 남은 {eta}s"
                    )
                    self.root.after(0, lambda: (self.dl_progress.config(value=pct),
                                                self.dl_status.set(msg)))
                elif status == "finished":
                    self.dl_last_file = d.get("filename")
                    self.root.after(0, lambda: self.dl_status.set("병합/변환 중..."))

            ydl_opts = {
                "outtmpl": str(Path(folder) / "%(title).100B [%(id)s].%(ext)s"),
                "format": "bv*+ba/b" if ffmpeg_path else "b[ext=mp4]/b",
                "merge_output_format": "mp4",
                "restrictfilenames": True,
                "noplaylist": True,
                "progress_hooks": [hook],
                "quiet": True,
                "no_warnings": True,
                "color": "no_color",
            }
            if ffmpeg_path:
                ydl_opts["ffmpeg_location"] = ffmpeg_path

            browser = self.dl_browser.get()
            if browser and browser != "없음":
                ydl_opts["cookiesfrombrowser"] = (browser,)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if not Path(filepath).exists():
                    for ext in ("mp4", "mkv", "webm"):
                        cand = Path(filepath).with_suffix(f".{ext}")
                        if cand.exists():
                            filepath = str(cand)
                            break
                self.dl_last_file = filepath

            self.root.after(0, self._on_dl_done, filepath, None)
        except Exception as e:
            self.root.after(0, self._on_dl_done, None, str(e))

    def _on_dl_done(self, filepath, error) -> None:
        self.dl_running = False
        self.dl_start_btn.config(state="normal", text="다운로드 시작")
        if error:
            self.dl_progress.config(value=0)
            self.dl_status.set("에러 발생")
            import re as _re
            clean = _re.sub(r"\x1b\[[0-9;]*m", "", error)
            hint = ""
            low = clean.lower()
            if "no video could be found" in low or "unavailable" in low or "requires login" in low or "not authorized" in low:
                hint = (
                    "\n\n힌트:\n"
                    "• yt-dlp를 최신으로: pip install -U yt-dlp\n"
                    "• 로그인 필요한 트윗이면 위 '브라우저 쿠키' 드롭다운에서 로그인된 브라우저(chrome/edge 등) 선택 후 재시도"
                )
            messagebox.showerror("다운로드 실패", clean + hint)
            return
        self.dl_progress.config(value=100)
        self.dl_status.set(f"완료: {filepath}")
        if self.dl_send_after.get() and filepath:
            self._send_to_video_swap(filepath)
        else:
            messagebox.showinfo("다운로드 완료", f"저장됨:\n{filepath}")

    def _send_to_video_swap(self, video_path: str) -> None:
        try:
            info = probe_video(video_path)
            dur = info["duration_sec"]
            m, s = divmod(int(dur), 60)
            self.v_target_info.set(
                f"{Path(video_path).name}\n"
                f"{info['width']}x{info['height']} · {info['fps']:.1f} fps · "
                f"{info['frames']} frames · {m}:{s:02d}"
            )
            self.v_target_path = video_path
            self.notebook.select(self.video_tab)
            messagebox.showinfo(
                "다운로드 완료",
                f"동영상이 '동영상 스왑' 탭에 설정됐어요.\n소스 사진과 저장 경로만 지정하고 스왑을 시작하세요.",
            )
        except Exception:
            messagebox.showinfo("다운로드 완료", f"저장됨:\n{video_path}")

    # -------------------------------------------------------------- trim UI
    def _build_trim_tab(self, parent: Frame) -> None:
        wrap = Frame(parent, padx=16, pady=16)
        wrap.pack(fill="both", expand=True)

        Label(wrap, text="원본 동영상", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(wrap, textvariable=self.tr_input_info, fg="#333", wraplength=800, justify="left").pack(anchor="w", pady=4)
        Button(wrap, text="동영상 선택...", command=self._tr_pick_input, padx=10, pady=4).pack(anchor="w")

        Label(wrap, text="").pack()
        Label(wrap, text="자를 구간 (초 또는 분:초 형식, 예: 30 · 1:15 · 0:30)",
              font=("Segoe UI", 11, "bold")).pack(anchor="w")

        row = Frame(wrap)
        row.pack(fill="x", pady=(6, 0))
        Label(row, text="시작:").pack(side="left")
        Entry(row, textvariable=self.tr_start, font=("Segoe UI", 11), width=10).pack(side="left", padx=(4, 12))
        Label(row, text="끝:").pack(side="left")
        Entry(row, textvariable=self.tr_end, font=("Segoe UI", 11), width=10).pack(side="left", padx=(4, 12))
        self.tr_len_lbl = Label(row, text="", fg="#666")
        self.tr_len_lbl.pack(side="left")
        self.tr_start.trace_add("write", lambda *_: self._tr_update_length())
        self.tr_end.trace_add("write", lambda *_: self._tr_update_length())

        Checkbutton(
            wrap,
            text="정확한 구간 자르기 (재인코딩, 느림. 끄면 빠르지만 시작 시점이 최대 몇 초 어긋날 수 있음)",
            variable=self.tr_reencode,
        ).pack(anchor="w", pady=(8, 0))

        Label(wrap, text="").pack()
        Label(wrap, text="저장 경로", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(wrap, textvariable=self.tr_output_info, fg="#333", wraplength=800, justify="left").pack(anchor="w", pady=4)
        Button(wrap, text="저장 위치 지정...", command=self._tr_pick_output, padx=10, pady=4).pack(anchor="w")

        Checkbutton(
            wrap,
            text="자르기 완료 후 자동으로 '동영상 스왑' 탭에 이 파일 설정",
            variable=self.tr_send_after,
        ).pack(anchor="w", pady=(8, 0))

        btns = Frame(wrap)
        btns.pack(pady=(12, 4))
        self.tr_start_btn = Button(
            btns, text="자르기 시작", command=self._run_trim,
            font=("Segoe UI", 13, "bold"),
            bg="#ef6c00", fg="white", padx=24, pady=10, relief="flat",
            activebackground="#c25400", activeforeground="white",
        )
        self.tr_start_btn.pack(side="left", padx=4)

        self.tr_progress = ttk.Progressbar(wrap, mode="indeterminate", length=520)
        self.tr_progress.pack(pady=6, fill="x")
        Label(wrap, textvariable=self.tr_status, fg="#555", wraplength=800, justify="left").pack(anchor="w", pady=(2, 8))

    def _tr_pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="원본 동영상 선택",
            filetypes=[("동영상", "*.mp4 *.mov *.avi *.mkv *.webm"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            info = probe_video(path)
        except Exception as e:
            messagebox.showerror("동영상 오류", str(e))
            return
        dur = info["duration_sec"]
        self.tr_duration_sec = dur
        m, s = divmod(int(dur), 60)
        self.tr_input_info.set(
            f"{Path(path).name}\n"
            f"{info['width']}x{info['height']} · {info['fps']:.1f} fps · {m}:{s:02d}"
        )
        self.tr_input_path = path
        self.tr_end.set(_format_time(min(dur, 10.0)))
        self._tr_update_length()

    def _tr_pick_output(self) -> None:
        base = "trimmed.mp4"
        if self.tr_input_path:
            p = Path(self.tr_input_path)
            base = f"{p.stem}_trimmed.mp4"
        path = filedialog.asksaveasfilename(
            title="자른 동영상 저장 경로",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4")],
            initialfile=base,
        )
        if path:
            self.tr_output_path = path
            self.tr_output_info.set(path)

    def _tr_update_length(self) -> None:
        try:
            start = _parse_time(self.tr_start.get())
            end = _parse_time(self.tr_end.get())
            length = end - start
            if length > 0:
                self.tr_len_lbl.config(text=f"→ 길이 {length:.1f}초", fg="#333")
            else:
                self.tr_len_lbl.config(text="(끝이 시작보다 뒤여야 함)", fg="#c00")
        except Exception:
            self.tr_len_lbl.config(text="", fg="#666")

    def _run_trim(self) -> None:
        if not self.tr_input_path:
            messagebox.showwarning("동영상 필요", "원본 동영상을 먼저 선택하세요.")
            return
        if not self.tr_output_path:
            messagebox.showwarning("저장 경로 필요", "저장 위치를 지정하세요.")
            return
        try:
            start = _parse_time(self.tr_start.get())
            end = _parse_time(self.tr_end.get())
        except Exception:
            messagebox.showwarning("시간 형식", "시작/끝 시간을 숫자(초) 또는 분:초 형식으로 입력하세요.")
            return
        if end <= start:
            messagebox.showwarning("시간 오류", "끝 시간이 시작 시간보다 뒤여야 해요.")
            return
        if self.tr_duration_sec and end > self.tr_duration_sec + 0.5:
            if not messagebox.askokcancel(
                "확인",
                f"끝 시간({end:.1f}s)이 원본 길이({self.tr_duration_sec:.1f}s)보다 커요.\n계속 진행할까요?",
            ):
                return

        self.tr_start_btn.config(state="disabled", text="자르는 중...")
        self.tr_progress.start(10)
        self.tr_status.set("ffmpeg으로 자르는 중...")
        threading.Thread(target=self._tr_worker, args=(start, end), daemon=True).start()

    def _tr_worker(self, start: float, end: float) -> None:
        try:
            trim_video(
                input_path=self.tr_input_path,
                output_path=self.tr_output_path,
                start_sec=start,
                end_sec=end,
                reencode=self.tr_reencode.get(),
            )
            self.root.after(0, self._on_trim_done, None)
        except Exception as e:
            self.root.after(0, self._on_trim_done, str(e))

    def _on_trim_done(self, error) -> None:
        self.tr_progress.stop()
        self.tr_start_btn.config(state="normal", text="자르기 시작")
        if error:
            self.tr_status.set("에러 발생")
            messagebox.showerror("자르기 실패", error)
            return
        self.tr_status.set(f"완료: {self.tr_output_path}")
        if self.tr_send_after.get() and self.tr_output_path:
            self._send_to_video_swap(self.tr_output_path)
        else:
            messagebox.showinfo("자르기 완료", f"저장됨:\n{self.tr_output_path}")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    FaceSwapApp().run()
