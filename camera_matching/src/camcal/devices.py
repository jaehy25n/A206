"""Windows 카메라 장치 목록 - "지금 연 것이 정말 그 카메라인가".

OpenCV 는 카메라를 **index 로만** 열 수 있고 어느 장치인지 알려주지 않는다.
그래서 index 0 이 열렸다는 사실만으로 "LUAZ 다" 라고 말할 수 없다.

2026-09-21 에 실제로 이 일이 있었다. LUAZ 를 꽂지 않은 상태에서 서버가 index 0
(노트북 내장 카메라)을 열고 **"LUAZ 연결됨"** 이라고 표시했다. 거기에 LUAZ 의 K 를
씌워 화면에 띄웠으니, 화각이 맞을 리가 없는데 화면에는 아무 경고도 없었다.

여기서 하는 일은 하나다: 기대한 장치 이름이 **실제로 연결돼 있는지** 확인한다.
확인할 수 없으면 (Windows 가 아니거나 조회가 실패하면) 모른다고 말한다.
"모른다"와 "연결됐다"를 섞지 않는다.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

#: PowerShell 조회 제한 시간 (초). 장치가 많아도 1초면 끝난다.
QUERY_TIMEOUT_SEC = 8


@dataclass(frozen=True)
class CameraDevice:
    name: str
    status: str

    @property
    def present(self) -> bool:
        """Status 가 OK 여야 실제로 꽂혀 있는 것이다.

        빼 놓은 장치도 목록에는 남는데 Status 가 `Unknown` 으로 나온다.
        이름만 보고 판단하면 안 되는 이유다.
        """
        return self.status.upper() == "OK"


def list_cameras() -> list[CameraDevice] | None:
    """연결된 카메라 목록. 조회할 수 없으면 **None** (빈 목록이 아니다).

    빈 목록은 "카메라가 없다", None 은 "알 수 없다" 이다. 이 둘을 섞으면
    Windows 가 아닌 곳에서 "카메라 없음" 경고가 잘못 뜬다.
    """
    command = (
        "Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue | "
        "Select-Object Status,FriendlyName | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            timeout=QUERY_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):  # 장치가 하나면 dict 로 온다
        data = [data]
    out: list[CameraDevice] = []
    for item in data:
        name = str(item.get("FriendlyName") or "").strip()
        if name:
            out.append(CameraDevice(name=name, status=str(item.get("Status") or "")))
    return out


def check_expected(pnp_name: str | None) -> tuple[bool | None, str]:
    """기대한 카메라가 연결돼 있는가.

    Returns:
        (판정, 설명). 판정은 True / False / **None(알 수 없음)**.
        None 은 조회 실패나 pnp_name 미설정이다 - 그 경우 막지 않되 확인도 하지 않는다.
    """
    if not pnp_name:
        return (None, "cameras.yaml 에 pnp_name 이 없어 장치를 확인하지 않았다")

    devices = list_cameras()
    if devices is None:
        return (None, "장치 목록을 조회하지 못해 확인하지 않았다 (Windows 가 아닐 수 있다)")

    present = [d for d in devices if d.present]
    matched = [d for d in present if pnp_name.lower() in d.name.lower()]
    listing = ", ".join(f"{d.name}({d.status})" for d in devices) or "없음"

    if matched:
        return (True, f"'{pnp_name}' 연결 확인. 장치: {listing}")
    return (
        False,
        f"**'{pnp_name}' 가 연결돼 있지 않다.** 지금 열리는 카메라는 다른 장치다. "
        f"장치: {listing}",
    )
