"""장면을 '읽는' 부분. 지금은 이미지 숫자만으로 계산하는 NumericAnalyzer 하나뿐이다.

나중에 AI(예: Gemini)를 붙이려면:
    1. SceneAnalyzer 를 상속한 클래스를 만들고 analyze() 를 채운다.
    2. 아래 ANALYZERS 에 이름을 등록한다.
    3. python scripts/scenes.py --analyzer 그이름  으로 실행한다.
analyze() 는 같은 모양의 dict 를 돌려주기만 하면 되므로 scenes.py 는 고칠 필요가 없다.
"""
import cv2
import numpy as np


class SceneAnalyzer:
    """모든 분석기가 따르는 약속(인터페이스)."""

    name = "base"

    def analyze(self, scene):
        """scene: {"idx", "start", "end", "duration", "photos": [사진 경로...], "samples": [BGR 프레임...]}

        돌려줄 것: {"shot_type": str, "description": str,
                    "features": {"sharpness", "brightness", "saturation", "warmth", "motion"},
                    "excluded": bool, "exclude_reason": str}
        """
        raise NotImplementedError


class NumericAnalyzer(SceneAnalyzer):
    """AI 없이 픽셀 숫자로만 계산한다. 설명(description)은 비워 둔다."""

    name = "numeric"

    # 제외 기준 (필요하면 숫자만 바꾸면 됨)
    MIN_DURATION = 0.5   # 초. 이보다 짧은 장면은 제외
    MIN_BRIGHTNESS = 25  # 0~255. 이보다 어두우면 제외
    MIN_SHARPNESS = 15   # 이보다 흐리면 제외

    def analyze(self, scene):
        frames = scene["samples"]
        small = [_resize(f, 320) for f in frames]
        grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in small]
        hsvs = [cv2.cvtColor(f, cv2.COLOR_BGR2HSV) for f in small]

        sharpness = float(np.mean([cv2.Laplacian(g, cv2.CV_64F).var() for g in grays]))
        brightness = float(np.mean([h[:, :, 2].mean() for h in hsvs]))
        saturation = float(np.mean([h[:, :, 1].mean() for h in hsvs]))
        # 따뜻함: 빨강 평균 - 파랑 평균 (+면 따뜻한 색, -면 차가운 색)
        warmth = float(np.mean([f[:, :, 2].mean() - f[:, :, 0].mean() for f in small]))
        # 움직임: 바로 옆 프레임끼리 픽셀이 얼마나 바뀌었나 (0~255)
        pairs = scene.get("motion_pairs", [])
        motion = float(np.mean([cv2.absdiff(_gray_small(a), _gray_small(b)).mean()
                                for a, b in pairs])) if pairs else 0.0

        if motion < 2:
            shot_type = "고정"
        elif motion < 12:
            shot_type = "움직임"
        else:
            shot_type = "빠른 움직임"

        reasons = []
        if scene["duration"] < self.MIN_DURATION:
            reasons.append("너무 짧음")
        if brightness < self.MIN_BRIGHTNESS:
            reasons.append("너무 어두움")
        if sharpness < self.MIN_SHARPNESS:
            reasons.append("흐림")

        return {
            "shot_type": shot_type,
            "description": "",
            "features": {
                "sharpness": round(sharpness, 1),
                "brightness": round(brightness, 1),
                "saturation": round(saturation, 1),
                "warmth": round(warmth, 1),
                "motion": round(motion, 2),
            },
            "excluded": bool(reasons),
            "exclude_reason": ", ".join(reasons),
        }


def _resize(frame, width):
    h, w = frame.shape[:2]
    return cv2.resize(frame, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)


def _gray_small(frame):
    return cv2.cvtColor(_resize(frame, 160), cv2.COLOR_BGR2GRAY)


ANALYZERS = {
    NumericAnalyzer.name: NumericAnalyzer,
    # "gemini": GeminiAnalyzer,   ← 나중에 AI 분석기를 여기에 등록
}
