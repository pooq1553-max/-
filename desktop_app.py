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
from faceswap.video import probe_video, swap_video
from faceswap.identity import build_identity
from faceswap.mosaic import mosaic_video
from faceswap.masks import preserve_expression
from faceswap.enhance import (
    FaceEnhancer,
    download_enhancer,
    enhancer_model_path,
    verify_enhancer_model,
)


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


_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def _prevent_sleep(keep_display: bool = False) -> None:
    """작업 중 시스템 절전을 막는다 (화면은 꺼져도 됨). Windows 전용, 실패 시 무시."""
    flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
    if keep_display:
        flags |= _ES_DISPLAY_REQUIRED
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def _allow_sleep() -> None:
    """절전 억제 해제 (평소 동작으로 복귀)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
    except Exception:
        pass


def _err_detail(e: Exception) -> str:
    """에러 메시지에 발생 위치를 덧붙인다 (스크린샷 한 장으로 원인 파악 가능하게)."""
    import traceback
    tb = traceback.format_exc().strip()
    lines = [ln for ln in tb.split("\n") if ln.strip()]
    tail = "\n".join(lines[-6:])
    return f"{e}\n\n--- 자세한 위치 ---\n{tail}"


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
        # 평균 정체성 캐시 (소스 사진 목록이 바뀌면 None으로 초기화)
        self._identity_cache = None
        self._v_identity_cache = None
        # 화질 개선 (GFPGAN ONNX) — 처음 켤 때 모델 로드
        self.enhancer: FaceEnhancer | None = None
        self.enhance_photo = BooleanVar(value=False)
        self.enhance_video = BooleanVar(value=False)
        self.enhance_strength = StringVar(value="보통")
        self.enhance_strength_v = StringVar(value="보통")

        # photo state
        self.source_path: str | None = None
        self.source_paths: list[str] = []
        self.source_count_var = StringVar(value="")
        self.target_path: str | None = None
        self.result_bgr = None
        self.replace_all_photo = BooleanVar(value=False)
        self.keep_mouth_photo = BooleanVar(value=True)
        self.keep_eyes_photo = BooleanVar(value=False)
        self.status_var = StringVar(value="사진 두 장을 선택한 뒤 '스왑 실행' 버튼을 누르세요.")

        # video state
        self.v_source_path: str | None = None
        self.v_source_paths: list[str] = []
        self.v_source_count_var = StringVar(value="")
        self.v_target_path: str | None = None
        self.v_output_path: str | None = None
        self.v_replace_all = BooleanVar(value=False)
        self.v_target_info = StringVar(value="선택된 동영상 없음")
        self.v_output_info = StringVar(value="선택된 저장 경로 없음")
        self.v_status = StringVar(value="사진 + 동영상 + 저장 경로 선택 후 시작.")
        self.v_eta = StringVar(value="")
        self.v_running = False
        self.v_resolution = StringVar(value="원본 유지")
        self.v_target_mode = StringVar(value="가장 큰 얼굴만")
        # inswapper는 입 벌림 같은 큰 표정 변화를 잘 못 따라온다. 입을 원본
        # 픽셀로 되돌리면 말하는 움직임이 살아나므로 기본으로 켜 둔다.
        self.v_keep_mouth = BooleanVar(value=True)
        self.v_keep_eyes = BooleanVar(value=False)
        self.v_keep_strength = StringVar(value="보통")
        self.v_shutdown = BooleanVar(value=False)
        self._video_proc_start: float | None = None

        # mosaic state
        self.mo_input_path: str | None = None
        self.mo_output_path: str | None = None
        self.mo_ref_paths: list[str] = []
        self.mo_input_info = StringVar(value="선택된 동영상 없음")
        self.mo_output_info = StringVar(value="선택된 저장 경로 없음")
        self.mo_ref_info = StringVar(value="기준 사진 없음")
        self.mo_target = StringVar(value="모든 얼굴")
        self.mo_style = StringVar(value="모자이크")
        self.mo_strength = StringVar(value="보통")
        self.mo_shape = StringVar(value="타원")
        self.mo_resolution = StringVar(value="원본 유지")
        self.mo_status = StringVar(value="동영상과 저장 경로를 고르고 시작하세요.")
        self.mo_eta = StringVar(value="")
        self.mo_running = False
        self._mo_cancel = False
        self._mo_proc_start: float | None = None
        self._mo_identity_cache = None


        self._build_ui()
        self._tray_icon = None
        self._setup_tray()

    # ------------------------------------------------------------ UI --------
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.notebook = nb
        self.photo_tab = Frame(nb)
        self.video_tab = Frame(nb)
        self.mosaic_tab = Frame(nb)
        nb.add(self.photo_tab, text="  사진 스왑  ")
        nb.add(self.video_tab, text="  동영상 스왑  ")
        nb.add(self.mosaic_tab, text="  모자이크  ")

        self._build_photo_tab(self.photo_tab)
        self._build_video_tab(self.video_tab)
        self._build_mosaic_tab(self.mosaic_tab)

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

        self.src_canvas = self._make_panel(
            panels, "소스 (얼굴 가져올 사진)", self._pick_source, 0,
            count_var=self.source_count_var,
            hint="여러 장 선택 가능 (Ctrl+클릭)\n각도·표정이 다른 사진 3~6장이면 더 정확",
        )
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

        pkeep = Frame(parent, padx=8)
        pkeep.pack(fill="x", pady=(0, 4))
        Checkbutton(
            pkeep, text="원본 입 모양 유지", variable=self.keep_mouth_photo,
        ).pack(side="left")
        Checkbutton(
            pkeep, text="원본 눈 유지", variable=self.keep_eyes_photo,
        ).pack(side="left", padx=(12, 0))
        Label(
            pkeep,
            text="  타깃 사진이 입을 벌리고 있을 때 그 모양을 살립니다.",
            fg="#666", font=("Segoe UI", 9),
        ).pack(side="left")

        enh = Frame(parent, padx=8)
        enh.pack(fill="x", pady=(0, 4))
        Checkbutton(
            enh,
            text="화질 개선 (스왑된 얼굴 선명하게)",
            variable=self.enhance_photo,
        ).pack(side="left")
        Label(enh, text="강도:").pack(side="left", padx=(12, 0))
        ttk.Combobox(
            enh, textvariable=self.enhance_strength,
            values=["약하게", "보통", "강하게"], state="readonly", width=8,
        ).pack(side="left", padx=(6, 0))
        Label(
            enh,
            text="  강할수록 선명하지만 과하면 인위적으로 보여요.",
            fg="#666", font=("Segoe UI", 9),
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

        Label(parent, textvariable=self.status_var, fg="#555",
              wraplength=980, justify="center").pack(pady=(2, 8))

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
        Label(left, textvariable=self.v_source_count_var, fg="#1565c0",
              font=("Segoe UI", 9, "bold")).pack()
        Label(left, text="여러 장 선택 가능 (Ctrl+클릭)\n각도·표정이 다른 사진 3~6장이면 더 정확",
              fg="#888", font=("Segoe UI", 8), justify="center").pack()

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
        Label(ctrl, text="교체 대상:").pack(side="left")
        ttk.Combobox(
            ctrl,
            textvariable=self.v_target_mode,
            values=["가장 큰 얼굴만", "모든 얼굴", "여성 얼굴만", "남성 얼굴만"],
            state="readonly",
            width=16,
        ).pack(side="left", padx=(6, 0))
        Label(
            ctrl,
            text="  (성별은 자동 추정이라 가끔 틀릴 수 있어요)",
            fg="#666", font=("Segoe UI", 9),
        ).pack(side="left")

        res_row = Frame(parent, padx=8)
        res_row.pack(fill="x", pady=(0, 4))
        Label(res_row, text="처리 해상도:").pack(side="left")
        ttk.Combobox(
            res_row,
            textvariable=self.v_resolution,
            values=["원본 유지", "720p (2배 빠름)", "540p (3~4배 빠름)", "480p (5배 빠름)"],
            state="readonly",
            width=22,
        ).pack(side="left", padx=(6, 0))
        Label(
            res_row,
            text="  결과 영상이 선택한 해상도로 저장됨. 낮을수록 빠르고 파일 작지만 화질 손해.",
            fg="#666", font=("Segoe UI", 9),
        ).pack(side="left")

        keep = Frame(parent, padx=8)
        keep.pack(fill="x", pady=(0, 4))
        Checkbutton(
            keep,
            text="원본 입 모양 유지 (말하는 움직임 살리기)",
            variable=self.v_keep_mouth,
        ).pack(side="left")
        Checkbutton(
            keep,
            text="원본 눈 유지 (깜빡임·시선)",
            variable=self.v_keep_eyes,
        ).pack(side="left", padx=(12, 0))
        Label(keep, text="강도:").pack(side="left", padx=(12, 0))
        ttk.Combobox(
            keep, textvariable=self.v_keep_strength,
            values=["약하게", "보통", "강하게"], state="readonly", width=8,
        ).pack(side="left", padx=(6, 0))
        Label(
            keep,
            text="  끄면 소스 사진의 다문 입이 그대로 붙습니다.",
            fg="#666", font=("Segoe UI", 9),
        ).pack(side="left")

        venh = Frame(parent, padx=8)
        venh.pack(fill="x", pady=(0, 4))
        Checkbutton(
            venh,
            text="화질 개선 (스왑된 얼굴 선명하게)",
            variable=self.enhance_video,
        ).pack(side="left")
        Label(venh, text="강도:").pack(side="left", padx=(12, 0))
        ttk.Combobox(
            venh, textvariable=self.enhance_strength_v,
            values=["약하게", "보통", "강하게"], state="readonly", width=8,
        ).pack(side="left", padx=(6, 0))
        Label(
            venh,
            text="  ⚠ 켜면 처리 시간이 2~3배 늘어요. 해상도를 함께 낮추면 상쇄됩니다.",
            fg="#a33", font=("Segoe UI", 9),
        ).pack(side="left")

        sd_row = Frame(parent, padx=8)
        sd_row.pack(fill="x", pady=(0, 4))
        Checkbutton(
            sd_row,
            text="스왑 완료 후 컴퓨터 자동 종료 (완료 시 60초 카운트다운, 취소 가능)",
            variable=self.v_shutdown,
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
        Label(parent, textvariable=self.v_status, fg="#555",
              wraplength=980, justify="center").pack(pady=(2, 0))
        # 남은 시간은 한 줄에 몰아넣으면 창 밖으로 잘리므로 따로, 크게 표시한다
        Label(parent, textvariable=self.v_eta, fg="#1565c0",
              font=("Segoe UI", 11, "bold"),
              wraplength=980, justify="center").pack(pady=(0, 8))

    def _make_panel(self, parent: Frame, title: str, pick_cb, col: int,
                    count_var: StringVar | None = None, hint: str = "") -> Canvas:
        frame = Frame(parent, padx=6, pady=6)
        frame.grid(row=0, column=col, sticky="nsew")
        Label(frame, text=title, font=("Segoe UI", 11, "bold")).pack()
        canvas = Canvas(frame, width=THUMB, height=THUMB, bg="#f0f0f0",
                        highlightthickness=1, highlightbackground="#ccc")
        canvas.pack(pady=6)
        Button(frame, text="사진 선택...", command=pick_cb, padx=12, pady=4).pack()
        if count_var is not None:
            Label(frame, textvariable=count_var, fg="#1565c0",
                  font=("Segoe UI", 9, "bold")).pack()
        if hint:
            Label(frame, text=hint, fg="#888", font=("Segoe UI", 8),
                  justify="center").pack()
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
        paths = filedialog.askopenfilenames(
            title="소스 사진 선택 (여러 장 고르면 더 정확해져요)",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")])
        if not paths:
            return
        self.source_paths = list(paths)
        self.source_path = self.source_paths[0]
        self._identity_cache = None
        self._show_file(self.src_canvas, self.source_path)
        n = len(self.source_paths)
        self.source_count_var.set(
            f"{n}장 사용 (평균 정체성)" if n > 1 else "1장 사용"
        )

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

    # -------------------------------------------------------- 화질 개선(GFPGAN)
    _STRENGTH_MAP = {"약하게": 0.5, "보통": 0.8, "강하게": 1.0}

    def _enhancer_ready(self) -> bool:
        p = enhancer_model_path()
        return p.exists() and verify_enhancer_model(p)

    def _ensure_enhancer_downloaded(self) -> bool:
        """모델이 없으면 물어보고 받는다. 지금 바로 쓸 수 있으면 True."""
        if self._enhancer_ready():
            return True
        if not messagebox.askyesno(
            "화질 개선 모델 필요",
            "화질 개선을 처음 쓰려면 모델 파일(약 330MB)을 받아야 해요.\n\n"
            "지금 받을까요? (몇 분 걸립니다)",
        ):
            return False
        self._download_enhancer_async()
        return False

    def _download_enhancer_async(self) -> None:
        self.status_var.set("화질 개선 모델 다운로드 중...")
        self.v_status.set("화질 개선 모델 다운로드 중...")

        def worker():
            try:
                def prog(seen, total):
                    if total:
                        msg = f"화질 개선 모델 다운로드 {seen/1e6:.0f} / {total/1e6:.0f} MB"
                    else:
                        msg = f"화질 개선 모델 다운로드 {seen/1e6:.0f} MB"
                    self.root.after(0, self.status_var.set, msg)
                    self.root.after(0, self.v_status.set, msg)

                download_enhancer(progress=prog)
                self.root.after(0, messagebox.showinfo, "다운로드 완료",
                                "화질 개선 모델 준비됐어요.\n'화질 개선'을 켜고 다시 실행하세요.")
                self.root.after(0, self.status_var.set, "화질 개선 모델 준비 완료")
                self.root.after(0, self.v_status.set, "화질 개선 모델 준비 완료")
            except Exception as e:
                self.root.after(0, messagebox.showerror, "다운로드 실패", str(e))
                self.root.after(0, self.status_var.set, "화질 개선 모델 다운로드 실패")
                self.root.after(0, self.v_status.set, "화질 개선 모델 다운로드 실패")

        threading.Thread(target=worker, daemon=True).start()

    def _get_enhancer(self, status_setter) -> FaceEnhancer:
        if self.enhancer is None:
            status_setter("화질 개선 모델 로딩 중...")
            self.enhancer = FaceEnhancer(enhancer_model_path())
        return self.enhancer

    def _get_identity(self, pipe, paths, cache_attr: str, status_setter):
        """소스 사진 목록에서 평균 정체성을 만든다 (같은 목록이면 캐시 재사용)."""
        paths = [p for p in (paths or []) if p]
        if not paths:
            raise RuntimeError("소스 사진을 선택하세요.")

        cached = getattr(self, cache_attr, None)
        if cached is not None and cached[0] == tuple(paths):
            return cached[1]

        if len(paths) == 1:
            img = _imread_unicode(paths[0])
            if img is None:
                raise RuntimeError("소스 사진을 열 수 없어요.")
            faces = pipe.detector.detect(img)
            if not faces:
                raise RuntimeError("소스 사진에서 얼굴을 찾지 못했어요.")
            face = pipe.detector.select(faces, "largest")
        else:
            status_setter(f"소스 {len(paths)}장 분석 중...")
            face, report = build_identity(
                pipe.detector, paths,
                progress=lambda p, m: status_setter(m),
            )
            status_setter(report.summary_ko())
            if report.skipped:
                reasons = "\n".join(
                    f"  · {Path(p).name}: {why}" for p, why in report.skipped[:6]
                )
                self.root.after(
                    0, messagebox.showinfo, "일부 사진 제외됨",
                    f"{len(report.skipped)}장을 제외하고 "
                    f"{report.used_count}장으로 정체성을 만들었어요.\n\n{reasons}",
                )

        setattr(self, cache_attr, (tuple(paths), face))
        return face

    def _run_photo_swap(self) -> None:
        if not self.source_path:
            messagebox.showwarning("사진 필요", "소스 사진(얼굴 가져올 사진)을 먼저 선택하세요.")
            return
        if not self.target_path:
            messagebox.showwarning("사진 필요", "타깃 사진(얼굴 바꿀 사진)을 먼저 선택하세요.")
            return
        if self.enhance_photo.get() and not self._ensure_enhancer_downloaded():
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
            tgt_img = _imread_unicode(self.target_path)
            if tgt_img is None:
                raise RuntimeError("타깃 사진을 열 수 없어요.")

            src_face = self._get_identity(
                pipe, self.source_paths or [self.source_path],
                cache_attr="_identity_cache",
                status_setter=lambda s: self.root.after(0, self.status_var.set, s),
            )

            tgt_faces = pipe.detector.detect(tgt_img)
            if not tgt_faces:
                raise RuntimeError("타깃 사진에서 얼굴을 찾지 못했어요.")
            to_replace = (tgt_faces if self.replace_all_photo.get()
                          else [pipe.detector.select(tgt_faces, "largest")])
            self.root.after(0, self.status_var.set, f"스왑 중... ({len(to_replace)}개 얼굴)")
            result = tgt_img.copy()
            for tf in to_replace:
                result = pipe.swapper.swap(result, tf, src_face)

            # 입·눈을 원본으로 되돌려 타깃의 표정을 살린다 (화질 개선 전에)
            if self.keep_mouth_photo.get() or self.keep_eyes_photo.get():
                result = preserve_expression(
                    result, tgt_img, to_replace,
                    mouth=0.8 if self.keep_mouth_photo.get() else 0.0,
                    eyes=0.8 if self.keep_eyes_photo.get() else 0.0,
                )

            if self.enhance_photo.get():
                enhancer = self._get_enhancer(
                    lambda s: self.root.after(0, self.status_var.set, s))
                self.root.after(0, self.status_var.set, "화질 개선 중...")
                blend = self._STRENGTH_MAP.get(self.enhance_strength.get(), 0.8)
                result = enhancer.enhance_faces(result, to_replace, blend=blend)

            self.result_bgr = result
            self.root.after(0, self._on_photo_done, result, None)
        except Exception as e:
            self.root.after(0, self._on_photo_done, None, _err_detail(e))

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
        paths = filedialog.askopenfilenames(
            title="소스 사진 선택 (여러 장 고르면 더 정확해져요)",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")])
        if not paths:
            return
        self.v_source_paths = list(paths)
        self.v_source_path = self.v_source_paths[0]
        self._v_identity_cache = None
        self._show_file(self.v_src_canvas, self.v_source_path)
        n = len(self.v_source_paths)
        self.v_source_count_var.set(
            f"{n}장 사용 (평균 정체성)" if n > 1 else "1장 사용"
        )

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
        if self.enhance_video.get() and not self._ensure_enhancer_downloaded():
            return
        self.v_running = True
        self._cancel = False
        self._video_proc_start = None
        self.v_start_btn.config(state="disabled")
        self.v_cancel_btn.config(state="normal")
        self.v_progress.config(mode="determinate", value=0)
        self.v_status.set("시작 중...")
        self.v_eta.set("")
        threading.Thread(target=self._video_worker, daemon=True).start()

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        seconds = int(max(0, seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}시간 {m}분"
        if m > 0:
            return f"{m}분 {s}초"
        return f"{s}초"

    def _calc_progress(self, done: int, total: int, msg: str, start_ts):
        """진행률·상태문구·남은시간문구를 계산한다. 동영상 처리 탭들이 공유."""
        now = time.time()
        # 시작 시각은 프레임 처리 직전에 잡아두므로 첫 보고부터 경과 시간이
        # 0보다 크다. 혹시 없으면 여기서 잡는 안전망만 둔다.
        if start_ts is None:
            start_ts = now

        pct = (done / total * 100) if total > 0 else 0
        eta_text = ""
        if done > 0:
            elapsed = max(now - start_ts, 1e-3)
            fps = done / elapsed
            speed = (f"{fps:.1f} 프레임/초" if fps >= 1
                     else f"프레임당 {1.0 / fps:.1f}초")
            if total > 0:
                eta = max(total - done, 0) / fps
                eta_text = f"남은 시간 약 {self._fmt_eta(eta)}  ·  {speed}"
            else:
                # 일부 영상은 전체 프레임 수를 못 읽는다. 그래도 경과와 속도는 보여준다.
                eta_text = (f"경과 {self._fmt_eta(elapsed)}  ·  {speed}"
                            f"  ·  (전체 길이를 못 읽어 남은 시간 계산 불가)")

        text = f"{msg} · {pct:.1f}%" if total > 0 else msg
        return pct, text, eta_text, start_ts

    def _video_progress(self, done: int, total: int, msg: str) -> None:
        pct, text, eta_text, self._video_proc_start = self._calc_progress(
            done, total, msg, self._video_proc_start)
        self.root.after(0, lambda: (self.v_progress.config(value=pct),
                                     self.v_status.set(text),
                                     self.v_eta.set(eta_text)))

    def _mosaic_progress(self, done: int, total: int, msg: str) -> None:
        pct, text, eta_text, self._mo_proc_start = self._calc_progress(
            done, total, msg, self._mo_proc_start)
        self.root.after(0, lambda: (self.mo_progress.config(value=pct),
                                     self.mo_status.set(text),
                                     self.mo_eta.set(eta_text)))

    def _video_worker(self) -> None:
        start = time.time()
        _prevent_sleep()
        try:
            pipe = self._ensure_pipeline(lambda s: self.root.after(0, self.v_status.set, s))
            res_map = {"원본 유지": None, "720p (2배 빠름)": 720,
                       "540p (3~4배 빠름)": 540, "480p (5배 빠름)": 480}
            resize_height = res_map.get(self.v_resolution.get())
            mode_map = {"가장 큰 얼굴만": "largest", "모든 얼굴": "all",
                        "여성 얼굴만": "female", "남성 얼굴만": "male"}
            target_mode = mode_map.get(self.v_target_mode.get(), "largest")
            src_face = self._get_identity(
                pipe, self.v_source_paths or [self.v_source_path],
                cache_attr="_v_identity_cache",
                status_setter=lambda s: self.root.after(0, self.v_status.set, s),
            )
            enhancer = None
            enhance_blend = 0.8
            if self.enhance_video.get():
                enhancer = self._get_enhancer(
                    lambda s: self.root.after(0, self.v_status.set, s))
                enhance_blend = self._STRENGTH_MAP.get(self.enhance_strength_v.get(), 0.8)

            keep = self._STRENGTH_MAP.get(self.v_keep_strength.get(), 0.8)
            keep_mouth = keep if self.v_keep_mouth.get() else 0.0
            keep_eyes = keep if self.v_keep_eyes.get() else 0.0

            # 모델·정체성 준비가 모두 끝난 지금부터 재야 프레임 처리 속도가 정확하다
            self._video_proc_start = time.time()
            saved_path, warning = swap_video(
                pipeline=pipe,
                source_image_path=self.v_source_path,
                target_video_path=self.v_target_path,
                output_video_path=self.v_output_path,
                target_mode=target_mode,
                resize_height=resize_height,
                source_face=src_face,
                enhancer=enhancer,
                enhance_blend=enhance_blend,
                preserve_mouth=keep_mouth,
                preserve_eyes=keep_eyes,
                progress=self._video_progress,
                cancel=lambda: self._cancel,
            )
            # 지정한 곳에 못 써서 다른 이름으로 저장됐을 수 있다
            self.v_output_path = str(saved_path)
            elapsed = time.time() - start
            self.root.after(0, self._on_video_done, None, elapsed, warning)
        except Exception as e:
            self.root.after(0, self._on_video_done, _err_detail(e), None)
        finally:
            _allow_sleep()

    def _on_video_done(self, error, elapsed, warning=None) -> None:
        self.v_running = False
        self.v_start_btn.config(state="normal")
        self.v_cancel_btn.config(state="disabled")
        if error:
            self.v_progress.config(value=0)
            self.v_status.set("에러 또는 취소됨")
            self.v_eta.set("")
            messagebox.showerror("동영상 스왑 실패", error)
            return
        self.v_progress.config(value=100)
        m, s = divmod(int(elapsed), 60)
        self.v_status.set(f"완료 · 소요 {m}분 {s}초 · 저장 위치: {self.v_output_path}")
        self.v_eta.set("")
        if self.v_shutdown.get():
            self._start_shutdown_countdown()
            return
        body = f"저장됨:\n{self.v_output_path}\n\n소요 시간: {m}분 {s}초"
        if warning:
            # 저장은 됐지만 알아야 할 사정이 있는 경우 (경로 변경, 음성 누락 등)
            messagebox.showwarning("동영상 스왑 완료 (확인 필요)", f"{body}\n\n{warning}")
        else:
            messagebox.showinfo("동영상 스왑 완료", body)

    def _start_shutdown_countdown(self, seconds: int = 60) -> None:
        """스왑 완료 후 컴퓨터 종료를 예약하고, 취소 가능한 안내창을 띄운다."""
        import subprocess
        try:
            # 윈도우 종료 예약 (creationflags로 콘솔창 안 뜨게)
            subprocess.run(
                ["shutdown", "/s", "/t", str(seconds)],
                check=True, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            messagebox.showwarning(
                "자동 종료 실패",
                f"종료 명령 실행에 실패했어요. 수동으로 꺼주세요.\n{e}",
            )
            return
        self.v_status.set(f"완료 · {seconds}초 후 컴퓨터가 종료됩니다.")
        cancel = messagebox.askyesno(
            "자동 종료 예약됨",
            f"스왑 완료. {seconds}초 후 컴퓨터가 종료됩니다.\n\n"
            f"저장 위치:\n{self.v_output_path}\n\n"
            "지금 종료를 취소할까요?\n(예=취소하고 계속 켜둠 / 아니오=예정대로 종료)",
        )
        if cancel:
            try:
                subprocess.run(
                    ["shutdown", "/a"],
                    check=False, capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.v_status.set("자동 종료 취소됨. 컴퓨터는 계속 켜져 있어요.")
            except Exception:
                pass


    # ----------------------------------------------------------- mosaic UI
    _MO_TARGETS = {
        "모든 얼굴": "all",
        "가장 큰 얼굴만": "largest",
        "여성 얼굴만": "female",
        "남성 얼굴만": "male",
        "기준 인물만 가리기": "match",
        "기준 인물 빼고 전부 가리기": "except_match",
    }
    _MO_STYLES = {"모자이크": "pixelate", "흐리게": "blur"}
    _MO_SHAPES = {"타원": "ellipse", "사각형": "rect"}

    def _build_mosaic_tab(self, parent: Frame) -> None:
        wrap = Frame(parent, padx=16, pady=12)
        wrap.pack(fill="both", expand=True)

        Label(wrap, text="가릴 동영상", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(wrap, textvariable=self.mo_input_info, fg="#333",
              wraplength=900, justify="left").pack(anchor="w", pady=2)
        Button(wrap, text="동영상 선택...", command=self._mo_pick_input,
               padx=10, pady=4).pack(anchor="w")

        Label(wrap, text="").pack()
        Label(wrap, text="저장 경로", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(wrap, textvariable=self.mo_output_info, fg="#333",
              wraplength=900, justify="left").pack(anchor="w", pady=2)
        Button(wrap, text="저장 위치 지정...", command=self._mo_pick_output,
               padx=10, pady=4).pack(anchor="w")

        Label(wrap, text="").pack()
        row1 = Frame(wrap)
        row1.pack(fill="x", pady=2)
        Label(row1, text="가릴 대상:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.mo_target,
                     values=list(self._MO_TARGETS), state="readonly",
                     width=24).pack(side="left", padx=(6, 16))
        Label(row1, text="방식:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.mo_style,
                     values=list(self._MO_STYLES), state="readonly",
                     width=10).pack(side="left", padx=(6, 16))
        Label(row1, text="강도:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.mo_strength,
                     values=["약하게", "보통", "강하게"], state="readonly",
                     width=8).pack(side="left", padx=(6, 16))
        Label(row1, text="모양:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.mo_shape,
                     values=list(self._MO_SHAPES), state="readonly",
                     width=8).pack(side="left", padx=(6, 0))

        row2 = Frame(wrap)
        row2.pack(fill="x", pady=2)
        Label(row2, text="처리 해상도:").pack(side="left")
        ttk.Combobox(row2, textvariable=self.mo_resolution,
                     values=["원본 유지", "720p (2배 빠름)", "540p (3~4배 빠름)",
                             "480p (5배 빠름)"],
                     state="readonly", width=22).pack(side="left", padx=(6, 0))

        Label(wrap, text="").pack()
        ref_box = Frame(wrap)
        ref_box.pack(fill="x")
        Label(ref_box, text="기준 인물 사진",
              font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(ref_box,
              text="'기준 인물만' 또는 '기준 인물 빼고 전부'를 골랐을 때만 필요해요. "
                   "여러 장 고르면 더 정확합니다.",
              fg="#666", font=("Segoe UI", 9), wraplength=900,
              justify="left").pack(anchor="w")
        Label(ref_box, textvariable=self.mo_ref_info, fg="#333",
              wraplength=900, justify="left").pack(anchor="w", pady=2)
        Button(ref_box, text="기준 사진 선택...", command=self._mo_pick_ref,
               padx=10, pady=4).pack(anchor="w")

        btns = Frame(wrap)
        btns.pack(pady=(14, 4))
        self.mo_start_btn = Button(
            btns, text="모자이크 시작", command=self._run_mosaic,
            font=("Segoe UI", 13, "bold"),
            bg="#37474f", fg="white", padx=24, pady=10, relief="flat",
            activebackground="#21303a", activeforeground="white",
        )
        self.mo_start_btn.pack(side="left", padx=4)
        self.mo_cancel_btn = Button(
            btns, text="취소", command=self._mo_request_cancel,
            padx=16, pady=8, state="disabled")
        self.mo_cancel_btn.pack(side="left", padx=4)

        self.mo_progress = ttk.Progressbar(wrap, mode="determinate",
                                           length=520, maximum=100)
        self.mo_progress.pack(pady=6, fill="x")
        Label(wrap, textvariable=self.mo_status, fg="#555",
              wraplength=900, justify="left").pack(anchor="w")
        Label(wrap, textvariable=self.mo_eta, fg="#1565c0",
              font=("Segoe UI", 11, "bold"),
              wraplength=900, justify="left").pack(anchor="w", pady=(0, 6))

    def _mo_pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="가릴 동영상 선택",
            filetypes=[("동영상", "*.mp4 *.mov *.avi *.mkv *.webm"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            info = probe_video(path)
        except Exception as e:
            messagebox.showerror("동영상 오류", str(e))
            return
        m, s = divmod(int(info["duration_sec"]), 60)
        self.mo_input_info.set(
            f"{Path(path).name}\n"
            f"{info['width']}x{info['height']} · {info['fps']:.1f} fps · {m}:{s:02d}")
        self.mo_input_path = path
        if not self.mo_output_path:
            # 실수로 원본을 덮어쓰지 않도록 기본 저장 이름을 미리 채워둔다
            p = Path(path)
            self.mo_output_path = str(p.with_name(f"{p.stem}_mosaic.mp4"))
            self.mo_output_info.set(self.mo_output_path)

    def _mo_pick_output(self) -> None:
        base = "mosaic.mp4"
        if self.mo_input_path:
            base = f"{Path(self.mo_input_path).stem}_mosaic.mp4"
        path = filedialog.asksaveasfilename(
            title="결과 저장 경로", defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4")], initialfile=base)
        if path:
            self.mo_output_path = path
            self.mo_output_info.set(path)

    def _mo_pick_ref(self) -> None:
        paths = filedialog.askopenfilenames(
            title="기준 인물 사진 선택 (여러 장 가능)",
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.webp"), ("모든 파일", "*.*")])
        if not paths:
            return
        self.mo_ref_paths = list(paths)
        self._mo_identity_cache = None
        n = len(self.mo_ref_paths)
        self.mo_ref_info.set(
            f"{n}장 선택됨" + (" (평균 정체성)" if n > 1 else "")
            + f" · {Path(self.mo_ref_paths[0]).name}" + (" 외" if n > 1 else ""))

    def _mo_request_cancel(self) -> None:
        self._mo_cancel = True
        self.mo_status.set("취소 요청됨... 현재 프레임 처리 후 중단.")

    def _run_mosaic(self) -> None:
        if self.mo_running:
            return
        if not self.mo_input_path:
            messagebox.showwarning("동영상 필요", "가릴 동영상을 먼저 선택하세요.")
            return
        if not self.mo_output_path:
            messagebox.showwarning("저장 경로 필요", "저장 위치를 지정하세요.")
            return
        mode = self._MO_TARGETS.get(self.mo_target.get(), "all")
        if mode in ("match", "except_match") and not self.mo_ref_paths:
            messagebox.showwarning(
                "기준 사진 필요",
                "'기준 인물' 모드를 쓰려면 그 사람의 사진을 선택해야 해요.")
            return

        self.mo_running = True
        self._mo_cancel = False
        self._mo_proc_start = None
        self.mo_start_btn.config(state="disabled")
        self.mo_cancel_btn.config(state="normal")
        self.mo_progress.config(value=0)
        self.mo_eta.set("")
        self.mo_status.set("시작 중...")
        threading.Thread(target=self._mosaic_worker, args=(mode,), daemon=True).start()

    def _mosaic_worker(self, mode: str) -> None:
        _prevent_sleep()
        try:
            pipe = self._ensure_pipeline(
                lambda s: self.root.after(0, self.mo_status.set, s))

            ref_embedding = None
            if mode in ("match", "except_match"):
                ref_face = self._get_identity(
                    pipe, self.mo_ref_paths,
                    cache_attr="_mo_identity_cache",
                    status_setter=lambda s: self.root.after(0, self.mo_status.set, s))
                ref_embedding = ref_face.embedding

            res_map = {"원본 유지": None, "720p (2배 빠름)": 720,
                       "540p (3~4배 빠름)": 540, "480p (5배 빠름)": 480}
            strength_map = {"약하게": 0.35, "보통": 0.6, "강하게": 0.9}

            self._mo_proc_start = time.time()
            saved_path, warning = mosaic_video(
                pipeline=pipe,
                target_video_path=self.mo_input_path,
                output_video_path=self.mo_output_path,
                mode=mode,
                reference_embedding=ref_embedding,
                style=self._MO_STYLES.get(self.mo_style.get(), "pixelate"),
                strength=strength_map.get(self.mo_strength.get(), 0.6),
                shape=self._MO_SHAPES.get(self.mo_shape.get(), "ellipse"),
                resize_height=res_map.get(self.mo_resolution.get()),
                progress=self._mosaic_progress,
                cancel=lambda: self._mo_cancel,
            )
            self.mo_output_path = str(saved_path)
            self.root.after(0, self._on_mosaic_done, None, warning)
        except Exception as e:
            self.root.after(0, self._on_mosaic_done, _err_detail(e), None)
        finally:
            _allow_sleep()

    def _on_mosaic_done(self, error, warning) -> None:
        self.mo_running = False
        self.mo_start_btn.config(state="normal")
        self.mo_cancel_btn.config(state="disabled")
        self.mo_eta.set("")
        if error:
            self.mo_progress.config(value=0)
            self.mo_status.set("에러 또는 취소됨")
            messagebox.showerror("모자이크 실패", error)
            return
        self.mo_progress.config(value=100)
        self.mo_status.set(f"완료 · 저장 위치: {self.mo_output_path}")
        body = f"저장됨:\n{self.mo_output_path}"
        if warning:
            messagebox.showwarning("모자이크 완료 (확인 필요)", f"{body}\n\n{warning}")
        else:
            messagebox.showinfo("모자이크 완료", body)


    # ------------------------------------------------------------- system tray
    def _setup_tray(self) -> None:
        try:
            import pystray
            from PIL import Image as _PImage, ImageDraw
        except Exception:
            # pystray/pillow 없으면 트레이 기능 없이 일반 최소화로 동작
            self._tray_icon = None
            return

        img = _PImage.new("RGB", (64, 64), "#1565c0")
        d = ImageDraw.Draw(img)
        d.ellipse((14, 12, 50, 48), fill="#ffd9b3")          # 얼굴
        d.ellipse((24, 26, 30, 32), fill="#333")              # 왼눈
        d.ellipse((37, 26, 43, 32), fill="#333")              # 오른눈
        d.arc((26, 30, 41, 44), 10, 170, fill="#994d00", width=2)  # 입

        menu = pystray.Menu(
            pystray.MenuItem("열기", self._tray_show, default=True),
            pystray.MenuItem("종료", self._tray_quit),
        )
        self._tray_icon = pystray.Icon("FaceSwap", img, "FaceSwap", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

        self.root.bind("<Unmap>", self._on_unmap)
        self.root.protocol("WM_DELETE_WINDOW", self._tray_quit)

    def _on_unmap(self, event) -> None:
        # 최소화 버튼을 눌렀을 때만 트레이로 숨김 (자식 위젯 이벤트 무시)
        if event.widget is self.root and self.root.state() == "iconic":
            if self._tray_icon is not None:
                self.root.withdraw()  # 작업표시줄에서도 사라지고 트레이에만 남음

    def _tray_show(self, icon=None, item=None) -> None:
        self.root.after(0, self._do_show)

    def _do_show(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _tray_quit(self, icon=None, item=None) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.root.after(0, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    FaceSwapApp().run()
