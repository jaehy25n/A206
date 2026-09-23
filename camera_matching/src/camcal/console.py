"""Windows 콘솔 출력 안전장치.

한국어 Windows 의 콘솔 기본 인코딩은 **cp949** 다. 한글은 들어가지만 em dash(U+2014)
나 almost-equal(U+2248) 같은 기호는 cp949 에 없어서 `print` 가
`UnicodeEncodeError` 로 죽는다.
(이 파일 자체도 그 문자를 쓰지 않는다 - tests/test_console.py 가 src/ 전체를 검사한다)

실제로 겪은 방식이 나쁘다: 촬영이나 분석을 다 끝내고 **결과를 출력하는 마지막
줄에서** 죽는다. 계산은 끝났는데 값을 못 본다.

그래서 두 가지를 같이 한다.
    1. 출력 스트림의 인코딩 에러 정책을 `replace` 로 바꾼다 (기호가 `?` 로 나올
       뿐, 프로그램은 살아 있다)
    2. 애초에 콘솔로 나가는 문자열에는 cp949 에 있는 문자만 쓴다
       (`tests/test_console.py` 가 src/ 전체를 검사한다)

1번만 있으면 값이 깨져 보이고, 2번만 있으면 다음에 누가 기호를 하나 넣는 순간
같은 일이 다시 난다.
"""

from __future__ import annotations

import sys


def setup_console() -> None:
    """stdout / stderr 이 인코딩 불가 문자로 죽지 않게 한다.

    모든 CLI 진입점(main)의 첫 줄에서 부른다. 호출해도 정상 출력은 달라지지 않는다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # 파이프로 감싸인 스트림 등
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):  # pragma: no cover - 드문 스트림 구현
            pass
