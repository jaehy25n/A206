# 에이전트 작업 지침 — Tiger

## 빌드와 테스트

저장소 루트에서 Gradle Wrapper를 실행한다.

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

`connectedDebugAndroidTest`는 연결된 실제 기기 또는 에뮬레이터가 있을 때만 실행한다.
단위 테스트만으로 실제 기기의 카메라, IMU, 권한, 저장소 동작을 검증했다고 판단하지 않는다.

## 프로젝트 규칙

- Android 앱 모듈은 `:app` 하나이며, Kotlin·Jetpack Compose·Material 3를 사용한다.
- 의존성 및 플러그인 버전은 `gradle/libs.versions.toml`에서 관리한다.
- Kotlin 공식 스타일을 따른다: 4칸 들여쓰기, null 안전성 활용, 작고 단일 책임인 함수.
- Composable과 클래스는 `PascalCase`, 함수·프로퍼티·파라미터는 `camelCase`를 사용한다.
- 부모가 소유하는 Compose 상태는 hoisting하고, Composable은 렌더링과 사용자 이벤트 처리로 한정한다.
- 사용자에게 보이는 문자열은 `res/values/strings.xml`에 두며, Composable에 하드코딩하지 않는다.
- 소스 식별자는 영어로 작성한다. 주석과 커밋 메시지는 한국어로 명확하게 작성한다.

## 변경 경계

- 작업 목적을 충족하는 최소 범위만 수정한다. 관련 없는 리팩터링, 일괄 포맷 변경, 의존성 정리를 하지 않는다.
- SDK·Gradle·Kotlin 버전 변경, 의존성 추가, 권한, 데이터 스키마, 업로드 동작, 서명, CI/CD 변경 전에는 먼저 확인한다.
- 결정론적 동작을 바꾸면 테스트를 갱신한다. 공개 사용자 흐름 또는 데이터 계약을 바꾸기 전에는 관련 명세를 먼저 갱신한다.

## 명세 산출물

- 기능별 명세·계획·작업은 `specs/<feature>/`에 둔다.
- 사용자 흐름, 데이터 형식, 상태 전이를 변경하면 해당 기능의 명세와 계약 문서를 함께 갱신한다.
- 구현 계획 또는 작업 분해가 바뀌면 해당 기능의 `plan.md`, `tasks.md`를 갱신한다.
- `$speckit-*` 작업과 task 완료 판정 시에는, 수정 대상이 `app/` 등 `specs/` 밖에 있더라도 반드시 `specs/AGENTS.md`의 완료 판정·검증 규칙을 읽고 따른다.

## Git

- 명시적으로 요청받지 않으면 commit, push, reset, 브랜치 삭제를 하지 않는다.
- 브랜치 이름은 소문자 kebab-case의 `<type>/<scope>` 형식을 사용한다. 사용자·도구·모델 이름 접두사는 사용하지 않는다.
- 브랜치 type은 목적에 맞게 `feature`, `fix`, `docs`, `chore`, `refactor`, `test` 중 하나를 사용한다.
- 커밋 요청 시 Conventional Commits를 사용한다.

  ```text
  <type>(<scope>): <한국어 요약>
  ```

  예: `feat(capture): 프레임별 타임스탬프 저장`,
  `fix(imu): 나노초 타임스탬프 보존`.

- 허용 타입: `feat`, `fix`, `test`, `refactor`, `docs`, `build`, `chore`.
- 커밋 하나에는 한 가지 목적의 변경만 포함한다. 생성 파일, `.idea/`, build output, secret, keystore, `.env` 파일은 커밋하지 않는다.
- Pull/Merge Request의 source·target 브랜치는 사용자 지시를 우선하며, 불명확하면 원격 기본 개발 브랜치와 병합 관계를 확인한 뒤 진행한다.
- Pull/Merge Request 제목은 `<type>(<scope>): <한국어 구체 요약>` 형식을 사용한다.
- push 전에는 포함할 커밋·문서·생성 파일·로컬 검사 산출물을 확인한다. 기능 계약을 바꾼 작업의 관련 명세 문서는 임의로 제외하지 않는다.
- 브랜치 삭제 전에는 원격 기준 브랜치에 병합됐거나 보존할 필요가 없음을 확인한다.

## 안전

- secret, private URL, access token, certificate, keystore material을 하드코딩하거나 출력하지 않는다.
- 단위 테스트 또는 에뮬레이터 테스트만으로 실제 기기 검증을 했다고 보고하지 않는다.
- 관련 없는 사용자 변경은 보존한다. 완료 보고에는 실행한 명령, 결과, 미검증 동작을 포함한다.
