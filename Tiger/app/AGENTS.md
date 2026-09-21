# 앱 모듈 작업 지침

`:app`의 Kotlin·Compose 코드와 리소스에 적용된다. 저장소 전체 규칙은 루트 [AGENTS.md](../AGENTS.md)에 있다.

## 코드 규칙

- Composable과 클래스는 `PascalCase`, 함수·프로퍼티·파라미터는 `camelCase`를 사용한다.
- ktlint의 `standard:function-naming`은 Composable의 `PascalCase`를 허용하지 않는다. 테스트 소스까지 포함해 Composable 선언에는 `@Suppress("FunctionName")`을 붙인다.
- 사용자에게 보이는 문자열은 `res/values/strings.xml`에 두며, Composable에 하드코딩하지 않는다.
- 부모가 소유하는 Compose 상태는 hoisting하고, Composable은 렌더링과 사용자 이벤트 처리로 한정한다.

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
