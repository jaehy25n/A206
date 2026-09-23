"""콘솔 출력이 한국어 Windows(cp949)에서 죽지 않는지 검사한다.

이 테스트가 있는 이유: 촬영을 25장 다 끝내고 **결과를 출력하는 마지막 줄에서**
UnicodeEncodeError 로 죽는 일이 실제로 있었다 (em dash U+2014). 계산은 끝났는데
값을 못 보고, 종료 코드도 1 이 되어 성공/실패 판정까지 뒤집힌다.

두 겹으로 막는다.
    1. src/ 소스 전체가 cp949 로 인코딩 가능한지 (여기)
    2. 그래도 뚫리면 setup_console() 의 errors="replace" 가 받는다
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from camcal.console import setup_console

SRC = Path(__file__).resolve().parent.parent / "src"

#: 한국어 Windows 콘솔의 기본 코드페이지.
CONSOLE_ENCODING = "cp949"


def source_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_source_files_found() -> None:
    """경로가 틀려서 0개를 검사하고 통과하는 일이 없게."""
    assert len(source_files()) >= 5


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_source_is_console_encodable(path: Path) -> None:
    """소스에 cp949 가 표현하지 못하는 문자가 없어야 한다.

    주석과 docstring 까지 포함해 검사한다. docstring 은 argparse 의 --help 로
    그대로 콘솔에 나가고, 주석은 언제든 출력 문자열로 옮겨 붙는다.
    """
    text = path.read_text(encoding="utf-8")
    bad: dict[str, int] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        for ch in line:
            try:
                ch.encode(CONSOLE_ENCODING)
            except UnicodeEncodeError:
                bad.setdefault(f"U+{ord(ch):04X} (line {line_no})", ord(ch))
    assert not bad, (
        f"{path.relative_to(SRC.parent)} 에 cp949 로 출력할 수 없는 문자: "
        f"{sorted(bad)}. ASCII 로 바꾼다 (em dash -> '-', almost-equal -> '~=')"
    )


def test_setup_console_survives_unencodable_output(monkeypatch) -> None:
    """2번째 겹: 그래도 기호가 들어오면 죽지 않고 대체 문자로 넘어간다."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding=CONSOLE_ENCODING)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)

    with pytest.raises(UnicodeEncodeError):
        stream.write("em dash — here")
        stream.flush()

    setup_console()
    stream.write("em dash — here")  # 이제는 죽지 않는다
    stream.flush()


def test_cli_help_runs_under_cp949() -> None:
    """--help 가 실제 하위 프로세스에서 cp949 콘솔로 나가도 죽지 않는지.

    argparse 는 모듈 docstring 을 그대로 출력한다. 위 정적 검사가 놓친 경로가
    있어도 여기서 잡힌다.
    """
    for script in ("preflight_jitter.py", "path_check.py", "capture_luaz.py"):
        proc = subprocess.run(
            [sys.executable, str(SRC / script), "--help"],
            capture_output=True,
            env={**__import__("os").environ, "PYTHONIOENCODING": CONSOLE_ENCODING},
        )
        assert proc.returncode == 0, (
            f"{script} --help 가 cp949 에서 실패했다:\n"
            f"{proc.stderr.decode(CONSOLE_ENCODING, errors='replace')}"
        )
