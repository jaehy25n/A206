# Capture Control UX 데이터 모델

## CaptureSession 요약

기존 Session 식별자와 bundle 파일 형식은 유지한다. 목록 또는 상세 projection은 다음 필드를 사용한다.

| 필드 | 규칙 |
| --- | --- |
| `sessionId` | 불변 UUID 및 bundle 식별자 |
| `displayNumber` | 사용자에게 보이는 Session 번호 |
| `recordingState` | bundle이 관리되는 내부 completed root에 있을 때만 `COMPLETED` Session을 목록·상세·업로드 대상으로 한다. |
| `uploadState` | `LOCAL_ONLY`, `UPLOADING`, `UPLOADED`, `FAILED` |
| `recordingStartEpochMs` | Session Detail의 날짜·시각을 위한 로컬 벽시계 수집 시작 시각. migration은 안전한 legacy 기본값을 제공하며 legacy 행은 경로 기준으로 제외한다. |
| `recordingStart` / `recordingEnd` | 수집 길이 계산에 사용하는 monotonic 값 |
| `bundlePath` | 내부 completed root 하위 canonical 경로. legacy 외부 경로는 이전·삭제 없이 제외한다. |
| `completedEpisodeCount` | outcome이 `COMPLETED`인 하위 Episode marker 개수 |

## EpisodeMarker

| 필드 | 규칙 |
| --- | --- |
| `task` / `objectName` | 첫 재생 전에 필수 입력하고, 해당 Session의 모든 Episode에 변경 없이 적용한다. |
| `outcome` | `ACTIVE`, `COMPLETED`, `INVALID_TRACKING`만 사용하며 `CANCELLED`는 제거한다. |
| `startTimestampNs` / `endTimestampNs` | 재생과 일시 정지·정지에서 Episode 경계를 쓴다. 완료된 Session에는 열린 Episode가 남을 수 없다. |

## 업로드 작업

한 Session을 키로 하는 일시적 UI·실행 상태다.

| 상태 | 진입 | 이탈 |
| --- | --- | --- |
| `Idle` | Detail을 연다. | 사용자가 전송 또는 재전송을 선택한다. |
| `Uploading` | 정지가 Session을 확정하거나 Detail에서 전송·재전송을 시작한다. | 기존 업로드 receipt 성공·실패, 확인된 취소, 백그라운드 전환 |
| `Uploaded` | 유효한 기존 서버 receipt | 이 기능에서는 종료 상태 |
| `Failed` | HTTP 실패, 취소 또는 백그라운드 중단 | Detail에서 재전송 선택 |

Session마다 하나의 작업만 소유할 수 있다. 업로드 상태 화면만 비결정적 진행 표시와 취소를 담당한다.

## 저장소 불변식

- staging과 completed bundle은 분리하고 metadata-last 공개 규칙을 유지한다.
- 원시 bundle은 업로드·export 중 수정하지 않는다.
- `filesDir/capture/completed/<session_id>/`만 이 기능이 관리하는 completed source root다.
- 외부 저장소 Session 경로는 복사·삭제·목록·상세·export·업로드하지 않는다.
