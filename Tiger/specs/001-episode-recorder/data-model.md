# Capture Session 데이터 모델

## CaptureSession

기존 Session identity와 recording/upload lifecycle을 유지한다. raw stream source는 앱 전용 내부 저장 영역의 `capture/staging/<session_id>/`에서 finalize 후 `capture/completed/<session_id>/`로 공개된다. 원시 bundle은 일반 파일 관리자가 직접 수정·삭제할 수 있는 위치에 두지 않으며, Session 메타데이터와 상태는 별도 색인으로 관리한다.

| Field | Rule |
| --- | --- |
| `sessionId` | immutable UUID; staging/completed directory identity |
| `recordingState` | `COMPLETED`인 경우에만 업로드 대상 |
| `uploadState` | 번들 전송의 진행과 결과 |
| `bundlePath` | 수집 중과 `INTERRUPTED`에서는 staging directory, `COMPLETED`에서는 completed source directory. 다음 실행의 구제가 이 경로로 staging 번들을 찾는다 |

## SessionBundle Manifest

metadata의 raw-file manifest는 `path`, `sizeBytes`, lowercase `sha256`로 구성된다. `metadata.json` 자신은 manifest 대상에서 제외하고 마지막 commit marker로 쓴다. 번들 검증은 manifest가 선언하는 각 raw file의 이름·크기·digest를 비교한다.

## 관계와 불변식

- CaptureSession 1개는 0개 이상의 Episode marker를 갖고, marker는 raw stream을 소유하지 않는다.
- completed bundle은 공개된 뒤 수정하지 않는다. 업로드는 읽기만 한다.
- SAF 내보내기는 제거됐다. 번들을 기기 밖으로 내보내는 길은 업로드 하나다. `SessionExport`와
  `exportState`·`exportTreeUri`·`exportFailureReason` 컬럼은 이관 5→6에서 함께 사라졌다.
