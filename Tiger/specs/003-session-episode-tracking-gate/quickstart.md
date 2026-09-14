# 검증 가이드: Session/Episode 분리와 Tracking 유효성 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](spec.md) | **계획**: [plan.md](plan.md)

구현이 끝난 뒤 이 기능이 실제로 동작하는지 확인하는 절차. 자동 검증과 실기기 검증을 나누어 기술한다. 계약 세부는 [contracts/](contracts/)를, 필드 정의는 [data-model.md](data-model.md)를 참조한다.

## 사전 조건

- 저장소 루트에서 Gradle Wrapper를 실행한다.
- 실기기 검증에는 ARCore(Google Play Services for AR)가 설치된 Android API 28 이상 기기가 필요하다. 기준 기기는 Galaxy S10 계열이다.
- 새 clone 또는 worktree라면 `.\gradlew.bat installGitHooks`를 한 번 실행한다.

## 자동 검증

```bash
./gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug
```

Compose 제어 상태 검증은 연결된 기기 또는 에뮬레이터가 있을 때만 실행한다.

```bash
./gradlew.bat connectedDebugAndroidTest
```

### 자동 검증이 덮는 범위

| 대상 | 확인 내용 | 대응 요구사항 |
|---|---|---|
| 상태 기계 | 가상 시계로 1초 안정화 후 `Ready` 전이, 0.5초 미만 유실 시 Episode 유지, 0.5초 이상 유실 시 `INVALID_TRACKING` 마감, 마감 시각이 유실 시작 + 0.5초 | FR-008, FR-010~FR-012 |
| 상태 기계 | `Ready`가 아닌 상태에서 Episode 시작 거부 | FR-009 |
| 상태 기계 | 자동 마감된 Episode를 사용자 조작으로 다시 마감하지 않음 | 불변식 6 |
| 제어 정책 | 다섯 상태별 재생·일시 정지·정지 활성화 여부 | FR-003, FR-006, FR-009 |
| frame index | 0부터 1씩 증가, 결번 없음. 중복 콜백 입력 시에도 프레임당 1회만 증가 | FR-017 |
| frame index | 녹화 구간 플래그가 꺼진 동안 행이 기록되지 않음 | FR-020 |
| 메타데이터 | `camera` 객체 직렬화, 선택 필드 미확보 시 키 생략 | FR-021, FR-023, FR-024 |
| 메타데이터 | 메타데이터 획득 실패를 주입해도 Session 마감이 완료됨 | FR-025 |
| 메타데이터 | 기존 세 키가 보존되어 `SessionBundleValidator`가 통과 | FR-026 |

**중요**: 상태 기계 테스트는 가상 시계를 쓰되, ticker가 실제로 `onTracking()`을 반복 호출하는 경로까지 포함해야 한다. 값 변화에만 반응하는 구현은 단위 테스트에서 통과하면서 실기기에서 0.5초 마감이 영영 발화하지 않을 수 있다([research.md](research.md) 결정 1).

## 실기기 검증

자동화할 수 없는 항목이며, 이 절이 끝나지 않은 상태로 기능을 완료로 보고하지 않는다.

### 시나리오 1 — Session과 Episode 분리 (US1)

1. 수집 화면에 진입해 task와 object를 입력한다.
2. 재생을 눌러 Session을 시작한다.
   - **기대**: 화면이 `INITIALIZING`을 표시한다. Episode가 시작되지 않는다.
3. 기기를 천천히 움직여 ARCore Tracking을 안정화시킨다.
   - **기대**: 화면이 `READY`로 바뀌고 재생이 활성화된다.
4. 재생을 눌러 Episode를 시작하고, 잠시 뒤 일시 정지로 종료한다.
   - **기대**: 화면이 `READY`로 돌아가고 프리뷰가 끊기지 않는다.
5. 3번 더 반복해 총 4개의 Episode를 수집한다.
6. 정지를 눌러 Session을 종료한다.

**확인**: 번들의 `episodes.csv`에 Episode 4개가 있고, 모든 `start_timestamp_ns`가 Session 시작 시각보다 크다. `accelerometer.csv`, `gyroscope.csv`, `arcore_poses.csv`의 시각 범위가 Session 전체를 연속으로 덮으며 Episode 사이에 공백이 없다. (SC-001, SC-004)

### 시나리오 2 — Tracking 게이트 (US2)

1. 렌즈를 가린 채 재생을 눌러 Session을 시작한다.
   - **기대**: 화면이 `INITIALIZING`에 머무르고 재생이 비활성이며 사유가 표시된다. 재생을 눌러도 Episode가 시작되지 않는다. (SC-003)
2. 가림을 풀어 `READY`가 되면 Episode를 시작한다.
3. 렌즈를 **0.3초 정도만** 가렸다 뗀다.
   - **기대**: Episode가 계속 진행되고 화면이 `EPISODE ACTIVE`를 유지한다.
4. 렌즈를 **2초 이상** 가린다.
   - **기대**: Episode가 자동 마감되고 화면이 `INITIALIZING`으로 바뀐다. 프리뷰와 수집은 계속된다.
5. 가림을 풀어 `READY`가 되면 Episode를 하나 더 수집하고 정상 종료한다.
6. 정지를 눌러 Session을 종료한다.

**확인**: `episodes.csv`에서 4번에서 마감된 Episode의 `outcome`이 `INVALID_TRACKING`이고, 5번 Episode는 `COMPLETED`다. `INVALID_TRACKING` Episode의 `end_timestamp_ns`가 `arcore_poses.csv`에서 `tracking_state`가 `TRACKING`이 아닌 값으로 바뀐 시각보다 약 0.5초 뒤다. Session 전체 데이터가 손실되지 않았다. (SC-002, SC-004)

### 시나리오 3 — frame index와 영상 대응 (US3, US5)

시나리오 1의 번들을 사용한다.

**확인**:

- `main_frame_timestamps.csv`의 헤더가 `frame_number,timestamp_ns,timestamp_source`로 유지된다. (FR-019)
- 첫 데이터 행의 `frame_number`가 `0`이고, 이후 행마다 1씩 증가하며 결번이 없다. (SC-005)
- `timestamp_ns`가 단조 증가하고 중복이 없다.
- 데이터 행 수와 `main_rgb.mp4`의 총 frame 수 차이가 2 이하다. (SC-009)

차이가 2를 넘으면 영상 중간의 지속적 frame drop 여부를 먼저 확인한다. 시작·종료 경계에만 몰려 있다면 수신 측의 서버 전처리 범위이며, 중간 구간에 흩어져 있다면 별도 조사가 필요하다.

### 시나리오 4 — Camera Metadata (US4)

시나리오 1의 번들을 사용한다.

**확인**:

- `metadata.json`에 `camera` 객체가 있고 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`가 모두 존재한다. (SC-006)
- `image_width` × `image_height`가 `main_rgb.mp4`의 실제 해상도와 일치한다. (SC-007)
- `cx`와 `cy`가 각각 `image_width`, `image_height`의 대략 절반 부근이다. 크게 벗어나면 잘못된 스트림의 intrinsics를 읽고 있을 가능성이 있다.
- `session_id`, `camera_streams`, `files` 세 키가 기존 형식 그대로다. (FR-026)
- 기기가 제공하지 않는 선택 필드는 키가 생략되어 있고, 0이나 임의 값으로 채워져 있지 않다. (FR-024)

### 시나리오 5 — 업로드 호환 (SC-008)

시나리오 1의 Session을 기존 경로로 EC2에 업로드한다.

**확인**: 수신 측 수정 없이 업로드가 성공하고, Session UUID 단위로 저장된다.

## 회귀 확인

이번 변경이 건드리지 않아야 하는 범위다.

- ARCore `SharedCamera` 기반 Main RGB 녹화가 정상 동작한다. 영상이 재생되고 길이가 수집 시간과 맞는다.
- Session 목록, Session 상세, 업로드 상태 화면의 동작이 그대로다.
- SAF export가 계속 동작한다.
- `arcore_poses.csv`의 헤더와 `tracking_state` 기록 형식이 변경되지 않았다.

## 완료 판정

`specs/AGENTS.md`에 따라, 위 자동 검증과 실기기 시나리오 1~5가 모두 통과하고 그 근거(실행한 명령, 테스트명, 기기와 결과)가 `tasks.md`에 기록된 경우에만 완료로 보고한다. 단위 테스트 통과만으로 실기기 동작을 검증했다고 판단하지 않는다.
