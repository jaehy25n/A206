# Capture Session SAF Export 검증 가이드

## 사전 조건

- Galaxy S10에서 main-only Capture Session을 정상 finalize해 completed bundle을 만든다.
- 앱에 CAMERA 외 broad storage permission이 선언되지 않았음을 확인한다.
- export 검증은 [bundle 계약](contracts/episode-bundle.md)과 [데이터 모델](data-model.md)을 따른다.

## 자동 검증

저장소 루트에서 실행한다.

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

2026-09-08에 HTTP upload 구현 뒤 위 세 검증을 실행했고 모두 성공했다. 단위 테스트는 MockWebServer receipt·상태 전이를 검증하지만 실제 기기 또는 ingestion server 전송을 대체하지 않는다.

다음 unit test를 추가·실행한다.

- app-specific staging path 및 `metadata.json` 마지막 commit marker
- completed source와 SAF destination의 mandatory file/CSV/manifest/metadata validation
- `NOT_EXPORTED → EXPORTING → EXPORTED`, cancel/grant-loss/I/O failure와 retry
- same-session destination overwrite 및 source preservation

## HTTP upload 설정과 검증

개발 서버 주소는 저장소에 기록하지 않는다. 로컬 `local.properties`에 다음 값을 설정한 뒤 debug APK를 다시 빌드한다.

```properties
tigerUploadBaseUrl=http://<ingestion-server>
```

completed Session에서 **업로드**를 선택한다. 앱은 source bundle을 먼저 검증하고, 동일한 UUID를 `Idempotency-Key`와 metadata `session_id`로 사용해 전체 multipart를 전송한다. `201 created` 또는 `200 duplicate`의 JSON receipt가 전송한 session ID와 일치할 때만 `UPLOADED`로 표시한다. 실패·앱 종료로 중단된 `UPLOADING`은 `FAILED`로 복구되며, **업로드 재시도**는 원본을 수정·삭제하지 않고 같은 session ID로 전체 request를 다시 보낸다.

실서버 검증은 Android에서 completed Session을 만든 뒤 다음 순서로 수행한다.

1. SAF export한 동일 bundle을 PC에서 multipart로 보내 `201 created` 또는 `200 duplicate`를 확인한다.
2. 앱에서 같은 Session을 업로드해 상태가 `UPLOADED`로 바뀌는지 확인한다.
3. 네트워크 오류 또는 의도적으로 잘못된 receipt를 재현해 `FAILED`와 수동 재시도가 표시되고 source bundle이 남는지 확인한다.

## Galaxy S10 수동 검증

1. completed Session의 Export를 선택하고 picker가 Documents 위치에서 시작하는지 확인한다.
2. Documents tree와 Documents 밖 provider tree를 각각 선택한다. 두 경우 모두 `TigerCapture/<session_id>/`가 선택된 tree URI 하위에만 생성되는지 확인한다.
3. export 후 모든 mandatory file, CSV headers, metadata manifest의 file size/SHA-256을 비교한다.
4. 앱을 재시작하고 마지막 tree 권한이 유효할 때 같은 Session retry가 가능한지 확인한다.
5. tree 권한 철회, picker 취소, provider I/O/여유 공간 부족을 재현한다. `EXPORT_FAILED`, 실패 사유, tree 재선택 또는 Retry action, source staging/completed 보존을 확인한다.
6. 같은 session directory를 재-export해, 새 임시 attempt directory가 검증된 뒤에만 final directory를 overwrite하는지 확인한다. publish 단계 실패 시 source bundle은 보존되고 실패한 attempt directory는 남으며, 다음 retry가 새 attempt로 시작하는지 확인한다.

실기기 검증은 unit test로 대체할 수 없다.
