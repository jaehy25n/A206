# 구현 계획: Capture Session Recorder MVP

## 요약

기존 episode별 recording lifecycle을 Capture Session lifecycle으로 교체한다. Session start가 ARCore SharedCamera, main RGB writer, raw IMU writer, pose writer를 함께 소유하고, Episode는 timestamp marker만 만든다. completed bundle을 사용자 선택 Documents tree에 export하거나 upload 단위로 사용한다.

## 설계 결정

- Session state: `IDLE → INITIALIZING → READY → FINALIZING → COMPLETED`이며 치명 오류는 `INTERRUPTED`로 전이한다. Episode가 ACTIVE여도 Session은 READY의 연속 raw recording을 유지한다.
- Export state: `NOT_EXPORTED → EXPORTING → EXPORTED` 또는 `EXPORTING → EXPORT_FAILED → EXPORTING`이다. export state는 completed bundle의 보존·upload state와 독립이며, `EXPORT_FAILED`에서도 source를 변경하지 않는다.
- Episode state: `NONE → ACTIVE → COMPLETED | CANCELLED | INVALID_TRACKING`이다. tracking이 1초 연속 안정화되어야 START를 활성화하며, 0.5초 이상 loss면 임계 timestamp로 ACTIVE Episode를 자동 종료하고 invalid 처리한다.
- 모든 writer는 staging Session directory 하나에 연속 기록한다. metadata는 validation·SHA-256 뒤 마지막 commit marker로 작성한다.
- raw stream은 앱 전용 외부 저장소의 `Android/data/com.ssafy.s15p21a206.tiger/files/capture/staging/<session_id>/`에 기록한다. 정상 finalize 후에만 export 가능하며, SAF tree URI 아래 `TigerCapture/<session_id>/`를 기본 제안한다.
- export는 source와 destination에서 필수 파일·CSV header·SHA-256 manifest·metadata 선언을 검증한다. 실패·취소 시 원본 staging/completed bundle은 보존하고 재시도 상태로 남긴다.
- 공용 Documents 직접 쓰기 broad storage permission은 사용하지 않는다. 앱 삭제 전 영구 보존은 사용자 명시 export에 한정한다.
- Camera `SENSOR_TIMESTAMP`, sensor timestamp, app marker timestamp, ARCore Android camera timestamp를 같은 monotonic timeline으로 보존한다. REALTIME preflight 실패는 시작 불가다.
- main-only baseline을 P0로 하고 Ultra-wide는 10~30분 실기기 probe가 성공할 때만 optional Session stream으로 넣는다.
- upload는 Session bundle 전체에 `POST /sessions`, `Idempotency-Key=session_id`를 사용한다.
- MVP upload endpoint는 신뢰된 폐쇄망의 HTTPS endpoint이며 앱 수준 인증을 추가하지 않는다.

## 영향 범위

- 기존 Episode 모델·저장소·upload 모델은 `CaptureSession`과 `EpisodeMarker` 관계로 migration한다.
- Camera/ARCore 결합, raw writers, pose writer, frame timestamp writer, state machine 및 Compose UI를 Session lifecycle으로 재구성한다.
- `contracts/episode-bundle.md`, `contracts/episode-upload.md`의 file names·metadata·multipart part를 Session 계약으로 적용하고, bundle 계약에 staging/completed 및 SAF export 계약을 추가한다.

## 검증 전략

단위 테스트로 상태 전이, marker 기록, validator, metadata/CSV serialization, SAF export 전후 검증과 실패 재시도, upload request와 오류 상태를 검증한다. Galaxy S10 실기기에서 main-only baseline, clock-source preflight, tracking threshold, Documents tree 선택·export 실패 재시도 및 UW probe를 별도로 수동 검증한다. 실제 기기 검증은 unit test를 대체하지 않는다.
