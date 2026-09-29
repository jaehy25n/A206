# 에이전트 작업 지침 — Tiger

## 빌드와 테스트

저장소 루트에서 Gradle Wrapper를 실행한다.

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

화면(Composable)·문자열 리소스·접근성 속성을 바꾼 작업은 Merge Request 전에 기기 또는
에뮬레이터를 붙여 계측 테스트를 직접 실행한다. 이 검사는 기기가 필요해 hook에 들어가 있지
않으므로, 돌리지 않으면 아무도 돌리지 않는다. 실행하지 못했다면 그 사실을 MR에 적는다.

### 계측 테스트 실행

`connectedDebugAndroidTest`를 쓰지 않는다. 이 태스크는 실행할 때마다 APK를 다시 설치하는데,
debug APK가 51MB이고 그중 43MB가 dex라(2026-09-29 기준) 기기에서 처리하는 데 수 분씩 걸린다. 2026-09-21에
`SM-G973N`에서 32분을 기다려도 테스트가 시작되지 않았다. 전송이 느린 것은 아니다
(`adb push`는 74MB/s로 측정됐다).

설치를 한 번만 하고 실행을 반복한다.

```powershell
.\gradlew.bat assembleDebug assembleDebugAndroidTest
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb install -r app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk
adb shell am instrument -w com.ssafy.s15p21a206.tigermask.test/androidx.test.runner.AndroidJUnitRunner
```

2026-09-21에 같은 기기에서 당시 전체 20개가 15초에 끝났다. 모두 통과하면 마지막 줄이
`OK (N tests)`이고, N은 `app/src/androidTest`의 `@Test` 수와 같다(2026-09-29 기준 41개).
클래스나 메서드만 고르려면 `-e class`를 준다.

패키지 이름이 둘이다. `-w` 뒤의 instrumentation은 `applicationId`(`com.ssafy.s15p21a206.tigermask`)를
따르고, `-e class`의 클래스 이름은 코드 네임스페이스(`com.ssafy.s15p21a206.tiger`)를 따른다. 앞의 것이
틀리면 `Unable to find instrumentation info`로 바로 실패한다.

```powershell
adb shell am instrument -w -e class "com.ssafy.s15p21a206.tiger.ui.session.SessionListScreenTest" `
  com.ssafy.s15p21a206.tigermask.test/androidx.test.runner.AndroidJUnitRunner
adb shell am instrument -w -e class "com.ssafy.s15p21a206.tiger.ui.session.SessionListScreenTest#anEmptyTaskSessionListExplainsHowToAddOne" `
  com.ssafy.s15p21a206.tigermask.test/androidx.test.runner.AndroidJUnitRunner
```

`-w`는 끝날 때까지 기다린다는 뜻이다. 빼면 명령이 즉시 돌아오고 결과를 볼 수 없다. 사람이 읽을
때는 위 형태를 쓰고, 출력을 기계로 파싱할 때만 `-r`을 더한다. `-r`을 주면 점과 `OK (N tests)`
대신 `INSTRUMENTATION_STATUS` 블록이 나온다.

두 가지를 주의한다.

- **소스를 고쳤으면 반드시 다시 설치한다.** 설치를 건너뛰면 옛 APK를 검사하고 통과로 오인한다.
  `assembleDebug assembleDebugAndroidTest`가 `UP-TO-DATE`로 끝나는지 보고 APK가 최신인지 확인한다.
- **`am instrument`는 테스트가 실패해도 exit code 0을 돌려준다.** `$?`나 `$LASTEXITCODE`로 판정하지
  않는다. 기본 출력에서는 마지막의 `OK (N tests)` 또는 `FAILURES!!!`를, `-r`을 준 경우에는
  `INSTRUMENTATION_STATUS_CODE`(0=통과, -1=오류, -2=실패)를 읽는다.

기기 없이 도는 검사(`testDebugUnitTest`, `lintDebug`)로 계측 테스트를 대신했다고 보고하지 않는다.

## 프로젝트 규칙

- Kotlin 스타일은 `.editorconfig`의 `ktlint_official`을 기준으로 한다. 위반은 `.\\gradlew.bat ktlintFormat`으로 수정한 뒤 재검사한다.
- 새 clone 또는 worktree에서는 한 번 `.\\gradlew.bat installGitHooks`를 실행해 저장소의 git hook을 활성화한다. `pre-commit`은 `ktlintCheck`와 `testDebugUnitTest`, `commit-msg`는 커밋 제목 규격을 검사한다. 즉 스타일 위반이나 단위 테스트 실패는 커밋을 막는다.
- worktree에서는 `core.hooksPath`가 다른 체크아웃의 `.githooks`를 가리킬 수 있다(`extensions.worktreeConfig`가 켜져 있으면 worktree 전용 설정이 저장소 설정을 덮는다). hook은 스크립트가 놓인 곳이 아니라 커밋하는 체크아웃을 검사하므로 그래도 지금 커밋하는 파일이 검사된다.
- `git commit --no-verify`로 hook을 건너뛸 수 있으나, 그 커밋은 아무 검사도 거치지 않은 채 이력에 남는다. 검사가 잡은 문제를 고치는 것이 기본이고, 건너뛰었다면 왜 건너뛰었는지와 언제 고칠지를 남긴다.
- 소스 식별자는 영어로 작성한다. 주석과 커밋 메시지는 한국어로 명확하게 작성한다.
- `app/` 아래를 수정할 때는 `app/AGENTS.md`의 Compose·리소스 규칙과 기록된 예외를 읽고 따른다.

## 변경 경계

- 작업 목적을 충족하는 최소 범위만 수정한다. 관련 없는 리팩터링, 일괄 포맷 변경, 의존성 정리를 하지 않는다.
- 지시받은 작업 도중 발견한 문제를 별개 이슈로 분리할지 혼자 판단하지 않는다. 직전 변경이 만든 필요인지 먼저 따지고, 판단이 갈리면 묻는다.
- SDK·Gradle·Kotlin 버전 변경, 의존성 추가, 권한, 데이터 스키마, 업로드 동작, 서명, CI/CD 변경 전에는 먼저 확인한다.
- 결정론적 동작을 바꾸면 테스트를 갱신한다. 공개 사용자 흐름 또는 데이터 계약을 바꾸기 전에는 관련 명세를 먼저 갱신한다.

## 작업 시작·재개 전 확인

- 구현 또는 task의 미구현 여부를 판단하기 전에 `git fetch origin develop`으로 기준 브랜치를 갱신하고, 현재 브랜치와의 차이를 확인한다. 사용자 지정 기준점이 있으면 이를 따른다. 이 규칙은 기존 브랜치에서 작업을 재개하거나 `$speckit-*`를 실행할 때도 적용한다.
- `tasks.md`의 `[ ]`만으로 미구현이라고 판단하지 않는다. 최신 기준 브랜치의 코드·production 호출 경로·관련 테스트와 대조하고, 문서와 구현이 다르면 관련 MR·커밋 이력을 확인한다.
- 이미 구현된 범위는 재구현하지 않는다. `tasks.md`를 정합화하고, 남은 범위만 구현한다.
- 원격 확인에 실패하면 확인 한계를 명시하고 최신 상태라고 단정하지 않는다.

## 명세 산출물

- 기능별 명세·계획·작업은 `specs/<feature>/`에 둔다.
- 사용자 흐름, 데이터 형식, 상태 전이를 변경하면 해당 기능의 명세와 계약 문서를 함께 갱신한다.
- 구현 계획 또는 작업 분해가 바뀌면 해당 기능의 `plan.md`, `tasks.md`를 갱신한다.
- `$speckit-*` 작업과 task 완료 판정 시에는, 수정 대상이 `app/` 등 `specs/` 밖에 있더라도 반드시 `specs/AGENTS.md`의 완료 판정·검증 규칙을 읽고 따른다.

## Git

- 명시적으로 요청받지 않으면 push, reset, 브랜치 삭제, 원격 브랜치 생성, Merge Request 생성·수정·종료를 하지 않는다. 한 번 받은 승인은 그때 지시받은 작업에만 유효하며, 작업 중 새로 발견한 건에는 미치지 않는다.
- 커밋은 작업 중에 한다. 목적 하나가 끝나 그 자체로 온전한 단위가 되면 그 시점에 커밋하며, 따로 승인을 받지 않는다. 작업을 모두 끝낸 뒤 한 덩어리를 목적별로 쪼개려 하지 않는다.
- 커밋 단위를 미리 선언하지 않는다. 경계는 작업하면서 드러나므로 시작 시점의 계획은 추측이 된다.
- 브랜치 이름은 소문자 kebab-case의 `<type>/<scope>` 형식을 사용한다. 사용자·도구·모델 이름 접두사는 사용하지 않는다.
- 브랜치 type은 목적에 맞게 `feature`, `fix`, `docs`, `chore`, `refactor`, `test` 중 하나를 사용한다.
- 사용자 지시로 다른 기준점을 명시하지 않는 한, 새 작업 브랜치는 반드시 `git fetch origin develop` 후 최신 `origin/develop`에서 생성한다. 현재 체크아웃 브랜치를 기준점으로 추정해 분기하지 않는다.
- Merge Request 생성 전에는 `git fetch origin develop`으로 대상을 갱신하고, `git merge-base origin/develop HEAD`와 비교 로그를 확인한다. `develop`에 동일 작업이 이미 병합됐거나 기준점이 뒤처졌다면 rebase·중복 제거를 먼저 수행한다.
- 커밋 메시지는 Conventional Commits를 사용한다.

  ```text
  <type>(<scope>): <한국어 요약>
  ```

  예: `feat(capture): 프레임별 타임스탬프 저장`,
  `fix(imu): 나노초 타임스탬프 보존`.

- 허용 타입: `feat`, `fix`, `test`, `refactor`, `docs`, `build`, `chore`.
- 커밋 하나에는 한 가지 목적의 변경만 포함한다. 생성 파일, `.idea/`, build output, secret, keystore, `.env` 파일은 커밋하지 않는다.
- 구현을 시작하기 전에 Jira 프로젝트·보드에서 대응 이슈가 이미 있는지 확인한다. 대응 이슈가 없으면 등록할 제목·작업 범위·완료 조건을 제시하고 승인을 받은 뒤 등록한다. 이슈 상태 전환도 요청받았을 때만 한다.
- Pull/Merge Request 제목은 `<type>(<scope>): <한국어 구체 요약>` 형식을 사용한다.
- Pull/Merge Request를 만들 때 작성자를 Assignee로 지정하고, 설명에 `Related Jira: <JIRA-KEY>` 형식으로 대응 Jira 이슈 키를 기록한다. 여러 이슈와 관련되면 모든 키를 쉼표로 구분해 기록한다.
- push 전에는 포함할 커밋·문서·생성 파일·로컬 검사 산출물을 확인한다. 기능 계약을 바꾼 작업의 관련 명세 문서는 임의로 제외하지 않는다.
- 브랜치 삭제 전에는 원격 기준 브랜치에 병합됐거나 보존할 필요가 없음을 확인한다.

## 안전

- secret, private URL, access token, certificate, keystore material을 하드코딩하거나 출력하지 않는다.
- 단위 테스트 또는 에뮬레이터 테스트만으로 카메라, IMU, 권한, 저장소 등 실제 기기 동작을 검증했다고 판단하거나 보고하지 않는다.
- 관련 없는 사용자 변경은 보존한다. 완료 보고에는 실행한 명령, 결과, 미검증 동작을 포함한다.
