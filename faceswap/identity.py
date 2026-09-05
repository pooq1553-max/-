"""여러 장의 인물 사진에서 하나의 안정적인 얼굴 정체성(identity)을 만든다.

사진 한 장의 임베딩에는 그 사진 고유의 각도/조명/표정 노이즈가 섞여 있다.
여러 장을 품질 가중 평균하면 그 사람의 정체성 쪽으로 수렴해서, 스왑 결과의
닮음 정도와 각도 변화에 대한 안정성이 올라간다.

주의: 이것은 모델을 재학습하는 것이 아니라 ArcFace 임베딩을 합치는 것이다.
DeepFaceLab 류의 인물별 파인튜닝과는 다르며, 훨씬 가볍고 즉시 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from .detector import DetectedFace, FaceDetector

ProgressCallback = Callable[[float, str], None]


def _imread_unicode(path: str | Path) -> Optional[np.ndarray]:
    try:
        with open(path, "rb") as f:
            data = np.frombuffer(f.read(), np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _frontality(kps: np.ndarray) -> float:
    """5점 랜드마크로 정면도를 0~1로 추정. 정면일수록 1에 가깝다.

    kps 순서: 왼눈, 오른눈, 코, 왼입꼬리, 오른입꼬리
    코가 두 눈 중점에서 좌우로 벗어난 정도를 눈 사이 거리로 정규화한다.
    """
    try:
        left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    except (IndexError, TypeError):
        return 0.5
    eye_dist = float(np.linalg.norm(right_eye - left_eye))
    if eye_dist <= 1e-6:
        return 0.0
    eye_mid_x = (left_eye[0] + right_eye[0]) / 2.0
    offset = abs(float(nose[0]) - eye_mid_x) / eye_dist
    return float(np.clip(1.0 - offset * 2.0, 0.0, 1.0))


class AveragedFace:
    """평균 임베딩을 담는 소스 얼굴 대체 객체.

    inswapper는 소스 얼굴에서 normed_embedding 하나만 읽는다. insightface의
    Face(dict 서브클래스)를 복사하면 버전마다 다른 내부 구현에 얽히고, 없는
    속성이 None으로 조용히 반환되는 성질 때문에 문제를 늦게 발견하게 된다.
    필요한 것만 직접 들고 있는 객체를 쓰는 편이 안전하다.
    """

    def __init__(self, embedding, kps=None, bbox=None, det_score: float = 1.0,
                 gender: int = -1, age=None):
        self.embedding = np.asarray(embedding, dtype=np.float32)
        self.kps = kps
        self.bbox = bbox
        self.det_score = det_score
        self.gender = gender
        self.age = age

    @property
    def embedding_norm(self) -> float:
        return float(np.linalg.norm(self.embedding))

    @property
    def normed_embedding(self) -> np.ndarray:
        n = self.embedding_norm
        return self.embedding / n if n > 1e-6 else self.embedding

    @property
    def sex(self):
        if self.gender == 0:
            return "F"
        if self.gender == 1:
            return "M"
        return None


@dataclass
class SourceSample:
    path: str
    face: DetectedFace
    unit_embedding: np.ndarray
    weight: float
    frontality: float
    similarity: float = 0.0


@dataclass
class IdentityReport:
    used: List[str] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)  # (path, 이유)
    similarities: List[Tuple[str, float]] = field(default_factory=list)

    @property
    def used_count(self) -> int:
        return len(self.used)

    def summary_ko(self) -> str:
        parts = [f"소스 {self.used_count}장 사용"]
        if self.skipped:
            parts.append(f"{len(self.skipped)}장 제외")
        if self.similarities:
            sims = [s for _, s in self.similarities]
            parts.append(f"일관성 평균 {float(np.mean(sims)):.2f}")
        return " · ".join(parts)


def build_identity(
    detector: FaceDetector,
    image_paths: List[str | Path],
    min_similarity: float = 0.35,
    progress: Optional[ProgressCallback] = None,
) -> Tuple[DetectedFace, IdentityReport]:
    """여러 사진에서 품질 가중 평균 임베딩을 만들어 소스 얼굴로 반환한다.

    min_similarity 미만으로 평균에서 동떨어진 사진은 다른 사람이거나 검출이
    잘못된 것으로 보고 제외한 뒤 평균을 다시 계산한다.
    """
    paths = [str(p) for p in image_paths]
    if not paths:
        raise ValueError("소스 사진이 없어요.")

    report = IdentityReport()
    samples: List[SourceSample] = []

    for i, path in enumerate(paths, 1):
        if progress:
            progress(i / max(1, len(paths)), f"소스 분석 중 {i}/{len(paths)} · {Path(path).name}")

        img = _imread_unicode(path)
        if img is None:
            report.skipped.append((path, "파일을 열 수 없음"))
            continue

        faces = detector.detect(img)
        if not faces:
            report.skipped.append((path, "얼굴을 찾지 못함"))
            continue

        face = detector.select(faces, "largest")
        emb = face.embedding
        if emb is None or emb.size == 0:
            report.skipped.append((path, "얼굴 특징 추출 실패"))
            continue

        norm = float(np.linalg.norm(emb))
        if norm <= 1e-6:
            report.skipped.append((path, "얼굴 특징이 비어 있음"))
            continue
        unit = (emb / norm).astype(np.float32)

        front = _frontality(face.kps)
        # 정면이고 검출 신뢰도가 높은 사진에 더 큰 비중을 준다.
        weight = float(max(0.05, face.det_score)) * (0.35 + 0.65 * front)
        samples.append(SourceSample(path=path, face=face, unit_embedding=unit,
                                    weight=weight, frontality=front))

    if not samples:
        raise RuntimeError(
            "선택한 사진들에서 쓸 만한 얼굴을 찾지 못했어요.\n"
            "더 정면이고 크게 나온 사진으로 시도해보세요."
        )

    def weighted_mean(items: List[SourceSample]) -> np.ndarray:
        mat = np.stack([s.unit_embedding for s in items])
        w = np.asarray([s.weight for s in items], dtype=np.float32).reshape(-1, 1)
        mean = (mat * w).sum(axis=0) / max(float(w.sum()), 1e-6)
        n = float(np.linalg.norm(mean))
        return (mean / n).astype(np.float32) if n > 1e-6 else mean.astype(np.float32)

    mean_emb = weighted_mean(samples)

    # 평균에서 크게 벗어난 사진 제외 (다른 사람이 섞였거나 검출 오류)
    kept: List[SourceSample] = []
    for s in samples:
        s.similarity = float(np.dot(s.unit_embedding, mean_emb))
        if len(samples) >= 3 and s.similarity < min_similarity:
            report.skipped.append(
                (s.path, f"다른 인물로 판단 (유사도 {s.similarity:.2f})")
            )
        else:
            kept.append(s)

    if not kept:
        kept = samples
        report.skipped = [x for x in report.skipped if "다른 인물로 판단" not in x[1]]

    if len(kept) != len(samples):
        mean_emb = weighted_mean(kept)
        for s in kept:
            s.similarity = float(np.dot(s.unit_embedding, mean_emb))

    report.used = [s.path for s in kept]
    report.similarities = [(s.path, s.similarity) for s in kept]

    # 가장 대표적인(가중치 높은) 얼굴의 위치 정보를 쓰고 임베딩만 평균값으로 바꾼다.
    # inswapper는 source_face.normed_embedding 만 사용하므로 이걸로 충분하다.
    best = max(kept, key=lambda s: s.weight)
    scale = float(np.linalg.norm(best.face.embedding)) or 1.0
    merged_embedding = (mean_emb * scale).astype(np.float32)
    raw = AveragedFace(
        merged_embedding,
        kps=best.face.kps,
        bbox=best.face.bbox,
        det_score=best.face.det_score,
        gender=best.face.gender,
    )

    source_face = DetectedFace(
        bbox=best.face.bbox,
        kps=best.face.kps,
        det_score=best.face.det_score,
        embedding=merged_embedding,
        raw=raw,
        gender=best.face.gender,
    )

    if progress:
        progress(1.0, report.summary_ko())
    return source_face, report
