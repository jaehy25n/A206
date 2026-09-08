# Capture Session Export 데이터 모델

## CaptureSession

기존 Session identity와 recording/upload lifecycle을 유지한다. raw stream source는 앱 전용 내부 저장 영역의 `capture/staging/<session_id>/`에서 finalize 후 `capture/completed/<session_id>/`로 공개된다. 원시 bundle은 일반 파일 관리자가 직접 수정·삭제할 수 있는 위치에 두지 않으며, Session 메타데이터와 상태는 별도 색인으로 관리한다.

| Field | Rule |
| --- | --- |
| `sessionId` | immutable UUID; staging/completed/export directory identity |
| `recordingState` | `COMPLETED`인 경우에만 export 허용 |
| `uploadState` | export와 독립 |
| `bundlePath` | completed source directory; export가 변경하지 않음 |

## SessionExport

| Field | Rule |
| --- | --- |
| `sessionId` | CaptureSession과 1:1 |
| `state` | `NOT_EXPORTED`, `EXPORTING`, `EXPORTED`, `EXPORT_FAILED` |
| `treeUri` | 마지막 선택 tree URI; persisted grant가 유효할 때만 재사용 |
| `failureReason` | 실패 상태에서 사용자에게 표시할 안전한 원인; 성공 시 비움 |

### 전이

- `NOT_EXPORTED → EXPORTING` : completed source validation과 tree access 확인 뒤.
- `EXPORTING → EXPORTED` : 대상 파일·CSV headers·manifest·metadata validation 성공 뒤.
- `EXPORTING → EXPORT_FAILED` : 취소, grant loss, overwrite/copy I/O, space 부족, destination validation failure.
- `EXPORT_FAILED → EXPORTING` : 같은 immutable completed source로 retry.

## SessionBundle Manifest

metadata의 raw-file manifest는 `path`, `sizeBytes`, lowercase `sha256`로 구성된다. `metadata.json` 자신은 manifest 대상에서 제외하고 마지막 commit marker로 쓴다. destination validation은 manifest가 선언하는 각 raw file의 이름·크기·digest를 비교한다.

## 관계와 불변식

- CaptureSession 1개는 0개 또는 1개의 SessionExport 상태를 가진다.
- SessionExport는 Episode marker나 raw stream을 소유하지 않는다.
- source staging/completed data는 어떤 export 전이에도 삭제·수정되지 않는다.
- 각 SessionExport attempt는 unique `attemptId`를 가지며 selected tree URI 안의 임시 directory에 대응한다. 성공한 attempt만 `TigerCapture/<session_id>/`로 publish한다.
- 같은 tree URI에서 최종 directory가 이미 있으면 검증 성공한 attempt만 이를 덮어쓴다. 실패한 attempt directory는 남기고 retry는 새 `attemptId`를 사용한다.
