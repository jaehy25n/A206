"""S10 원격 촬영 서버 실행 진입점.

    python src/run_s10_server.py --port 8443

`src/s10_server/app.py` 를 직접 실행하면 `src/` 가 sys.path 에 들어가지 않아
`camcal` 을 찾지 못한다 (Python 은 **스크립트가 있는 디렉토리**를 경로에 넣는다).
이 파일은 `src/` 바로 아래에 있으므로 그것만으로 해결된다.

옵션과 동작 설명은 `s10_server/app.py` 의 docstring 을 본다.
"""

from __future__ import annotations

from s10_server.app import main

if __name__ == "__main__":
    raise SystemExit(main())
