"""Native desktop face-swap app (tkinter).

No browser, no Gradio. Only uses Python's built-in tkinter plus the packages
already needed by the CLI (opencv, insightface, pillow).

Run: `python desktop_app.py` (or double-click desktop.bat).
"""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
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


def _imread_unicode(path: str):
    """cv2.imread that works with non-ASCII paths on Windows."""
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

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "inswapper_128.onnx"
THUMB = 320


class FaceSwapApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("FaceSwap")
        self.root.geometry("1080x720")
        self.root.minsize(900, 640)

        self.source_path: str | None = None
        self.target_path: str | None = None
        self.result_bgr = None
        self.pipeline: FaceSwapPipeline | None = None
        self.replace_all = BooleanVar(value=False)
        self.status_var = StringVar(value="사진 두 장을 선택한 뒤 '스왑 실행' 버튼을 누르세요.")

        self._build_ui()

    def _build_ui(self) -> None:
        panels = Frame(self.root, padx=12, pady=12)
        panels.pack(fill="both", expand=True)

        self.src_canvas = self._make_panel(panels, "소스 (얼굴 가져올 사진)", self._pick_source, 0)
        self.tgt_canvas = self._make_panel(panels, "타깃 (얼굴 바꿀 사진)", self._pick_target, 1)
        self.res_canvas, self.save_btn = self._make_result_panel(panels, 2)

        for i in range(3):
            panels.columnconfigure(i, weight=1)

        ctrl = Frame(self.root, padx=12, pady=6)
        ctrl.pack(fill="x")
        Checkbutton(
            ctrl,
            text="타깃의 모든 얼굴 교체 (기본: 가장 큰 얼굴만)",
            variable=self.replace_all,
        ).pack(side="left")

        self.swap_btn = Button(
            self.root,
            text="스왑 실행",
            command=self._run_swap,
            font=("Segoe UI", 13, "bold"),
            bg="#2e7d32",
            fg="white",
            padx=24,
            pady=10,
            relief="flat",
            activebackground="#256428",
            activeforeground="white",
        )
        self.swap_btn.pack(pady=(8, 4))

        self.progress = ttk.Progressbar(self.root, mode="indeterminate", length=400)
        self.progress.pack(pady=4)

        Label(self.root, textvariable=self.status_var, fg="#555").pack(pady=(2, 12))

        note = Label(
            self.root,
            text="주의: 등장 인물의 동의가 있는 사진에만 사용하세요.",
            fg="#888",
            font=("Segoe UI", 9),
        )
        note.pack(side="bottom", pady=6)

    def _make_panel(self, parent: Frame, title: str, pick_cb, col: int) -> Canvas:
        frame = Frame(parent, padx=6, pady=6)
        frame.grid(row=0, column=col, sticky="nsew")
        Label(frame, text=title, font=("Segoe UI", 11, "bold")).pack()
        canvas = Canvas(frame, width=THUMB, height=THUMB, bg="#f0f0f0", highlightthickness=1, highlightbackground="#ccc")
        canvas.pack(pady=6)
        Button(frame, text="사진 선택...", command=pick_cb, padx=12, pady=4).pack()
        return canvas

    def _make_result_panel(self, parent: Frame, col: int) -> tuple[Canvas, Button]:
        frame = Frame(parent, padx=6, pady=6)
        frame.grid(row=0, column=col, sticky="nsew")
        Label(frame, text="결과", font=("Segoe UI", 11, "bold")).pack()
        canvas = Canvas(frame, width=THUMB, height=THUMB, bg="#f0f0f0", highlightthickness=1, highlightbackground="#ccc")
        canvas.pack(pady=6)
        save_btn = Button(frame, text="결과 저장...", command=self._save_result, padx=12, pady=4, state="disabled")
        save_btn.pack()
        return canvas, save_btn

    def _pick_source(self) -> None:
        path = filedialog.askopenfilename(
            title="소스 사진 선택",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")],
        )
        if path:
            self.source_path = path
            self._show_file(self.src_canvas, path)

    def _pick_target(self) -> None:
        path = filedialog.askopenfilename(
            title="타깃 사진 선택",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")],
        )
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

    def _run_swap(self) -> None:
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
        threading.Thread(target=self._swap_worker, daemon=True).start()

    def _swap_worker(self) -> None:
        try:
            if self.pipeline is None:
                self._set_status("모델 준비 중... (첫 실행이면 InsightFace 검출기 다운로드로 몇 분 걸릴 수 있음)")
                if not DEFAULT_MODEL_PATH.exists():
                    raise FileNotFoundError(f"스왑 모델이 없습니다: {DEFAULT_MODEL_PATH}\n먼저 setup.bat 또는 download_models.py를 실행하세요.")
                self.pipeline = FaceSwapPipeline(swap_model_path=DEFAULT_MODEL_PATH)

            self._set_status("얼굴 검출 중...")
            src_img = _imread_unicode(self.source_path)
            tgt_img = _imread_unicode(self.target_path)
            if src_img is None:
                raise RuntimeError("소스 사진을 열 수 없어요.")
            if tgt_img is None:
                raise RuntimeError("타깃 사진을 열 수 없어요.")

            src_faces = self.pipeline.detector.detect(src_img)
            tgt_faces = self.pipeline.detector.detect(tgt_img)
            if not src_faces:
                raise RuntimeError("소스 사진에서 얼굴을 찾지 못했어요.\n더 정면·고해상도 사진으로 시도해보세요.")
            if not tgt_faces:
                raise RuntimeError("타깃 사진에서 얼굴을 찾지 못했어요.")

            src_face = self.pipeline.detector.select(src_faces, "largest")
            to_replace = (
                tgt_faces if self.replace_all.get() else [self.pipeline.detector.select(tgt_faces, "largest")]
            )

            self._set_status(f"스왑 중... ({len(to_replace)}개 얼굴)")
            result = tgt_img.copy()
            for tf in to_replace:
                result = self.pipeline.swapper.swap(result, tf, src_face)

            self.result_bgr = result
            self.root.after(0, self._on_done, result, None)
        except Exception as e:
            self.root.after(0, self._on_done, None, str(e))

    def _set_status(self, text: str) -> None:
        self.root.after(0, self.status_var.set, text)

    def _on_done(self, result, error) -> None:
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
        path = filedialog.asksaveasfilename(
            title="결과 저장",
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")],
            initialfile="faceswap_result.jpg",
        )
        if path:
            if not _imwrite_unicode(path, self.result_bgr):
                messagebox.showerror("저장 실패", f"파일 저장에 실패했어요: {path}")
                return
            messagebox.showinfo("저장 완료", f"저장됨:\n{path}")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    FaceSwapApp().run()
