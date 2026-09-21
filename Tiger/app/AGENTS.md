# 앱 모듈 작업 지침

`:app`의 Kotlin·Compose 코드와 리소스에 적용된다. 저장소 전체 규칙은 루트 [AGENTS.md](../AGENTS.md)에 있다.

## 코드 규칙

- Composable과 클래스는 `PascalCase`, 함수·프로퍼티·파라미터는 `camelCase`를 사용한다.
- ktlint의 `standard:function-naming`은 Composable의 `PascalCase`를 허용하지 않는다. 테스트 소스까지 포함해 Composable 선언에는 `@Suppress("FunctionName")`을 붙인다.
- 사용자에게 보이는 문자열은 `res/values/strings.xml`에 두며, Composable에 하드코딩하지 않는다.
- 부모가 소유하는 Compose 상태는 hoisting하고, Composable은 렌더링과 사용자 이벤트 처리로 한정한다.

## Presentation 계층

수집과 조회는 상태의 성격이 달라 같은 패턴을 쓰지 않는다. 하나로 통일하지 않는다.

### 수집 — MVI

`CaptureWorkspaceControlState`의 다섯 상태가 진실이고, 그것을 만들어 내는 불리언들은 중복 표현이다. `finalizing`·`collecting`·`active`·`trackingReady` 넷이 16가지 조합을 만드는데 합법은 다섯이고, 나머지 열하나는 타입이 아니라 호출 순서로만 막혀 있다.

상태 변경의 출처도 tracking 폴링·권한 콜백·lifecycle 이벤트·ARCore 실패로 흩어져 있고 서로 경합한다. 입구를 하나로 두어 순서를 한곳에서 정한다.

- 상태는 `CaptureUiState` 하나로 모은다.
- 변경은 `CaptureIntent`를 통해서만 한다.
- 화면 이동·Snackbar 같은 일회성 동작은 effect로 내보낸다. 수집 쪽이 `NavController`를 알지 않는다.
- `CaptureSessionCoordinator`는 이미 상태 기계이고 `CaptureControlPolicy`는 이미 순수 파생 함수다. 새로 만들지 말고 그것을 쓴다.

### 조회 — 상태 보유자만

Room Flow에서 목록이 나오고 화면은 값과 콜백만 받는다. 상태 기계가 없으므로 intent와 reducer를 두지 않는다. 내보내기·전송·삭제 세 동작과 그 결과 문구를 드는 얇은 보유자면 된다.

### `ViewModel`을 쓰지 않는다

`androidx.lifecycle.ViewModel`이 주는 것이 이 앱에서 맞지 않는다.

- **구성 변경에서 살아남는 것이 여기서는 해가 된다.** 수집 상태는 `ON_STOP`에서 진행 중인 Session을 `INTERRUPTED`로 마감하며 의도적으로 버린다. 살아남으면 이미 마감된 세션의 상태를 들고 돌아온다.
- `viewModelScope`는 `rememberCoroutineScope()`가, `onCleared()`는 `DisposableEffect`가 이미 한다.

상태 보유자는 `remember`로 만드는 평범한 클래스로 둔다. Android 의존이 없어 단위 테스트가 쉽다.

### DI 라이브러리를 쓰지 않는다

프로세스 수명을 갖는 객체가 셋(`TigerDatabase`·`SessionRepository`·`SessionUploadService`), 스코프 하나, 단일 모듈이다. Hilt가 지원하는 Compose 경로는 `hiltViewModel()`인데 `ViewModel`을 쓰지 않으므로 `@EntryPoint` 우회로를 써야 하고, 그 의식이 없애려는 코드보다 길어진다. `Application`의 필드로 둔다.

### 패턴 밖에 두는 것

`previewSurface`·`previewTexture`는 `CaptureUiState`에 넣지 않는다. 수명이 `TextureView`에 묶여 있어 상태로 올리면 backing view가 사라진 뒤의 null·release를 직접 관리해야 한다. composition에 남기고 intent의 인자로 넘긴다. 권한 launcher도 같다. 아래 "composition에 묶여 있어 올릴 수 없는 것"과 같은 목록이다.

### 다시 검토해야 하는 조건

- 수집 상태 열거형이 여덟을 넘으면
- 상태 보유자가 셋을 넘으면
- 수집 상태를 프로세스 재생성 너머로 살려야 하는 요구가 생기면 — 이때는 `ViewModel` 판단부터 다시 한다

앞의 둘은 평소 작업에서 걸린다. 걸렸다는 것은 이 절의 결정이 규모를 감당하지 못하게 됐다는 신호다.

## `CaptureScreen`의 예외

`CaptureScreen.kt`의 `CaptureScreen`은 위 세 번째 규칙을 절반만 지킨다. 새로 만드는 화면의 기준으로 삼지 않는다.

**상태 hoisting은 지켜진다.** `CaptureScreen`이 상태를 소유하고, 자식 Composable은 값과 콜백만 받는다. 자식 쪽에 자체 상태가 없다.

**"렌더링과 사용자 이벤트 처리로 한정"은 지켜지지 않는다.** `CaptureScreen`은 Room 데이터베이스와 `SessionRepository`, `OkHttpClient`·`SessionUploadService`를 직접 만들고 `repository.save`를 직접 호출한다.

### composition에 묶여 있어 올릴 수 없는 것

수집 파이프라인의 상당 부분은 실제로 composition과 Activity에 묶여 있다. 함께 올리면 수명주기를 직접 관리해야 하므로 오히려 위험해진다.

- `previewSurface`·`previewTexture`는 `AndroidView` 안 `TextureView`의 리스너에서 만들어져 수명이 View에 묶인다. ViewModel이 들고 있으면 backing View가 사라진 뒤의 null·release를 직접 처리해야 한다.
- 카메라 권한·프리뷰 권한·SAF 선택의 `rememberLauncherForActivityResult`는 composition에서만 만들 수 있다.
- ARCore `requestInstall`과 수집 화면의 방향 고정은 Activity를 필요로 한다.
- `CapturePreviewController`의 preflight가 `previewSurface`를 클로저로 잡는다.

### 데이터·업로드 계층이 여기 있는 이유

이쪽은 위 이유에 해당하지 않는다. Room도 OkHttp도 Activity와 무관하며, 여기에 있는 것은 누적된 결과다.

2026-09-17에는 "현재 동작에 결함이 없으므로 미룬다"는 판단으로 두었다. **그 전제는 사실이 아니다.**

`MainActivity`의 `configChanges`에 `uiMode`·`locale`·`fontScale`·`density`가 없다. 시스템 다크 모드 전환, 언어 변경, 글꼴 크기 변경은 Activity를 재생성하고, 새 composition에서 `remember`가 다시 돌아 두 번째 Room 인스턴스와 두 번째 `OkHttpClient`가 생긴다. 앞의 것을 닫는 경로가 없다.

크래시는 아니다. Room은 첫 쿼리까지 연결을 열지 않고 OkHttp의 유휴 스레드는 60초면 회수된다. 남는 것은 같은 파일을 보는 연결 풀 둘과 회수되지 않는 Room 인스턴스다. 그래도 "인스턴스가 하나만 생긴다"는 틀렸다.

분리 비용도 과하게 잡혀 있었다. 생성 위치를 올려도 `repository` 인스턴스의 동일성과 수명이 유지되면 카메라와 ARCore의 동작은 바뀌지 않는다. 기기에서 확인할 것은 업로드 경로와 Activity 재생성 경로다.

### 예정된 작업

Room 데이터베이스와 `OkHttpClient` 생성을 `Application`으로 올린다. 위 결함을 없애는 것이 하나이고, 화면을 수집과 조회로 가르면 `repository`를 양쪽이 쓰게 되어 어느 한쪽에 둘 수 없다는 것이 다른 하나다. 화면 분리의 선행조건이다.
