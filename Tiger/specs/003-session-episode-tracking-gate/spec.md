# Feature Specification: Session/Episode 분리와 Tracking 유효성 게이트

**Feature Branch**: `feature/session-episode-tracking-gate`

**Created**: 2026-09-14

**Status**: Draft

**Input**: 데이터 수신 측의 테스트 업로드 검토 결과에 따른 수정 요청. Session START와 Episode START 분리, ARCore Tracking 상태와 Episode 유효성 연동, `main_frame_timestamps.csv`의 `frame_number` 수정, Camera Intrinsic/Metadata 저장.

## 배경

수신 측에서 EC2에 업로드된 실제 Session 데이터를 검토한 결과, Session 단위 번들 생성·업로드 자체는 정상 동작하지만 아래 네 가지가 기존 명세 의도와 다르게 동작하고 있음이 확인되었다.

1. `START` 한 번에 Session과 첫 Episode가 동시에 시작되어, Session과 Episode의 구분이 조작 단계에서 사라져 있다.
2. ARCore Tracking이 장시간 `PAUSED`였던 구간의 Episode도 `COMPLETED`로 저장되어, 수신 측이 학습 데이터의 유효성을 판단할 수 없다.
3. `main_frame_timestamps.csv`의 `frame_number` 열에 순차 frame index가 아니라 `timestamp_ns`와 동일한 값이 들어 있어, 영상 frame과 timestamp를 대응시킬 수 없다.
4. `metadata.json`에 촬영에 사용된 Camera의 ID·해상도·Intrinsic이 없어, 서버의 Camera Geometry 처리와 ORB-SLAM3 설정에 필요한 값을 확보할 수 없다.

데이터 구조(Session 번들 안에 Episode marker, Session 전체에 걸친 연속 Camera/IMU/ARCore 기록) 자체는 의도대로 동작하고 있으므로, 파일 레이아웃과 업로드 계약은 바꾸지 않는다.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Session과 Episode를 따로 시작한다 (Priority: P1)

수집 담당자가 촬영 장소에 도착해 `Session START`를 누르면 Session이 생성되고 Camera / IMU / ARCore 수집이 시작된다. 이 시점에는 아직 어떤 demonstration도 기록 대상이 아니다. ARCore Tracking이 안정화되어 화면이 `READY`가 되면, 담당자는 실제 demonstration을 시작할 준비가 된 순간에 `Episode START`를 눌러 Episode를 시작한다. demonstration을 마치면 `Episode END`를 누르고, 화면은 다시 `READY`로 돌아간다. Session과 Camera / IMU / ARCore 수집은 끊기지 않고 계속되므로, 담당자는 자세를 고쳐 잡거나 대상 물체를 바꾼 뒤 곧바로 다음 `Episode START`를 누를 수 있다. 모든 demonstration이 끝나면 `Session END`를 눌러 Session을 마감한다.

**Why this priority**: Session과 Episode의 분리는 나머지 모든 요구사항이 올라앉는 토대다. Episode 경계가 사용자 조작으로 명확히 그어져야 Tracking 유효성을 Episode 단위로 판정할 수 있고, 준비 동작이 demonstration 구간에 섞여 들어가지 않는다.

**Independent Test**: Session을 시작해 `READY`를 확인한 뒤 Episode를 시작·종료하는 동작을 두 번 반복하고 Session을 종료한다. 결과 번들의 `episodes.csv`에 두 개의 Episode marker가 있고, 두 Episode의 시작 시각이 Session 시작 시각보다 늦으며, Camera / IMU / ARCore 기록이 Session 전체 구간에 걸쳐 끊김 없이 존재하는지로 검증한다.

**Acceptance Scenarios**:

1. **Given** 앱이 수집 화면에 있고 Session이 시작되지 않은 상태에서, **When** 담당자가 `Session START`를 누르면, **Then** Session이 생성되고 Camera / IMU / ARCore 수집이 시작되며, 화면은 `INITIALIZING` 상태를 표시하고 Episode marker는 생성되지 않는다.
2. **Given** Session이 시작되어 `INITIALIZING` 상태인 동안, **When** ARCore Tracking이 안정화되면, **Then** 화면은 `READY`로 전환되고 `Episode START`가 가능해진다.
3. **Given** 화면이 `READY`인 상태에서, **When** 담당자가 `Episode START`를 누르면, **Then** 새 Episode가 `ACTIVE`로 시작되고 그 시작 시각이 기록된다.
4. **Given** Episode가 `ACTIVE`인 상태에서, **When** 담당자가 `Episode END`를 누르면, **Then** 해당 Episode가 `COMPLETED`로 마감되고, 화면은 `READY`로 돌아가며, Session과 Camera / IMU / ARCore 수집은 중단되지 않는다.
5. **Given** 한 Session 안에서 Episode를 종료한 직후 `READY` 상태에서, **When** 담당자가 다시 `Episode START`를 누르면, **Then** 같은 Session에 속한 두 번째 Episode가 시작된다.
6. **Given** Episode가 하나도 진행 중이 아닌 상태에서, **When** 담당자가 `Session END`를 누르면, **Then** Session이 마감되고 번들이 생성된다.
7. **Given** Episode가 `ACTIVE`인 상태에서, **When** 담당자가 `Session END`를 시도하면, **Then** 진행 중인 Episode를 먼저 종료하라는 안내가 표시되고 Session은 마감되지 않는다.

---

### User Story 2 - Tracking이 불안정한 구간을 유효하지 않은 Episode로 구분한다 (Priority: P1)

수신 측이 학습 데이터로 쓸 Episode와 쓸 수 없는 Episode를 구분할 수 있어야 한다. ARCore Tracking이 안정화되기 전에는 담당자가 Episode를 시작할 수 없고, Episode 수행 중 Tracking이 짧게 흔들리는 것은 무시하되 일정 시간 이상 유실이 지속되면 해당 Episode는 유효하지 않은 것으로 마감된다. 이때 Session 전체를 버릴 필요는 없다. Tracking이 회복되어 다시 안정화되면 화면은 `READY`로 돌아가고, 담당자는 다음 Episode를 이어서 수집한다.

**Why this priority**: 현재 업로드된 데이터에서 실제로 확인된 결함이며, 이 값이 없으면 수신 측이 Session 단위로 데이터를 전량 폐기하거나 수작업으로 선별해야 한다. Episode 분리(Story 1)와 같은 릴리스에서 나가야 의미가 있다.

**Independent Test**: Session을 시작한 직후 Tracking이 아직 안정화되지 않은 동안 `Episode START`가 눌리지 않는 것을 확인한다. Episode 수행 중 카메라를 가려 Tracking을 유실시킨 뒤, 짧게 가린 경우 Episode가 계속 `ACTIVE`로 유지되고, 길게 가린 경우 해당 Episode가 유효하지 않은 것으로 마감되는지 확인한다. 이후 카메라를 정상화하면 `READY`로 돌아와 다음 Episode를 시작할 수 있는지 확인한다.

**Acceptance Scenarios**:

1. **Given** Session이 시작되었으나 ARCore Tracking이 아직 안정화되지 않은 상태에서, **When** 담당자가 `Episode START`를 시도하면, **Then** Episode는 시작되지 않고 Tracking 준비 중임이 화면에 표시된다.
2. **Given** ARCore Tracking이 정상 상태로 안정화 판정 시간 이상 유지되면, **When** 그 시점이 되면, **Then** 화면은 `READY`로 전환되고 `Episode START`가 가능해진다.
3. **Given** Episode가 `ACTIVE`인 동안, **When** ARCore Tracking이 유실되었다가 유효성 판정 시간보다 짧게 회복되면, **Then** Episode는 계속 `ACTIVE`로 유지되고 기록도 계속된다.
4. **Given** Episode가 `ACTIVE`인 동안, **When** ARCore Tracking 유실이 유효성 판정 시간 이상 지속되면, **Then** 해당 Episode는 `INVALID_TRACKING` 상태로 마감되고, Session과 Camera / IMU / ARCore 수집은 계속된다.
5. **Given** 직전 Episode가 `INVALID_TRACKING`으로 마감된 상태에서, **When** ARCore Tracking이 회복되어 안정화 판정 시간 이상 유지되면, **Then** 화면은 `READY`로 전환되고 다음 Episode를 시작할 수 있다.
6. **Given** Session 번들이 생성될 때, **When** 수신 측이 `episodes.csv`를 읽으면, **Then** 각 Episode의 상태에서 `COMPLETED`와 `INVALID_TRACKING`을 구분할 수 있다.

---

### User Story 3 - 영상 frame과 timestamp를 대응시킬 수 있다 (Priority: P1)

수신 측이 `main_frame_timestamps.csv`를 읽어 MP4의 n번째 frame이 어느 시각에 촬영되었는지 알 수 있어야 하고, 이를 통해 Video Frame / Camera Timestamp / ARCore Pose / IMU를 하나의 시간축에 정렬할 수 있어야 한다.

**Why this priority**: 현재 `frame_number`가 `timestamp_ns`와 같은 값이어서 열이 사실상 비어 있는 것과 같다. 서버 동기화 파이프라인 전체가 이 값에 의존한다.

**Independent Test**: Session을 하나 수집하고 `main_frame_timestamps.csv`를 읽어 `frame_number`가 0부터 1씩 증가하는 정수열인지, `timestamp_ns`가 단조 증가하는지 확인한다.

**Acceptance Scenarios**:

1. **Given** Session이 수집되어 번들이 생성되었을 때, **When** 수신 측이 `main_frame_timestamps.csv`를 읽으면, **Then** `frame_number`는 해당 Camera Stream의 첫 행에서 0으로 시작해 행마다 1씩 증가하는 정수다.
2. **Given** 같은 파일에서, **When** 수신 측이 `timestamp_ns`를 읽으면, **Then** 기존과 동일한 Camera Sensor 시각이 유지되고 단조 증가한다.
3. **Given** 파일 헤더가, **When** 수신 측 파서에 입력되면, **Then** 기존 헤더 `frame_number,timestamp_ns,timestamp_source`가 그대로 유지되어 파서 변경이 필요 없다.

---

### User Story 4 - 촬영에 사용된 Camera의 Intrinsic을 Session과 함께 받는다 (Priority: P2)

수신 측이 Session 번들의 `metadata.json`만 보고 그 Session이 어느 Camera로 어느 해상도에서 촬영되었는지, 그리고 그 조합에 대응하는 Intrinsic이 무엇인지 알 수 있어야 한다. 이 값으로 Camera Geometry 처리, ARCore 결과 검증, ORB-SLAM3 설정을 수행한다.

**Why this priority**: 서버 측 후속 처리에 필요하지만, 데이터가 이미 수집된 Session에 대해서는 기기별로 한 번 확보하면 소급 적용이 가능하다. Story 1~3보다 시급성이 낮다.

**Independent Test**: Session을 하나 수집하고 `metadata.json`을 읽어 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`가 모두 존재하고, `image_width`/`image_height`가 실제 MP4의 해상도와 일치하는지 확인한다.

**Acceptance Scenarios**:

1. **Given** Session이 수집되어 번들이 생성되었을 때, **When** 수신 측이 `metadata.json`을 읽으면, **Then** 실제 촬영에 사용된 Camera의 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`가 포함되어 있다.
2. **Given** `metadata.json`의 해상도 값이, **When** 같은 Session의 MP4 해상도와 비교되면, **Then** 두 값이 일치한다.
3. **Given** Intrinsic 값이, **When** 수신 측이 검토하면, **Then** 기기 일반 대표값이 아니라 위 `camera_id`와 해상도 조합에 대응하는 값이다.
4. **Given** 기기가 왜곡 계수, 초점 거리, 센서 물리 크기를 제공하는 경우, **When** `metadata.json`이 생성되면, **Then** 해당 값들도 함께 포함된다.
5. **Given** 기기가 위 부가 값 중 일부를 제공하지 않는 경우, **When** `metadata.json`이 생성되면, **Then** 해당 항목은 값이 없음이 명시되고, 임의로 계산한 값이 채워지지 않으며, Session 저장과 업로드는 정상적으로 완료된다.
6. **Given** 기존 `metadata.json`의 Session 식별자, Camera Stream 선언, 파일 manifest가, **When** 새 필드가 추가된 뒤에도, **Then** 형식과 의미가 그대로 유지되어 기존 업로드 파이프라인이 계속 동작한다.

---

### User Story 5 - Timestamp 기록 구간을 실제 녹화 구간에 맞춘다 (Priority: P3)

수신 측이 `main_frame_timestamps.csv`의 행 수와 MP4의 frame 수를 대조했을 때 두 값이 거의 일치해, 별도의 구간 정렬 없이도 대응 관계를 신뢰할 수 있어야 한다.

**Why this priority**: 수신 측이 서버 전처리에서 처리 가능하다고 명시한 항목이다. 다만 원인이 녹화 시작·종료 경계에 한정되고 수정 비용이 낮아 이번 범위에 포함한다. 영상 중간의 지속적 frame drop이 아님이 확인되었으므로 정확한 1:1 대응을 보장하지는 않는다.

**Independent Test**: Session을 하나 수집하고 `main_frame_timestamps.csv`의 데이터 행 수와 MP4의 총 frame 수를 비교한다.

**Acceptance Scenarios**:

1. **Given** Session이 수집되었을 때, **When** `main_frame_timestamps.csv`의 데이터 행 수와 MP4 frame 수를 비교하면, **Then** 영상 녹화가 실제로 진행되지 않은 구간의 Camera Timestamp는 기록되지 않는다.
2. **Given** 이 변경 이후에도, **When** 수신 측이 서버 전처리에서 공통 유효 구간을 계산하면, **Then** 기존 Temporal Crop 절차가 그대로 동작한다.

---

### Edge Cases

- Session 시작 후 ARCore Tracking이 끝내 안정화되지 않으면 어떻게 되는가: 화면은 `INITIALIZING`에 머무르고 `Episode START`는 계속 불가능하다. 담당자는 Episode 없이 `Session END`로 Session을 마감할 수 있다.
- Episode가 하나도 없는 Session을 종료하면 어떻게 되는가: Session 번들은 정상 생성되며 `episodes.csv`는 헤더만 포함한다.
- Episode가 `INVALID_TRACKING`으로 자동 마감된 직후 담당자가 `Episode END`를 누르면 어떻게 되는가: 이미 마감된 Episode를 다시 마감하지 않으며, 상태가 중복 기록되지 않는다.
- Tracking 유실이 유효성 판정 시간 이상 지속된 Episode의 종료 시각은 무엇인가: Tracking 유실이 시작된 시점부터 유효성 판정 시간이 경과한 순간이다. 담당자가 나중에 인지한 시점이 아니다.
- Episode가 진행 중이 아닌 `READY` 상태에서 Tracking이 유실되면 어떻게 되는가: 유효하지 않게 마감할 Episode가 없으므로 Episode 상태는 변하지 않고, 화면만 `READY`에서 Tracking 준비 중 상태로 돌아가 `Episode START`가 불가능해진다.
- Session 수집 중 앱이 비정상 종료되면 어떻게 되는가: 아래 FR-027~FR-030의 구제를 따른다. 다음 실행에서 staging 번들을 정상 Session으로 마감하고, 마감할 수 없는 번들만 중단 상태로 남긴다. 처음에는 "기존 중단 복구를 그대로 따른다"고 적었으나 같은 명세의 구제 요구가 그 동작을 바꿨다.
- `metadata.json`의 Intrinsic을 확보하지 못하면 Session 저장이 실패하는가: 실패하지 않는다. 확보 가능한 값만 기록하고 Session은 정상 마감된다.

## Requirements *(mandatory)*

### Functional Requirements

**Session / Episode 상태 분리**

- **FR-001**: 시스템은 Session 시작과 Episode 시작을 별개의 사용자 조작으로 제공해야 한다.
- **FR-002**: Session 시작 시 시스템은 Session을 생성하고 Camera / IMU / ARCore 수집을 시작해야 하며, Episode를 자동으로 시작해서는 안 된다.
- **FR-003**: 시스템은 수집 화면에 현재 상태를 `INITIALIZING`, `READY`, `EPISODE ACTIVE`, `FINALIZING` 중 하나로 구분해 표시해야 한다. (2026-09-21) `FINALIZING`은 상태 배지가 아니라 화면을 덮는 마감 판(`세션을 마무리하고 있습니다`)으로 표시한다.
- **FR-004**: Episode 종료 시 시스템은 Session과 Camera / IMU / ARCore 수집을 중단하지 않고 유지해야 한다.
- **FR-005**: 시스템은 하나의 Session 안에서 Episode 시작·종료를 횟수 제한 없이 반복할 수 있어야 한다.
- **FR-006**: 시스템은 Episode가 진행 중일 때 Session 종료를 허용하지 않고, 진행 중인 Episode를 먼저 종료하도록 안내해야 한다. (2026-09-29 확인) 지금은 Session을 완료한다는 종료 확인을 먼저 띄운 뒤 거부한다.
- **FR-007**: Episode 식별 정보(task, object)는 각 Episode 시작 시점의 값으로 해당 Episode에 기록되어야 한다.

**Tracking 유효성 게이트**

- **FR-008**: 시스템은 ARCore Tracking이 정상 상태로 안정화 판정 시간 이상 연속 유지된 뒤에만 `READY` 상태로 전환해야 한다.
- **FR-009**: 시스템은 `READY` 상태가 아닌 동안 Episode 시작을 허용해서는 안 되며, 그 이유를 화면에 표시해야 한다.
- **FR-010**: Episode 수행 중 Tracking 유실이 유효성 판정 시간 미만으로 지속되면 시스템은 Episode를 계속 `ACTIVE`로 유지하고 모든 수집을 계속해야 한다.
- **FR-011**: Episode 수행 중 Tracking 유실이 유효성 판정 시간 이상 지속되면 시스템은 해당 Episode를 `INVALID_TRACKING` 상태로 마감해야 한다.
- **FR-012**: `INVALID_TRACKING`으로 마감된 Episode의 종료 시각은 Tracking 유실 시작 시점에 유효성 판정 시간을 더한 값이어야 한다.
- **FR-013**: Episode가 `INVALID_TRACKING`으로 마감되어도 시스템은 Session과 Camera / IMU / ARCore 수집을 중단해서는 안 된다.
- **FR-014**: Tracking이 회복되어 안정화 판정 시간 이상 유지되면 시스템은 다시 `READY`로 전환해 다음 Episode 시작을 허용해야 한다.
- **FR-015**: 시스템은 각 Episode의 상태를 Session 번들의 Episode 기록에 저장해야 하며, 최소한 `COMPLETED`와 `INVALID_TRACKING`이 구분 가능해야 한다.
- **FR-016**: 안정화 판정 시간은 1초, 유효성 판정 시간은 0.5초를 기본값으로 한다.

**Frame Timestamp**

- **FR-017**: 시스템은 `main_frame_timestamps.csv`의 `frame_number`에 해당 Camera Stream의 0부터 시작하는 순차 frame index를 기록해야 한다.
- **FR-018**: 시스템은 `main_frame_timestamps.csv`의 `timestamp_ns`에 기존과 동일한 Camera Sensor 시각을 계속 기록해야 한다.
- **FR-019**: 시스템은 `main_frame_timestamps.csv`의 헤더와 열 구성을 변경해서는 안 된다.
- **FR-020**: 시스템은 영상 녹화가 실제로 진행 중인 구간에 대해서만 Camera Timestamp 행을 기록해야 한다.

**Camera Metadata**

- **FR-021**: 시스템은 Session 마감 시 `metadata.json`에 실제 촬영에 사용된 Camera의 `camera_id`, `image_width`, `image_height`, `fx`, `fy`, `cx`, `cy`를 기록해야 한다. (2026-09-29 확인) 다음 실행에서 구제된 Session에는 기록되지 않는다.
- **FR-022**: 기록되는 Intrinsic은 기기 일반 대표값이 아니라 해당 Session의 Camera ID 및 촬영 해상도에 대응하는 값이어야 한다.
- **FR-023**: 시스템은 기기가 제공하는 경우 `distortion_coefficients`, `focal_length_mm`, `sensor_width_mm`·`sensor_height_mm`를 함께 기록해야 한다.
- **FR-024**: 시스템은 기기가 제공하지 않는 Camera Metadata 항목에 대해 값을 임의로 계산해 채워서는 안 되며, 값이 없음을 명시해야 한다.
- **FR-025**: Camera Metadata 확보 실패는 Session 마감과 업로드를 실패시켜서는 안 된다.
- **FR-026**: 시스템은 `metadata.json`의 기존 Session 식별자, Camera Stream 선언, 파일 manifest의 형식과 의미를 유지해야 한다.

### Key Entities

- **Session**: 전체 데이터 수집 구간. Camera / IMU / ARCore 기록 전체를 소유하며, 0개 이상의 Episode를 포함한다. 촬영에 사용된 Camera의 식별자·해상도·Intrinsic을 속성으로 가진다.
- **Episode**: Session 내부의 실제 demonstration / task 수행 구간. 시작 시각, 종료 시각, task, object, 그리고 유효성을 나타내는 상태를 가진다. Session의 연속 기록 위에 놓인 marker이며 자체 미디어 파일을 갖지 않는다.
- **Tracking 상태**: Session 수집 중 ARCore Tracking의 현재 판정. Episode 시작 가능 여부와 진행 중 Episode의 유효성을 결정한다. 원시 Tracking 값은 지금과 같이 ARCore Pose 기록에 계속 남는다.
- **Camera Metadata**: Session 단위로 확보되는 Camera 식별자, 촬영 해상도, Intrinsic 및 부가 광학 값. Session 마감 시 `metadata.json`에 기록된다.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 수집 담당자가 한 Session 안에서 Session 수집을 중단하지 않고 연속된 Episode를 3회 이상 수집할 수 있다.
- **SC-002**: 수집된 Session 번들의 모든 Episode 기록에서, Tracking이 유효성 판정 시간 이상 유실된 구간을 포함한 Episode는 100% `INVALID_TRACKING`으로 표시되고, 그렇지 않은 Episode는 `COMPLETED`로 표시된다.
- **SC-003**: Tracking이 안정화되지 않은 상태에서 Episode가 시작되는 경우가 0건이다.
- **SC-004**: 하나의 Episode가 `INVALID_TRACKING`으로 마감되어도 같은 Session의 다른 Episode와 Camera / IMU / ARCore 기록은 손실되지 않는다.
- **SC-005**: 수신 측이 `main_frame_timestamps.csv`의 `frame_number`만으로 MP4 frame과 Camera Timestamp를 대응시킬 수 있으며, 해당 열은 0부터 1씩 증가하는 정수열이다.
- **SC-006**: 수신 측이 `metadata.json`만 읽어 Session의 Camera ID, 촬영 해상도, `fx`/`fy`/`cx`/`cy`를 추가 조회 없이 확보할 수 있다.
- **SC-007**: `metadata.json`에 기록된 촬영 해상도가 같은 Session의 MP4 해상도와 100% 일치한다.
- **SC-008**: 이번 변경 이후 업로드된 Session이 기존 EC2 업로드 경로에서 수정 없이 처리된다.
- **SC-009**: `main_frame_timestamps.csv` 행 수와 MP4 frame 수의 차이가 Session당 2 frame 이하다.

## 범위 밖 (Out of Scope)

아래 항목은 검토 요청에는 포함되었으나 이번 구현 범위에 넣지 않는다.

- **Ultra-wide Camera 동시 촬영**: ARCore는 논리 카메라 기준 설정만 선택할 수 있어 Ultra-wide physical camera를 Tracking Camera로 직접 지정할 수 없다. ARCore가 Main Camera를 점유한 상태에서 Ultra-wide physical camera를 별도로 여는 구성은 기기 제약에 좌우되므로, 실기기에서 timebox된 확인 작업으로만 다루고 본 기능의 구현 범위에는 넣지 않는다. 이번 범위는 Main Camera 기준으로 진행한다. 수신 측도 구현 비용이 클 경우 Main 우선 진행에 동의했다.
- **Ultra-wide Camera Intrinsic**: 위 항목에 종속된다. Ultra-wide 동시 촬영이 가능하다고 확인되기 전에는 수집 대상이 아니다.
- **ARCore SharedCamera 도입**: 이미 구현되어 동작 중이므로 이번 변경 대상이 아니다. 회귀가 발생하지 않는 것만 확인한다.
- **Session 번들의 파일 구성 및 업로드 계약 변경**: 수신 측이 현행 구조로 정상 동작함을 확인했다. `metadata.json`에 필드를 추가하는 것 외에 파일 레이아웃과 업로드 방식은 바꾸지 않는다.
- **Camera 설정값의 사용자 노출 설정 화면**: 해상도·프레임레이트 등을 쉽게 바꿀 수 있는 구조는 향후 확장 항목으로만 남긴다. 이번 범위에서는 설정 UI를 추가하지 않는다. (2026-09-16) 녹화 해상도 선택은 FR-039로 범위에 들어왔고, (2026-09-23) 초점·ISO·셔터·화이트 밸런스와 함께 카메라 설정 시트에서 고른다([002](../002-capture-control-ux/spec.md) FR-017 계열). 프레임레이트는 30으로 고정이다.
- **영상 중간 구간의 frame drop 대응**: 확인 결과 Timestamp와 MP4 frame 수의 차이는 녹화 시작·종료 경계에서 발생하며 중간 구간의 지속적 drop이 아니다. 정확한 1:1 frame correspondence를 위한 별도 인코더 처리는 수신 측 방침에 따라 서버 전처리에 맡긴다.

## Assumptions

- 수집 담당자는 앱을 사용해 본 내부 인원이며, `Session START`와 `Episode START`가 분리된 조작을 별도 교육 없이 수행할 수 있다.
- 안정화 판정 시간 1초, 유효성 판정 시간 0.5초는 기존 명세에서 합의된 값을 따른다. 수신 측이 제시한 "약 0.5초 이상"을 0.5초로 확정한다.
- Episode의 task와 object 입력 방식은 기존 흐름을 유지하되, 입력된 값이 Session 단위가 아니라 각 Episode 단위로 귀속된다. (2026-09-22) 각 Episode는 여전히 시작 시점의 값을 제 값으로 기록하며(FR-007), 같은 값을 Session 속성으로도 저장해 Episode 없이 마감된 Session도 이름을 잃지 않는다.
- Episode 상태 값의 표현은 기존 Episode 기록 형식을 그대로 사용한다. 수신 측이 `COMPLETED`와 `INVALID_TRACKING`을 같은 열에서 읽을 수 있으므로 새 열을 추가하지 않는다.
- `metadata.json`에 새 필드를 추가하는 것은 수신 측 파이프라인에 호환되는 변경이다. 기존 필드를 제거하거나 이름을 바꾸지 않는다.
- ARCore Tracking 상태의 원시 값은 지금처럼 ARCore Pose 기록에 계속 남으며, 이번 변경은 그 값을 Episode 유효성 판정에 사용하는 것을 추가한다.
- 대상 기기는 기존 검증 기기(Galaxy S10 계열)를 기준으로 하며, 실기기 검증 없이 완료로 판단하지 않는다.

## 추가 요구사항: 중단된 Session 구제

실기기 검증 중 발견된 문제를 반영한다. 수집 화면이 홈 버튼으로 중단되자 Episode 3개를 담은 55초
분량 Session이 완료 목록에서 사라졌다. 파일은 남아 있었으나 완료 처리되지 않아 사용자에게는
데이터가 사라진 것으로 보였다.

Session이 Episode 여러 개를 담는 긴 단위가 되면서 중단 한 번의 손실이 커졌다. 홈 버튼은 앱이
가로채거나 확인을 띄울 수 없으므로, 중단을 막는 대신 중단된 결과를 살린다.

- **FR-027**: 수집 화면이 사용자 조작 없이 중단되어 Session이 마감되지 못한 경우, 시스템은 그때까지
  수집된 데이터를 폐기해서는 안 된다. (2026-09-29 확인) 중단 순간 진행 중이던 Episode의 기록과 촬영
  조건·Camera 정보는 남지 않는다.
- **FR-028**: 시스템은 다음 실행 시 마감되지 못한 Session을 정상 Session으로 마감해 완료 목록에
  포함해야 한다.
- **FR-029**: 마감할 수 없을 만큼 손상된 Session만 중단 상태로 남겨야 한다. (2026-09-29 확인) 손상 판정은 필수 파일이 있고 비어 있지 않은지와 CSV 헤더만 본다. 마무리되지 않은 MP4는 가려내지 못한다.
- **FR-030**: 이전 실행에서 중단으로 표시된 Session도 이후 실행의 구제 대상에 포함되어야 한다.

**SC-010**: 수집 화면이 중단된 Session의 데이터 손실률이 0%다. 번들이 온전하면 완료 Session으로
복구된다.

## 추가 요구사항: 수집 중 라이브 프리뷰 유지

수집을 시작하면 프리뷰가 시작 직전 프레임에서 멈춘 정지 화면으로 남았다. 사용자는 수집 내내 얼어붙은
화면을 보며, 무엇이 찍히고 있는지 확인할 수 없었다. Session이 Episode 여러 개를 담는 긴 단위가
되면서 이 비용이 커졌다.

- **FR-031**: Session 수집이 진행 중인 동안에도 시스템은 수집 화면에 라이브 카메라 프리뷰를 계속
  표시해야 한다.
- **FR-032**: 프리뷰는 저장되는 영상과 같은 방향으로 보여야 하며, 보여 줄 수 있는 화각을 잘라내지
  않아야 한다. ARCore Camera 텍스처(16:9)와 녹화 해상도(4:3)의 비율 차이에서 오는 세로 화각 차이는
  ARCore Camera 구성의 속성이며 이 범위에서 해소하지 않는다. (2026-09-16) 녹화도 ARCore Camera
  텍스처(`textureSize`, 16:9)를 따르게 되어 이 차이는 사라졌다. 프리뷰와 저장 영상의 비율·화각이 같다.
- **FR-033**: 프리뷰 표시를 위한 카메라 출력 추가가 `main_frame_timestamps.csv`의 행 수와
  `frame_number` 연속성에 영향을 주어서는 안 된다.

**SC-011**: 수집 중 프리뷰가 정지하는 Session이 0건이며, `main_frame_timestamps.csv` 행 수와 MP4
frame 수의 차이가 프리뷰 없는 대조군과 같은 수준을 유지한다.

## 추가 요구사항: 수집 종료 시 안전한 정리

수집을 끝낼 때 ARCore 종료 과정에서 앱 프로세스가 죽었다. 홈 버튼 중단에서는 매번, 정상 마감에서는
간헐적으로 나타났다. Phase 11의 구제 경로로 데이터는 다음 실행에서 복구되지만, 사용자에게는 앱이 갑자기 사라지는 것으로 보였다.

- **FR-034**: 수집을 정상 마감하든 화면 중단으로 끝내든, 앱 프로세스가 비정상 종료되어서는 안 된다.
- **FR-035**: 중단 후 수집 화면으로 돌아오면 다시 수집을 시작할 수 있어야 한다.

**SC-012**: Session을 끝낼 때 프로세스가 죽는 경우가 0건이며, FR-027~FR-030의 Session 구제가 계속
동작한다.


## 추가 요구사항: 좌표계 정합 (2026-09-16 갱신)

폰을 가로로 눕혀 촬영한다. 센서가 내보내는 가로 프레임이 곧 똑바로 선 장면이므로 영상을 돌리지
않는다. 한때 시계 방향 90도 회전을 적용했으나, 가로 촬영으로 정리하면서 되돌렸다.

- **FR-036**: 시스템은 `main_rgb.mp4`에 회전을 적용하지 않아야 한다. 영상·Intrinsic·Pose가 모두
  같은 가로 기준이어야 한다.
- **FR-037**: `metadata.json`의 Camera Intrinsic은 저장된 영상과 같은 기하여야 하며, 적용한 회전
  각도(`video_rotation_degrees`, 현재 항상 `0`)를 함께 기록해 수신 측이 회전 규약이 있던 시기의
  수집분과 구분할 수 있어야 한다. (2026-09-29 확인) 값이 `0`이면 직렬화가 기본값을 생략해 키가 쓰이지
  않는다. 수신 측은 키 부재를 `0`으로 읽는다.
- **FR-038**: `arcore_poses.csv`는 ARCore 원본 기록을 유지한다.

**SC-013**: 수신 측이 `metadata.json`의 `video_rotation_degrees`만으로 회전 적용 여부를 판별할 수
있고, `main_frame_timestamps.csv`와 MP4 frame 수의 대응이 유지된다.

## 추가 요구사항: 녹화 해상도 선택

- **FR-039**: 수집자는 Session을 시작하기 전에 녹화 해상도를 `1920×1080`과 `1280×720` 중에서 골라야
  한다. 기본값은 `1920×1080`이며, 직전 선택이 다음 수집의 기본값이 된다. (2026-09-23) 고르는 곳은
  수집 정보 입력이 아니라 초점·ISO와 같은 카메라 설정이다. 셋 다 Session 내내 고정되는 촬영 조건이다.
- **FR-040**: `metadata.json`의 `image_width`·`image_height`와 Intrinsic은 고른 해상도를 따라야 하며,
  수집 화면은 촬영 전에 어느 해상도로 찍는지 보여야 한다. (2026-09-23) 카메라 설정 안에서 보여 주며,
  상단의 해상도 배지는 두지 않는다.

**SC-014**: 두 해상도 모두에서 30 FPS가 유지되고, `main_rgb.mp4`의 해상도가 `metadata.json`의
`image_width` × `image_height`와 일치한다.
