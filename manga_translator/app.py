#!/usr/bin/env python3
"""
만화 번역기 — 창 프로그램.

파일/폴더/zip 을 끌어다 놓거나 [추가] 버튼으로 넣고 [번역 시작]을 누르면 끝.
인자를 주고 실행하면 창 없이 명령줄 모드로 동작한다 (translate_manga.py 와 같음).
"""

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path


def _fix_std_streams():
    """창 모드 exe 에서는 stdout/stderr 가 None 이라 라이브러리 출력이 죽는다 → 로그 파일로 보낸다."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = Path.home() / ".manga_translator"
    log_dir.mkdir(parents=True, exist_ok=True)
    f = open(log_dir / "last_run.log", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


_fix_std_streams()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import translate_manga as tm

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # 끌어다 놓기는 없어도 버튼으로 쓸 수 있다
    TkinterDnD = None

LANGS = [("일본어", "ja"), ("영어", "en"), ("중국어", "zh")]
ENGINES = [("구글 번역 (무료)", "google"), ("Ollama 로컬 AI (무료, 고품질)", "ollama")]


def open_path(p):
    p = str(p)
    if sys.platform.startswith("win"):
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


class App:
    def __init__(self, root):
        self.root = root
        root.title("만화 번역기 — 한국어로 자동 번역")
        root.geometry("1000x680")
        root.minsize(820, 560)

        self.inputs = []
        self.msgs = queue.Queue()
        self.worker = None
        self.stop_flag = threading.Event()
        self.ocr_cache = {}          # 언어별 OCR 모델 (한 번 불러오면 재사용)
        self.last_out = None
        self.preview_img = None

        style = ttk.Style()
        style.configure("Big.TButton", font=("", 13, "bold"), padding=10)

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=0, minsize=420)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        # ── 왼쪽: 입력 목록 + 설정 ──
        left = ttk.Frame(main)
        left.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        hint = "번역할 폴더·zip·이미지를 여기로 끌어다 놓으세요" if TkinterDnD else "번역할 폴더·zip·이미지를 추가하세요"
        ttk.Label(left, text=hint, font=("", 11, "bold"), wraplength=400).grid(row=0, column=0, sticky="w")
        self.listbox = tk.Listbox(left, height=8, selectmode="extended", activestyle="none")
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=6)
        if TkinterDnD:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self.on_drop)

        btns = ttk.Frame(left)
        btns.grid(row=2, column=0, sticky="ew")
        ttk.Button(btns, text="폴더 추가", command=self.add_folder).pack(side="left")
        ttk.Button(btns, text="파일 추가", command=self.add_files).pack(side="left", padx=6)
        ttk.Button(btns, text="선택 삭제", command=self.remove_selected).pack(side="left")
        ttk.Button(btns, text="비우기", command=self.clear).pack(side="left", padx=6)

        opts = ttk.LabelFrame(left, text="설정", padding=10)
        opts.grid(row=3, column=0, sticky="ew", pady=10)
        opts.columnconfigure(1, weight=1)

        ttk.Label(opts, text="원문 언어").grid(row=0, column=0, sticky="w")
        self.lang_var = tk.StringVar(value=LANGS[0][0])
        ttk.Combobox(opts, textvariable=self.lang_var, values=[n for n, _ in LANGS], state="readonly",
                     width=24).grid(row=0, column=1, sticky="w", pady=3)

        ttk.Label(opts, text="번역 방식").grid(row=1, column=0, sticky="w")
        self.engine_var = tk.StringVar(value=ENGINES[0][0])
        ttk.Combobox(opts, textvariable=self.engine_var, values=[n for n, _ in ENGINES], state="readonly",
                     width=24).grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(opts, text="최대 글자 크기").grid(row=2, column=0, sticky="w")
        self.font_var = tk.IntVar(value=40)
        ttk.Spinbox(opts, from_=16, to=80, textvariable=self.font_var, width=6).grid(row=2, column=1, sticky="w", pady=3)

        self.redo_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="이미 번역한 페이지도 다시 번역", variable=self.redo_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(opts, text="결과는 원본 옆 '이름_한국어' 폴더에 저장됩니다.", foreground="#666").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        run = ttk.Frame(left)
        run.grid(row=4, column=0, sticky="ew")
        run.columnconfigure(0, weight=1)
        self.start_btn = ttk.Button(run, text="▶  번역 시작", style="Big.TButton", command=self.start)
        self.start_btn.grid(row=0, column=0, sticky="ew")
        self.stop_btn = ttk.Button(run, text="중지", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(6, 0), sticky="ns")

        self.progress = ttk.Progressbar(left, mode="determinate")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(10, 2))
        self.status = ttk.Label(left, text="대기 중")
        self.status.grid(row=6, column=0, sticky="w")
        self.open_btn = ttk.Button(left, text="결과 폴더 열기", command=self.open_result, state="disabled")
        self.open_btn.grid(row=7, column=0, sticky="w", pady=(6, 0))

        # ── 오른쪽: 미리보기 + 기록 ──
        ttk.Label(main, text="미리보기 (방금 번역한 페이지)", font=("", 11, "bold")).grid(row=0, column=1, sticky="w")
        self.canvas = tk.Label(main, background="#2b2b2b", text="번역이 시작되면 여기에 결과가 보입니다",
                               foreground="#bbb")
        self.canvas.grid(row=1, column=1, sticky="nsew", pady=6)
        self.logbox = tk.Text(main, height=9, wrap="word", state="disabled", font=("", 9))
        self.logbox.grid(row=2, column=1, sticky="nsew")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.pump)

    # ── 입력 목록 ──
    def add_paths(self, paths):
        for p in paths:
            p = Path(p)
            if p.exists() and p not in self.inputs:
                self.inputs.append(p)
                kind = "폴더" if p.is_dir() else p.suffix.lstrip(".").lower()
                self.listbox.insert("end", f"[{kind}] {p.name}   —   {p.parent}")

    def on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def add_folder(self):
        d = filedialog.askdirectory(title="만화 폴더 선택")
        if d:
            self.add_paths([d])

    def add_files(self):
        fs = filedialog.askopenfilenames(
            title="zip 또는 이미지 선택",
            filetypes=[("만화 파일", "*.zip *.cbz *.jpg *.jpeg *.png *.webp *.bmp"), ("모든 파일", "*.*")])
        self.add_paths(fs)

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            del self.inputs[i]

    def clear(self):
        self.listbox.delete(0, "end")
        self.inputs.clear()

    # ── 실행 ──
    def start(self):
        if not self.inputs:
            messagebox.showinfo("만화 번역기", "번역할 폴더나 파일을 먼저 추가하세요.")
            return
        self.stop_flag.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.open_btn.config(state="disabled")
        opts = dict(
            lang=dict(LANGS)[self.lang_var.get()],
            engine=dict(ENGINES)[self.engine_var.get()],
            max_font=int(self.font_var.get()),
            redo=self.redo_var.get(),
            inputs=list(self.inputs),
        )
        self.worker = threading.Thread(target=self.work, args=(opts,), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_flag.set()
        self.status.config(text="지금 페이지까지만 하고 멈춥니다...")

    def work(self, o):
        log = lambda m: self.msgs.put(("log", m))
        try:
            gpu = tm.detect_gpu()
            log(f"{'그래픽카드(GPU)' if gpu else 'CPU'} 로 실행합니다.")
            self.msgs.put(("status", "준비 중... (처음엔 AI 모델을 내려받느라 몇 분 걸려요)"))
            font = tm.get_font_path(log=log)
            if o["lang"] not in self.ocr_cache:
                self.ocr_cache[o["lang"]] = tm.Ocr(o["lang"], gpu, log=log)
            ocr = self.ocr_cache[o["lang"]]
            translator = tm.Translator(o["engine"], o["lang"], "qwen2.5:7b", "http://localhost:11434", log=log)
            for n, src in enumerate(o["inputs"], 1):
                if self.stop_flag.is_set():
                    break
                label = f"({n}/{len(o['inputs'])}) {src.name}"

                def on_page(i, total, img, label=label):
                    self.msgs.put(("progress", (i, total, label)))
                    if img is not None:
                        self.msgs.put(("preview", img))

                out = tm.default_output(src)
                self.last_out = out
                log(f"── {src.name} 시작")
                tm.run_job(src, out, ocr, translator, font, o["max_font"], o["redo"],
                           log=log, on_page=on_page, should_stop=self.stop_flag.is_set)
            self.msgs.put(("done", "중지됨" if self.stop_flag.is_set() else "모두 완료!"))
        except Exception as e:
            log(traceback.format_exc())
            self.msgs.put(("error", str(e)))

    # ── 작업 스레드 → 화면 ──
    def pump(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "log":
                    self.logbox.config(state="normal")
                    self.logbox.insert("end", val + "\n")
                    self.logbox.see("end")
                    self.logbox.config(state="disabled")
                elif kind == "status":
                    self.status.config(text=val)
                elif kind == "progress":
                    i, total, label = val
                    self.progress.config(maximum=total, value=i)
                    self.status.config(text=f"{label} — {i}/{total} 페이지")
                elif kind == "preview":
                    self.show_preview(val)
                elif kind in ("done", "error"):
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    if self.last_out and Path(self.last_out).exists():
                        self.open_btn.config(state="normal")
                    if kind == "done":
                        self.status.config(text=val)
                        if val == "모두 완료!":
                            messagebox.showinfo("만화 번역기", "번역이 끝났습니다!")
                    else:
                        self.status.config(text="오류 발생 — 아래 기록을 확인하세요")
                        messagebox.showerror("만화 번역기", f"오류가 발생했습니다:\n{val}")
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def show_preview(self, img):
        w = max(200, self.canvas.winfo_width() - 8)
        h = max(200, self.canvas.winfo_height() - 8)
        im = img.copy()
        im.thumbnail((w, h), Image.LANCZOS)
        self.preview_img = ImageTk.PhotoImage(im)
        self.canvas.config(image=self.preview_img, text="")

    def open_result(self):
        if self.last_out:
            open_path(self.last_out)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("만화 번역기", "번역 중입니다. 정말 닫을까요?"):
                return
        self.root.destroy()


def main():
    if len(sys.argv) > 1:          # 인자가 있으면 명령줄 모드
        tm.main(sys.argv[1:])
        return
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
