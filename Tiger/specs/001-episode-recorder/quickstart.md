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

다음 unit test를 추가·실행한다.

- app-specific staging path 및 `metadata.json` 마지막 commit marker
- completed source와 SAF destination의 mandatory file/CSV/manifest/metadata validation
- `NOT_EXPORTED → EXPORTING → EXPORTED`, cancel/grant-loss/I/O failure와 retry
- same-session destination overwrite 및 source preservation

## Galaxy S10 수동 검증

1. completed Session의 Export를 선택하고 picker가 Documents 위치에서 시작하는지 확인한다.
2. Documents tree와 Documents 밖 provider tree를 각각 선택한다. 두 경우 모두 `TigerCapture/<session_id>/`가 선택된 tree URI 하위에만 생성되는지 확인한다.
3. export 후 모든 mandatory file, CSV headers, metadata manifest의 file size/SHA-256을 비교한다.
4. 앱을 재시작하고 마지막 tree 권한이 유효할 때 같은 Session retry가 가능한지 확인한다.
5. tree 권한 철회, picker 취소, provider I/O/여유 공간 부족을 재현한다. `EXPORT_FAILED`, 실패 사유, tree 재선택 또는 Retry action, source staging/completed 보존을 확인한다.
6. 같은 session directory를 재-export해, 새 임시 attempt directory가 검증된 뒤에만 final directory를 overwrite하는지 확인한다. publish 단계 실패 시 source bundle은 보존되고 실패한 attempt directory는 남으며, 다음 retry가 새 attempt로 시작하는지 확인한다.

실기기 검증은 unit test로 대체할 수 없다.
