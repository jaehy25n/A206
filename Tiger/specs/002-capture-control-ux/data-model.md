# Capture Control UX 데이터 모델

## CaptureSession 요약

기존 Session 식별자와 bundle 파일 형식은 유지한다. 목록 또는 상세 projection은 다음 필드를 사용한다.

| 필드 | 규칙 |
| --- | --- |
| `sessionId` | 불변 UUID 및 bundle 식별자 |
| `displayNumber` | 기존 bundle·metadata 호환성을 위해 보존하는 내부 순번. 목록의 주 식별자로 표시하지 않는다. |
| `recordingState` | bundle이 관리되는 내부 completed root에 있을 때만 `COMPLETED` Session을 목록·상세·업로드 대상으로 한다. |
| `uploadState` | `LOCAL_ONLY`, `UPLOADING`, `UPLOADED`, `FAILED` |
| `recordingStartEpochMs` | Session Detail의 날짜·시각을 위한 로컬 벽시계 수집 시작 시각. migration은 안전한 legacy 기본값을 제공하며 legacy 행은 경로 기준으로 제외한다. |
| `recordingStartMonotonicTimestampNs` / `recordingEndMonotonicTimestampNs` | 수집 길이 계산에 사용하는 monotonic 값. 색인 컬럼은 `recordingStartNs` / `recordingEndNs`다. |
| `bundlePath` | 내부 completed root 하위 canonical 경로. legacy 외부 경로는 이전·삭제 없이 제외한다. |
| `completedEpisodeCount` | outcome이 `COMPLETED`인 하위 Episode marker 개수 |
| `taskName` | Session 행의 `task` 값. Task 홈에서 Session을 묶는 키이고 상세 본문에서 Object와 짝으로 표시하며, 값이 없으면 `이름 없는 Task` 그룹으로 표시한다. |
| `objectName` | Session 행의 `objectName` 값. 목록 카드와 상세 본문에서 수집 대상을 확인하는 데 쓴다. 두 화면 모두 수집 일시에 딸린 줄이며, 값이 없으면 그 자리를 세우지 않는다. |

### Task와 Object의 저장 위치

두 이름은 수집 시작 때 한 번 입력받아 Session 전체에 적용되므로 `sessions` 행에 저장한다. `episode_markers` 집계로 역산하지 않는다. 역산하던 때에는 Episode를 하나도 시작하지 않은 Session에서 두 이름이 빈 문자열이 되어, 수집자가 분명히 입력한 값이 `이름 없는 Task` 그룹으로 떨어졌다.

`episode_markers`의 `task`·`objectName`은 그대로 유지한다. 번들의 `episodes.csv`가 Episode마다 두 열을 요구하는 계약이기 때문이다. 두 곳의 값은 같으며, Session 행이 조회의 유일한 출처다.

migration은 컬럼을 더하는 것으로 끝나지 않는다. 조회가 집계를 떠나 Session 행을 읽으므로, 이전 버전에서 마감된 Session은 같은 migration 안에서 Episode 행이 가진 값으로 채운다. 채우지 않으면 이미 쌓인 Session이 전부 `이름 없는 Task`로 떨어져, 이 변경이 고치려는 증상을 과거 데이터 전체에 되풀이한다. 채울 Episode 행이 없는 Session만 빈 값으로 남는다. 그 두 이름은 애초에 어디에도 저장된 적이 없다.

## EpisodeMarker

| 필드 | 규칙 |
| --- | --- |
| `task` / `objectName` | 첫 재생 전에 필수 입력하고, 해당 Session의 모든 Episode에 변경 없이 적용한다. 번들 계약을 위해 Episode 행에도 남기며, 조회는 Session 행에서 읽는다. |
| `outcome` | `ACTIVE`, `COMPLETED`, `INVALID_TRACKING`만 사용하며 `CANCELLED`는 제거한다. |
| `startTimestampNs` / `endTimestampNs` | 재생에서 시작 경계를, 일시 정지(`COMPLETED`) 또는 Tracking 유실(`INVALID_TRACKING`)에서 끝 경계를 쓴다. 열린 Episode가 있으면 정지가 거부되므로 완료된 Session에는 열린 Episode가 남을 수 없다(003 FR-006). |

## 업로드 작업

전송 상태는 색인의 `uploadState`가 들고, Detail은 그 값을 그대로 그린다. (2026-09-29 정리) 처음에는 Session을 키로 하는 일시적 상태(`Idle`·`Uploading`·`Uploaded`·`Failed`)를 따로 두는 설계였으나 그런 타입은 만들지 않았다.

| `uploadState` | 진입 | 이탈 |
| --- | --- | --- |
| `LOCAL_ONLY` | Session 확정. 업로드 서버 주소가 없는 빌드에서는 여기 머문다. | Detail에서 전송 선택 |
| `UPLOADING` | 정지가 Session을 확정한 직후(앱이 전면일 때), 또는 Detail에서 전송·재전송을 시작한다. | 서버 receipt 성공·실패, 백그라운드 전환 |
| `UPLOADED` | 유효한 서버 receipt | 이 기능에서는 종료 상태 |
| `FAILED` | HTTP 실패, 백그라운드 중단, 백그라운드에서 마감된 Session, 앱을 다시 켰을 때 남아 있던 `UPLOADING` | Detail에서 재전송 선택 |

실행 중인 것은 앱에 하나뿐인 `SessionOperations`가 든다. 진행 중인 전송 Job 하나와, 저장하지 않는 마지막 실패 사유 하나이며 Session을 키로 나누지 않는다. 그래서 전송이 겹치면 마지막에 건 것만 추적하고, 실패 사유는 마지막 실패의 것 하나가 `FAILED`인 Session의 상세마다 보인다. 진행 표시는 Session Detail이 담당한다. 사용자가 전송을 중간에 끊는 수단은 두지 않으며, 백그라운드 전환만이 진행 중인 전송을 끊는다.

## 삭제 연산

기기에서만 지운다. 서버에 DELETE API가 없으므로 색인과 번들에만 미친다.

| 연산 | 규칙 |
| --- | --- |
| `CaptureSessionDao.delete(sessionId)` | 색인의 Session 행을 지운다. `uploadState`가 `UPLOADING`이면 repository가 먼저 거절하므로 도달하지 않는다. |
| `EpisodeMarkerDao.deleteForSession(sessionId)` | 그 Session의 Episode marker를 함께 지운다. 두 테이블에 외래 키가 없어 색인에 고아 marker가 남지 않도록 명시적으로 지운다. |
| `CaptureSessionDao.allSessionIds()` | 고아 번들 회수가 쓰는 색인의 전체 id. `recordingState`를 가리지 않는다. 아직 마감되지 않은 Session의 디렉터리를 고아로 오인해 지우면 수집 중인 데이터가 사라진다. |
| `SessionBundleStore.deleteCompletedBundle(path)` | 관리하는 completed 디렉터리만 지운다. 관리 대상이 아니면 아무것도 하지 않고 지워진 것으로 본다. 이전 버전의 외부 경로를 건드리지 않기 위함이다. |
| `SessionBundleStore.orphanCompletedBundles(knownIds)` | completed root에서 색인에 대응하는 행이 없는 디렉터리를 낸다. |

삭제 결과는 세 가지다.

| 결과 | 뜻 |
| --- | --- |
| `DELETED` | 색인과 번들이 모두 사라졌다. |
| `BUNDLE_RETAINED` | 색인은 지웠지만 디렉터리가 남았다. 목록에서는 사라지며 다음 실행이 디렉터리를 회수한다. |
| `UPLOAD_IN_PROGRESS` | 전송이 번들을 읽고 있어 지우지 않았다. 색인도 번들도 그대로다. |

## 고아 번들 수명주기

1. 삭제가 색인을 먼저 지우고 디렉터리를 지운다. 디렉터리 삭제가 실패하면 그 디렉터리는 고아가 된다.
2. 고아는 색인에 행이 없으므로 목록·상세·전송 어디에도 나타나지 않는다. 저장 공간만 차지한다.
3. 다음 앱 시작에서 `SessionRepository.purgeOrphanBundles()`가 회수한다. 실행 순서는 staging 구제
   → 중단된 업로드 정리 → 순번 정규화 → 고아 회수다. 구제가 staging에서 옮겨 온 번들은 색인에 행이
   있어 고아가 아니지만, 회수를 구제보다 먼저 돌리면 옮겨지기 전 상태를 보고 판단하게 된다.

## 저장소 불변식

- staging과 completed bundle은 분리하고 metadata-last 공개 규칙을 유지한다.
- 원시 bundle은 업로드 중 수정하지 않는다.
- `filesDir/capture/completed/<session_id>/`만 이 기능이 관리하는 completed source root다.
- 외부 저장소 Session 경로는 복사·삭제·목록·상세·업로드하지 않는다.
- 삭제는 관리하는 completed 번들에만 미친다. 색인을 먼저 지우므로 재생·전송이 불가능한 Session이 목록에 남지 않는다.
