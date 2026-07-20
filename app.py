"""Gradio face-swap app. Run: `python app.py` (or double-click run.bat on Windows)."""

from __future__ import annotations

from pathlib import Path

import cv2
import gradio as gr

from faceswap.pipeline import FaceSwapPipeline

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "inswapper_128.onnx"

_pipeline: FaceSwapPipeline | None = None


def _get_pipeline() -> FaceSwapPipeline:
    global _pipeline
    if _pipeline is None:
        if not DEFAULT_MODEL_PATH.exists():
            raise gr.Error(
                f"모델 파일이 없습니다: {DEFAULT_MODEL_PATH}\n"
                "setup.bat 을 다시 실행하거나 `python download_models.py` 를 실행하세요."
            )
        _pipeline = FaceSwapPipeline(swap_model_path=DEFAULT_MODEL_PATH)
    return _pipeline


def swap(source_path: str | None, target_path: str | None, replace_all: bool, progress=gr.Progress()):
    if not source_path:
        raise gr.Error("소스 사진을 먼저 업로드하세요 (얼굴 가져올 사진).")
    if not target_path:
        raise gr.Error("타깃 사진을 먼저 업로드하세요 (얼굴 바꿀 사진).")

    progress(0.05, desc="모델 준비 중...")
    pipe = _get_pipeline()

    src_img = cv2.imread(source_path, cv2.IMREAD_COLOR)
    tgt_img = cv2.imread(target_path, cv2.IMREAD_COLOR)
    if src_img is None:
        raise gr.Error("소스 사진을 열 수 없어요.")
    if tgt_img is None:
        raise gr.Error("타깃 사진을 열 수 없어요.")

    progress(0.2, desc="얼굴 검출 중...")
    src_faces = pipe.detector.detect(src_img)
    tgt_faces = pipe.detector.detect(tgt_img)
    if not src_faces:
        raise gr.Error("소스 사진에서 얼굴을 찾지 못했어요. 더 정면·고해상도 사진으로 시도해보세요.")
    if not tgt_faces:
        raise gr.Error("타깃 사진에서 얼굴을 찾지 못했어요.")

    src_face = pipe.detector.select(src_faces, "largest")
    to_replace = tgt_faces if replace_all else [pipe.detector.select(tgt_faces, "largest")]

    result = tgt_img.copy()
    total = len(to_replace)
    for i, tf in enumerate(to_replace, 1):
        progress(0.3 + 0.65 * (i / total), desc=f"스왑 중 ({i}/{total})...")
        result = pipe.swapper.swap(result, tf, src_face)

    progress(1.0, desc="완료")
    return cv2.cvtColor(result, cv2.COLOR_BGR2RGB)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="FaceSwap", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# FaceSwap\n"
            "**소스** = 얼굴 가져올 사진, **타깃** = 몸/배경 사진. 두 장 올리고 아래 **스왑 실행**.\n\n"
            "결과 이미지 오른쪽 위의 다운로드 아이콘으로 저장할 수 있어요."
        )
        with gr.Row():
            source_in = gr.Image(label="소스 (얼굴 가져올 사진)", type="filepath", height=350)
            target_in = gr.Image(label="타깃 (얼굴 바꿀 사진)", type="filepath", height=350)
        with gr.Row():
            replace_all = gr.Checkbox(
                label="타깃의 모든 얼굴 교체 (기본: 가장 큰 얼굴 하나만)",
                value=False,
            )
        swap_btn = gr.Button("스왑 실행", variant="primary", size="lg")
        output_img = gr.Image(label="결과", height=450, format="jpeg")

        swap_btn.click(
            fn=swap,
            inputs=[source_in, target_in, replace_all],
            outputs=output_img,
        )

        gr.Markdown(
            "---\n"
            "**주의**: 등장하는 사람의 동의를 받은 사진에만 사용하세요. "
            "실제 인물을 사칭하거나, 성적 콘텐츠 제작, 기만적 자료 제작에 사용하는 것은 "
            "한국을 포함한 여러 국가에서 형사처벌 대상입니다."
        )
    return demo


if __name__ == "__main__":
    build_ui().launch(inbrowser=True, server_name="127.0.0.1", server_port=7860, show_api=False)
