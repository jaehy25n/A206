# 앱 모듈 작업 지침

`:app`의 Kotlin·Compose 코드와 리소스에 적용된다. 저장소 전체 규칙은 루트 [AGENTS.md](../AGENTS.md)에 있다.

## 코드 규칙

- Composable과 클래스는 `PascalCase`, 함수·프로퍼티·파라미터는 `camelCase`를 사용한다.
- ktlint의 `standard:function-naming`은 Composable의 `PascalCase`를 허용하지 않는다. 테스트 소스까지 포함해 Composable 선언에는 `@Suppress("FunctionName")`을 붙인다.
- 사용자에게 보이는 문자열은 `res/values/strings.xml`에 두며, Composable에 하드코딩하지 않는다.
- 부모가 소유하는 Compose 상태는 hoisting하고, Composable은 렌더링과 사용자 이벤트 처리로 한정한다.

## 디자인 시스템

화면에서 크기·굵기·색·표면 색을 직접 고르지 않는다. 정해진 이름 중에서 고른다. 조합을 자리마다 손으로 만들면 축이 하나씩 늘어나고, 그러면 어느 요소도 다른 요소와 스타일을 공유하지 않아 위계가 아니라 잡음으로 읽힌다.

- **글자**: `ui/theme/TigerText.kt`의 역할에서 고른다. 크기 다섯 층(28·22·16·14·12)과 잉크 세 단계가 거기서 정해진다. 새 조합이 필요하면 호출부가 아니라 이 파일에 역할을 더한다.
- **판**: `ui/theme/TigerSurface.kt`. 카드가 얹히는 바닥과 글자가 놓이는 판 둘뿐이다.
- **타입 스케일과 글꼴**: `ui/theme/Type.kt`. Material 3 컴포넌트가 제 안에서 집어 쓰는 눈금이라 여기를 비우면 그 컴포넌트만 앱 밖의 값을 쓴다.
- **공용 컴포넌트**: `ui/common`의 `TigerCard`, `LabelledGroup`, `LabelledValue`, `TigerMenuItem`. 카드와 묶음과 메뉴 항목은 여기를 거친다.

역할은 색을 비워 두지 않는다. 비우면 놓인 자리의 콘텐츠 색을 따라 같은 역할이 자리마다 다르게 렌더된다. 예외는 `menuItem` 하나이고, 그 자리의 색은 스타일이 아니라 상태(되돌릴 수 없음·비활성)가 정하므로 컴포넌트에 맡긴다.

간격은 줄상자를 깎은 뒤에 정한다. Material 3의 타입 스케일은 줄 높이를 글자보다 크게 잡아 그 차이가 상자 여백으로 남고, `spacedBy`는 그 바깥에 더해진다. 역할마다 상자를 깎아 두었으므로 쓴 값이 곧 보이는 값이다.

왜 그렇게 정했는지는 각 파일의 KDoc과 `specs/002-capture-control-ux/contracts/capture-control-ui.md`에 있다. 값을 바꾸기 전에 읽는다.

## Presentation 계층

수집과 조회는 상태의 성격이 달라 같은 패턴을 쓰지 않는다. 하나로 통일하지 않는다.

### 수집 — MVI

`CaptureWorkspaceControlState`의 다섯 상태가 진실이고, 그것을 만들어 내는 불리언들은 중복 표현이다. `finalizing`·`collecting`·`active`·`trackingReady` 넷이 16가지 조합을 만드는데 합법은 다섯이고, 나머지 열하나는 타입이 아니라 호출 순서로만 막혀 있다.

상태 변경의 출처도 tracking 폴링·권한 콜백·lifecycle 이벤트·ARCore 실패로 흩어져 있고 서로 경합한다. 입구를 하나로 두어 순서를 한곳에서 정한다.

- 상태는 `CaptureUiState` 하나로 모은다.
- 변경은 `CaptureIntent`를 통해서만 한다.
- `CaptureSessionCoordinator`는 이미 상태 기계이고 `CaptureControlPolicy`는 이미 순수 파생 함수다. 새로 만들지 말고 그것을 쓴다.

**일회성 동작에 effect 채널을 두지 않는다.** 둘뿐이고 각자 갈 곳이 이미 있다.

- 화면 이동: 수집은 목적지를 모른다. 마감된 세션을 `onCompleted(sessionId, uploadable)`로 올려 보내고 `TigerApp`이 정한다.
- Snackbar: 문구를 `CaptureUiState.notice`에 담고, `LaunchedEffect`가 한 번 보여 준 뒤 `CaptureIntent.NoticeShown`으로 비운다.

셋째가 생기면 그때 채널을 만든다. 지금 만들면 두 줄짜리 배선에 틀만 씌우는 것이 된다.

### 조회 — 상태 보유자만

Room Flow에서 목록이 나오고 화면은 값과 콜백만 받는다. 상태 기계가 없으므로 intent와 reducer를 두지 않는다. 전송·삭제 두 동작과 그 결과 문구를 드는 얇은 보유자면 된다.

### `ViewModel`을 쓰지 않는다

`androidx.lifecycle.ViewModel`이 주는 것이 이 앱에서 맞지 않는다.

- **구성 변경에서 살아남는 것이 여기서는 해가 된다.** 수집 상태는 `ON_STOP`에서 진행 중인 Session을 `INTERRUPTED`로 마감하며 의도적으로 버린다. 살아남으면 이미 마감된 세션의 상태를 들고 돌아온다.
- `viewModelScope`는 `rememberCoroutineScope()`가, `onCleared()`는 `DisposableEffect`가 이미 한다.

상태 보유자는 `remember`로 만드는 평범한 클래스로 둔다. Android 의존이 없어 단위 테스트가 쉽다.

### DI 라이브러리를 쓰지 않는다

프로세스 수명을 갖는 객체가 셋(`TigerDatabase`·`SessionRepository`·`SessionUploadService`), 스코프 하나, 단일 모듈이다. Hilt가 지원하는 Compose 경로는 `hiltViewModel()`인데 `ViewModel`을 쓰지 않으므로 `@EntryPoint` 우회로를 써야 하고, 그 의식이 없애려는 코드보다 길어진다. `Application`의 필드로 둔다.

### 패턴 밖에 두는 것

`previewSurface`·`previewTexture`는 `CaptureUiState`에 넣지 않는다. 수명이 `TextureView`에 묶여 있어 상태로 올리면 backing view가 사라진 뒤의 null·release를 직접 관리해야 한다. `rememberCaptureDriver`가 들고, 화면은 Surface가 생기고 사라졌다는 사실만 알린다. 권한 launcher도 드라이버에 있다. 아래 "composition에 묶여 있어 올릴 수 없는 것"과 같은 목록이다.

### 다시 검토해야 하는 조건

- 수집 상태 열거형이 여덟을 넘으면
- 상태 보유자가 셋을 넘으면
- 수집 상태를 프로세스 재생성 너머로 살려야 하는 요구가 생기면 — 이때는 `ViewModel` 판단부터 다시 한다

앞의 둘은 평소 작업에서 걸린다. 걸렸다는 것은 이 절의 결정이 규모를 감당하지 못하게 됐다는 신호다.

## 수집 화면의 구성

`ui/capture/`는 책임별로 갈라져 있다. 새 화면을 만들 때 참고할 수 있는 배치다.

| | 맡는 것 |
|---|---|
| `CaptureWorkspace` | 그리기만 한다. 카메라도 목적지도 모른다 |
| `CaptureDriver` | 카메라 세션·ARCore·권한·tracking 폴링·마감 |
| `CaptureState` | `CaptureUiState`·`CaptureIntent`·`reduce` |
| `CapturePreviewSurface` | `TextureView`와 `SurfaceTexture`의 수명 |
| `CaptureMetadataDialog` | Task·Object·해상도 입력 |
| `CaptureWorkspaceScreen` | 배지·제어 버튼·오버레이 |
| `CaptureControlPolicy` | 상태에서 파생되는 허용 동작 |

상태는 `TigerApp`이 소유하고 화면은 값과 `onIntent`만 받는다. 작업 공간을 여는 것이 조회 화면의 동작이기 때문이다.

### 드라이버가 평범한 클래스가 아닌 이유

`rememberCaptureDriver`는 Composable이다. 권한 `rememberLauncherForActivityResult`는 composition에서만 만들 수 있고, tracking 폴링과 `ON_STOP`·`ON_START` 처리도 composition의 effect다. 무거운 것들은 `remember`로 한 번만 만들고, 돌려주는 `CaptureDriver`는 매 composition 새로 만든다 — 콜백이 `remember`에 갇히면 옛 상태를 보게 된다.

`previewSurface`·`previewTexture`가 드라이버에 있는 것은 Camera2 session을 여는 쪽이 거기이기 때문이다. 화면은 Surface가 생기고 사라졌다는 사실만 알린다.

### composition에 묶여 있어 올릴 수 없는 것

수집 파이프라인의 상당 부분은 실제로 composition과 Activity에 묶여 있다. 함께 올리면 수명주기를 직접 관리해야 하므로 오히려 위험해진다.

- `previewSurface`·`previewTexture`는 `AndroidView` 안 `TextureView`의 리스너에서 만들어져 수명이 View에 묶인다. ViewModel이 들고 있으면 backing View가 사라진 뒤의 null·release를 직접 처리해야 한다.
- 카메라 권한·프리뷰 권한·SAF 선택의 `rememberLauncherForActivityResult`는 composition에서만 만들 수 있다.
- ARCore `requestInstall`과 수집 화면의 방향 고정은 Activity를 필요로 한다.
- `CapturePreviewController`의 preflight가 `previewSurface`를 클로저로 잡는다.

### 데이터·업로드 계층은 올렸다 (해결)

Room 데이터베이스와 `SessionRepository`, `SessionUploadService`는 `TigerApplication`이 소유한다. `TigerApp`이 받아 쓰고, 세션 저장에 필요한 `repository`만 `CaptureWorkspace`에 넘긴다.

2026-09-17에는 "현재 동작에 결함이 없으므로 미룬다"고 두었으나 그 전제가 사실이 아니었다. `configChanges`에 `uiMode`·`locale`·`fontScale`·`density`가 없어, 다크 모드 전환만으로 Activity가 재생성되고 `remember`가 다시 돌아 인스턴스가 하나씩 더 생겼다. 닫는 경로는 없었다.

이 계층을 다시 화면 안으로 내리지 않는다. 회귀는 계측 `ApplicationScopedDependencyTest`가 잡는다.

### 화면은 갈랐다 (해결)

`TigerApp`이 앱 루트다. `NavHost`와 조회 흐름의 운용(전송·삭제), 그리고 수집 상태를 소유한다. `CaptureWorkspace`는 수집 파이프라인만 가져간다.

이전에는 한 함수가 둘을 다 들고 있었고, 수집 마감이 `navController`를 직접 밀었다. 지금은 `onCompleted(sessionId, uploadable)` 하나가 경계다. **수집 쪽에서 `NavController`나 route 타입을 참조하지 않는다.**

`MainActivity`는 `TigerApp`을 띄우는 것 외에 아무것도 하지 않는다.
