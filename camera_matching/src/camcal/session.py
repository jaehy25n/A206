"""촬영 세션 - 디렉토리 구조와 meta.json.

    data/<camera>/<session_id>/
        frames/000.png, 001.png, ...
        meta.json

session_id = YYYYMMDD_HHMMSS_<camera>  (예: 20260918_143012_luaz)

meta.json 은 "이 사진들이 어떤 조건에서 찍혔는가"의 유일한 기록이다.
조건을 모르는 사진은 캘리브레이션에 쓸 수 없으므로, 프레임을 추가할 때마다
즉시 디스크에 다시 쓴다 (촬영 중 크래시로 세션 전체를 잃지 않게).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .board import BoardSpec
from .constants import (
    FRAME_FILENAME_FORMAT,
    META_FILENAME,
    META_REPLACE_DELAY_SEC,
    META_REPLACE_RETRIES,
    META_SCHEMA_VERSION,
    PNG_WRITE_PARAMS,
)

#: 카메라 이름은 경로 한 조각이 된다. 경로 조작과 OS 별 금지문자를 막는다.
_CAMERA_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")


def make_session_id(camera: str, when: datetime | None = None) -> str:
    """YYYYMMDD_HHMMSS_<camera>.

    초 단위이므로 같은 카메라로 1초 안에 두 번 만들면 충돌한다.
    충돌은 Session.create 에서 FileExistsError 로 드러난다 (덮어쓰지 않는다).
    """
    when = when or datetime.now()
    return f"{when:%Y%m%d_%H%M%S}_{camera}"


def _validate_camera(camera: str) -> str:
    if not _CAMERA_NAME_RE.match(camera):
        raise ValueError(
            f"카메라 이름은 소문자/숫자/_/- 만 쓴다 (경로 한 조각이 된다): {camera!r}"
        )
    return camera


@dataclass
class FrameRecord:
    """프레임 한 장의 기록.

    코너 좌표 자체는 넣지 않는다 - PNG 무손실이라 같은 검출기를 돌리면 같은
    결과가 나오고, meta.json 은 사람이 읽을 수 있는 크기로 둔다.
    """

    index: int
    filename: str
    detected: bool
    n_corners: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FrameRecord":
        return cls(
            index=int(data["index"]),
            filename=str(data["filename"]),
            detected=bool(data["detected"]),
            n_corners=int(data["n_corners"]),
            timestamp=str(data["timestamp"]),
        )


@dataclass
class Session:
    """한 카메라의 촬영 한 판.

    직접 생성하지 말고 `Session.create()` 또는 `Session.open()` 을 쓴다.
    """

    path: Path
    camera: str
    session_id: str
    board: BoardSpec
    resolution_requested: tuple[int, int]
    resolution_actual: tuple[int, int]
    created_at: str
    capture_settings: dict[str, Any] = field(default_factory=dict)
    frames: list[FrameRecord] = field(default_factory=list)
    coverage: dict[str, Any] | None = None
    schema_version: int = META_SCHEMA_VERSION

    # --- 경로 -------------------------------------------------------------

    @property
    def frames_dir(self) -> Path:
        return self.path / "frames"

    @property
    def meta_path(self) -> Path:
        return self.path / META_FILENAME

    # --- 생성 / 열기 ------------------------------------------------------

    @classmethod
    def create(
        cls,
        data_root: str | Path,
        camera: str,
        board: BoardSpec,
        resolution_requested: tuple[int, int],
        resolution_actual: tuple[int, int],
        capture_settings: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> "Session":
        """새 세션 디렉토리를 만든다. 이미 있으면 예외 (덮어쓰지 않는다).

        Args:
            data_root: `data/` 경로.
            camera: "luaz" / "s10" 같은 소문자 이름.
            board: 이 세션에서 쓴 보드 규격. 그대로 meta.json 에 복사된다.
            resolution_requested: 카메라에 **요청한** (width, height).
            resolution_actual: 첫 프레임에서 **실제로 나온** (width, height).
            capture_settings: 카메라에서 읽어낸 실제 설정 (카메라별 자유 dict).
            session_id: 지정하지 않으면 YYYYMMDD_HHMMSS_<camera>.
        """
        camera = _validate_camera(camera)
        now = datetime.now()
        session_id = session_id or make_session_id(camera, now)
        path = Path(data_root) / camera / session_id
        if path.exists():
            raise FileExistsError(f"세션이 이미 있다: {path}")

        session = cls(
            path=path,
            camera=camera,
            session_id=session_id,
            board=board,
            resolution_requested=(
                int(resolution_requested[0]),
                int(resolution_requested[1]),
            ),
            resolution_actual=(
                int(resolution_actual[0]),
                int(resolution_actual[1]),
            ),
            created_at=now.astimezone().isoformat(timespec="seconds"),
            capture_settings=dict(capture_settings or {}),
        )
        session.frames_dir.mkdir(parents=True, exist_ok=False)
        session.save()
        return session

    @classmethod
    def open(cls, session_path: str | Path) -> "Session":
        """기존 세션 디렉토리를 읽는다."""
        path = Path(session_path)
        meta_path = path / META_FILENAME
        if not meta_path.exists():
            raise FileNotFoundError(f"meta.json 이 없다: {meta_path}")
        with meta_path.open("r", encoding="utf-8") as fp:
            meta = json.load(fp)

        version = int(meta.get("schema_version", 0))
        if version != META_SCHEMA_VERSION:
            raise ValueError(
                f"meta.json 스키마 버전이 다르다: {version} != {META_SCHEMA_VERSION} "
                f"({meta_path}). 다른 버전의 도구가 만든 세션이다"
            )

        resolution_requested = meta["resolution_requested"]
        resolution_actual = meta["resolution_actual"]
        return cls(
            path=path,
            camera=str(meta["camera"]),
            session_id=str(meta["session_id"]),
            board=BoardSpec.from_dict(meta["board"]),
            resolution_requested=(
                int(resolution_requested[0]),
                int(resolution_requested[1]),
            ),
            resolution_actual=(
                int(resolution_actual[0]),
                int(resolution_actual[1]),
            ),
            created_at=str(meta["created_at"]),
            capture_settings=dict(meta.get("capture_settings") or {}),
            frames=[FrameRecord.from_dict(f) for f in meta.get("frames", [])],
            coverage=meta.get("coverage"),
            schema_version=version,
        )

    # --- 프레임 추가 ------------------------------------------------------

    def add_frame(
        self,
        image: np.ndarray,
        detected: bool,
        n_corners: int,
    ) -> FrameRecord:
        """프레임 한 장을 PNG 무손실로 저장하고 meta.json 을 갱신한다.

        detected=False 인 프레임도 저장할 수는 있지만 캘리브레이션에 쓰이지
        않는다. 촬영 도구는 검출 성공 프레임만 저장한다.

        저장할 이미지 크기가 resolution_actual 과 다르면 예외 - 세션 도중에
        카메라가 해상도를 바꾼 것이고, 그런 프레임을 섞으면 K 가 무의미해진다.
        """
        height, width = image.shape[:2]
        if (width, height) != self.resolution_actual:
            raise ValueError(
                f"프레임 해상도가 세션과 다르다: {(width, height)} != {self.resolution_actual}"
            )

        index = len(self.frames)
        filename = FRAME_FILENAME_FORMAT.format(index=index)
        out_path = self.frames_dir / filename
        if out_path.exists():
            raise FileExistsError(f"프레임 파일이 이미 있다: {out_path}")

        ok = cv2.imwrite(str(out_path), image, PNG_WRITE_PARAMS)
        if not ok:
            raise IOError(f"PNG 저장 실패: {out_path}")

        record = FrameRecord(
            index=index,
            filename=filename,
            detected=bool(detected),
            n_corners=int(n_corners),
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self.frames.append(record)
        self.save()
        return record

    def frame_path(self, record: FrameRecord) -> Path:
        return self.frames_dir / record.filename

    @property
    def n_detected(self) -> int:
        return sum(1 for f in self.frames if f.detected)

    # --- 저장 -------------------------------------------------------------

    def set_capture_settings(self, settings: dict[str, Any]) -> None:
        """카메라에서 실제로 읽어낸 설정을 기록한다."""
        self.capture_settings = dict(settings)
        self.save()

    def set_coverage(self, coverage: dict[str, Any]) -> None:
        """Coverage.to_dict() 결과를 세션에 남긴다."""
        self.coverage = dict(coverage)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "camera": self.camera,
            "created_at": self.created_at,
            "resolution_requested": list(self.resolution_requested),
            "resolution_actual": list(self.resolution_actual),
            "board": self.board.to_dict(),
            "capture_settings": self.capture_settings,
            "coverage": self.coverage,
            "n_frames": len(self.frames),
            "n_detected": self.n_detected,
            "frames": [f.to_dict() for f in self.frames],
        }

    def save(self) -> None:
        """meta.json 을 원자적으로 쓴다 (임시파일 -> os.replace).

        중간에 죽어도 반쪽짜리 JSON 이 남지 않는다.

        Windows 에서 os.replace 는 대상 파일을 다른 프로세스가 열고 있으면
        PermissionError 를 낸다 (백신, 검색 인덱서가 방금 쓴 파일을 훑는 경우).
        촬영 중에는 프레임마다 이 함수를 부르므로 그 일시적 잠금 한 번으로
        세션이 죽으면 안 된다. 짧게 여러 번 재시도하고, 그래도 안 되면
        **조용히 넘기지 않고** 예외를 올린다.
        """
        self.path.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_path.with_name(META_FILENAME + ".tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())

        last: OSError | None = None
        for attempt in range(META_REPLACE_RETRIES):
            try:
                os.replace(tmp, self.meta_path)
                return
            except PermissionError as exc:  # Windows 전용 증상
                last = exc
                time.sleep(META_REPLACE_DELAY_SEC * (attempt + 1))
        raise IOError(
            f"meta.json 을 {META_REPLACE_RETRIES}회 시도했지만 바꿔치기하지 못했다: "
            f"{self.meta_path}. 다른 프로그램이 파일을 잡고 있다 "
            f"(마지막 오류: {last})"
        ) from last

    def close(self) -> None:
        """종료 시 최종 저장."""
        self.save()
