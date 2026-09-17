# 앱 모듈 작업 지침

`:app`의 Kotlin·Compose 코드와 리소스에 적용된다. 저장소 전체 규칙은 루트 [AGENTS.md](../AGENTS.md)에 있다.

## 코드 규칙

- Composable과 클래스는 `PascalCase`, 함수·프로퍼티·파라미터는 `camelCase`를 사용한다.
- 사용자에게 보이는 문자열은 `res/values/strings.xml`에 두며, Composable에 하드코딩하지 않는다.
- 부모가 소유하는 Compose 상태는 hoisting하고, Composable은 렌더링과 사용자 이벤트 처리로 한정한다.

## `CaptureScreen`의 예외

`MainActivity.kt`의 `CaptureScreen`은 위 세 번째 규칙을 절반만 지킨다. 새로 만드는 화면의 기준으로 삼지 않는다.

**상태 hoisting은 지켜진다.** `CaptureScreen`이 상태를 소유하고, 자식 Composable은 값과 콜백만 받는다. 자식 쪽에 자체 상태가 없다.

**"렌더링과 사용자 이벤트 처리로 한정"은 지켜지지 않는다.** `CaptureScreen`은 Room 데이터베이스와 `SessionRepository`, `OkHttpClient`·`SessionUploadService`를 직접 만들고 `repository.save`를 직접 호출한다.

### composition에 묶여 있어 올릴 수 없는 것

수집 파이프라인의 상당 부분은 실제로 composition과 Activity에 묶여 있다. 함께 올리면 수명주기를 직접 관리해야 하므로 오히려 위험해진다.

- `previewSurface`·`previewTexture`는 `AndroidView` 안 `TextureView`의 리스너에서 만들어져 수명이 View에 묶인다. ViewModel이 들고 있으면 backing View가 사라진 뒤의 null·release를 직접 처리해야 한다.
- 카메라 권한·프리뷰 권한·SAF 선택의 `rememberLauncherForActivityResult`는 composition에서만 만들 수 있다.
- ARCore `requestInstall`과 수집 화면의 방향 고정은 Activity를 필요로 한다.
- `CapturePreviewController`의 preflight가 `previewSurface`를 클로저로 잡는다.

### 데이터·업로드 계층을 그대로 두는 이유

이쪽은 위 이유에 해당하지 않는다. Room도 OkHttp도 Activity와 무관하며, 여기에 있는 것은 누적된 결과다.

다만 현재 동작에 결함은 없다. `CaptureScreen`은 `setContent`의 뿌리이고 Activity와 수명이 같아 인스턴스가 하나만 생긴다. Room 데이터베이스와 `OkHttpClient`를 단일 인스턴스로 쓰는 것은 두 라이브러리의 권장 사용법과 어긋나지 않는다.

분리하려면 카메라·ARCore·업로드를 포함한 수집 흐름 전체를 실기기에서 다시 검증해야 한다. 고쳐서 얻는 것보다 위험이 커서 하지 않는다 (2026-09-17 사용자 결정).

### 다시 검토해야 하는 조건

`CaptureScreen`이 `setContent`의 뿌리에서 벗어나 composition을 떠났다 돌아올 수 있게 되면 — 예를 들어 `NavHost`의 목적지 안으로 들어가면 — `remember`로 만든 Room 데이터베이스와 `OkHttpClient` 인스턴스가 여러 개 생긴다. 앞의 것을 닫는 경로가 없으므로 SQLite 연결과 소켓이 누적된다.

그 변경을 하게 되면 데이터·업로드 계층 분리는 선택이 아니다. 먼저 분리하고 나서 화면을 옮긴다.
