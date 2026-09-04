# 구현 계획: Capture Session Recorder MVP — SAF Export

## Technical Context

| 항목 | 결정 |
| --- | --- |
| App | 단일 `:app` Android 모듈, Kotlin, Jetpack Compose, Material 3 |
| 지원 범위 | minSdk 28, targetSdk 37, Galaxy S10 실기기 검증 |
| 기존 저장 | 앱 전용 외부 저장소의 `capture/staging/` 및 `capture/completed/`; Room session catalog |
| Export API | Android Storage Access Framework의 tree URI와 persistable URI 접근 권한 |
| 검증 | 기존 `SessionBundleValidator`를 source/destination 공통 검사로 확장; JVM unit test와 Galaxy S10 수동 검증 |
| 의존성·권한 | 신규 라이브러리 및 broad storage permission 없음 |

## Constitution Check

프로젝트 constitution은 아직 템플릿 상태여서 적용 가능한 구체 원칙이 없다. 대신 저장소 지침을 gate로 적용한다.

- 신규 dependency, broad storage permission, 업로드 동작 변경은 금지한다.
- export 상태와 마지막 tree URI를 재시작 뒤 보존하려는 Room schema 변경은 **구현 전 사용자 승인 필요**다.
- Compose 상태는 상위 owner가 소유하고, 사용자 문자열은 `strings.xml`에 둔다.
- unit test는 SAF·권한·파일 provider의 실기기 동작을 대체하지 않는다.

**Gate result:** 계획 단계 통과. 2026-09-03에 사용자가 Room schema migration을 승인했다. export state·last tree URI·failure reason 영속화 구현은 진행할 수 있다.

## 설계

### 상태와 데이터 흐름

```text
COMPLETED + NOT_EXPORTED
  → EXPORTING
  → EXPORTED
  ↘ EXPORT_FAILED → EXPORTING (same completed source)
```

recording/upload state와 export state는 독립이다. export는 completed source directory만 읽으며, 실패·취소·권한 상실 때 source staging/completed 내용을 삭제하거나 변경하지 않는다. 대상에 남은 부분 파일은 정리하지 않고 다음 재시도에서 같은 `<session_id>` directory를 덮어쓴다.

### 구성 요소

1. `SessionBundleStore`를 `context.getExternalFilesDir(null)` 기반으로 구성해 raw session을 `capture/staging/<session_id>/`에 만들고 completed publish path를 유지한다. 기존 display-number 기반 staging 명명은 `session_id` 경로 계약에 맞춘다.
2. `SessionBundleValidator`를 metadata JSON의 stream declaration과 manifest filename/size/SHA-256까지 검증하도록 확장한다. source validator와 SAF destination validator는 같은 required-file/CSV/header 규칙을 공유한다.
3. `SessionRepository`/`DocumentTreeGateway`/`SessionBundleExporter` 경계를 둔다. repository는 export state, last tree URI, failure reason을 영속화하고, gateway는 tree picker 결과의 persistable read/write 권한과 document operation capability를 제공한다. exporter는 새 임시 attempt directory의 copy·validation·최종 publish·retry orchestration을 담당한다.
4. Room에는 session별 export state·마지막 tree URI·failure reason을 영속화한다. 이것은 재시작 retry를 위한 schema migration이며, 승인 전에는 구현하지 않는다. URI 자체가 권한을 주지 않으므로 persisted grant 유효성도 매 export 전에 확인한다.
5. `MainActivity`의 screen state를 ViewModel/상태 owner로 옮기고, completed Session에서만 Export 버튼을 노출한다. tree picker는 Documents 위치에서 시작하고 사용자가 선택한 모든 accessible tree URI를 허용한다. 권한 상실은 picker 재선택 안내로, 실패는 원인과 Retry action으로 표현한다.

### 권한 경계

- `ACTION_OPEN_DOCUMENT_TREE`와 returned tree URI child document만 사용한다.
- manifest에 broad storage permission을 추가하지 않는다.
- 마지막 tree URI는 선택된 URI permission이 유효한 경우에만 재사용한다. 권한 상실 시 `EXPORT_FAILED`로 전이하고 새 선택을 요구한다.

## 구현 단계

1. **Storage contract alignment** — external-files staging path와 session-id path를 구현·테스트하고, finalizer의 metadata-last 공개 조건을 강화한다.
2. **Export domain persistence** — 승인 후 export enum/model, Room migration, DAO/repository API와 failure state tests를 추가한다.
3. **SAF adapter and copy** — Android adapter와 fake tree gateway를 작성한다. 새 attempt directory의 copy·metadata-last·validation 뒤에만 최종 session directory를 publish하며, provider capability 부족, URI grant loss, copy/publish failure는 source-preserving 방식으로 처리한다.
4. **Validation** — source와 destination에서 mandatory files, exact CSV headers, metadata stream declaration, manifest size/SHA-256을 검사한다. failed/cancelled export는 success로 기록할 수 없다.
5. **Compose flow** — Documents-start picker, selected-tree reuse, progress/failure/retry/overwrite status와 strings resource를 연결한다.
6. **Verification** — JVM tests, lint, assemble 뒤 Galaxy S10에서 tree 선택·Documents 밖 provider·grant loss·storage exhaustion·retry와 manifest validation을 수동으로 확인한다.

## 영향 범위

- `app/src/main/java/.../episode/`: bundle path, validator, export model/repository/store
- `app/src/main/java/.../data/local/`: export state persistence 및 migration (승인 후)
- `app/src/main/java/.../MainActivity.kt`와 `res/values/strings.xml`: picker/export/retry UI
- `app/src/test/java/.../episode/`: path, validator, state, fake document-tree tests
- `AndroidManifest.xml`: camera permission 외 broad storage permission 추가 없음

## 검증 전략

자동 테스트는 state transition, same-ID overwrite, grant loss, copy I/O failure, source preservation, CSV/manifest/metadata mismatch를 커버한다. `testDebugUnitTest`, `lintDebug`, `assembleDebug`를 실행한다. Galaxy S10에서만 SAF provider behavior, Documents-start UX, persistable grant 재시작, 실제 free-space failure 및 exported file readability를 검증한다.
