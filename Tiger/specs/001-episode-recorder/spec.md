# 기능 명세: Capture Session Recorder MVP

**작성일**: 2026-09-03
**상태**: 초안  
**입력**: Capture Session 안에서 ARCore pose, main RGB, raw IMU와 Episode marker를 연속 수집하도록 MVP 요구사항을 변경한다.

## 목표

수집자는 Galaxy S10을 로봇 End-Effector에 강체 고정한 뒤, 하나의 긴 Capture Session 동안 main RGB, raw accelerometer·gyroscope·rotation vector, ARCore pose를 끊지 않고 수집한다. 수집자는 그 Session 안에서 여러 demonstration 구간을 Episode marker로 표시하고, 검증을 통과한 Session bundle 전체를 서버로 전송하거나 사용자가 선택한 Documents 위치로 내보낼 수 있다. 서버는 동일한 Session에서 ARCore direct pose와 RGB+IMU 기반 후처리 경로를 모두 시험할 수 있어야 한다.

## Clarifications

### Session 2026-09-03

- Q: Tracking loss가 0.5초 이상 지속되어 Episode가 `INVALID_TRACKING`이 되면, 앱은 그 Episode를 어떻게 종료해야 하나요? → A: 0.5초 loss 임계값에 도달한 timestamp로 자동 종료하고 `INVALID_TRACKING`을 기록한다.
- Q: Episode START를 누르기 전에 task와 object를 모두 입력하도록 필수로 둘까요? → A: task와 object가 모두 비어 있지 않을 때만 Episode START를 허용한다.
- Q: 수집 중 앱이 완전히 백그라운드로 전환되어 `onStop` 상태가 되면, Capture Session을 어떻게 처리해야 하나요? → A: `onStop`에서 writers를 안전하게 정리하고 Session을 `INTERRUPTED`로 기록한다.
- Q: MVP에서 Capture Session의 최대 길이를 어떻게 제한할까요? → A: 시간 상한은 두지 않고, 저장 가능 공간 안에서 사용자가 직접 종료한다.
- Q: MVP 서버는 Session 업로드 요청을 어떤 접근 정책으로 받을까요? → A: 현재 프로젝트에서는 HTTP endpoint를 사용하며, 앱 수준 인증은 MVP에서 사용하지 않는다. 서버가 HTTPS로 전환되면 endpoint와 Android 네트워크 설정을 함께 변경한다.
- Q: 동일한 `session_id`의 export 대상 폴더가 이미 선택된 tree URI 아래에 있으면 어떻게 처리해야 하나요? → A: 기존 export 대상 bundle을 덮어쓰고 같은 completed source로 다시 export한다.
- Q: 앱을 다시 연 뒤 export를 재시도할 때 마지막으로 선택한 Documents tree를 자동으로 다시 사용할까요? → A: 마지막 선택 tree의 접근 권한을 유지해 재사용하고, 권한을 잃었을 때만 다시 선택한다.
- Q: export 대상은 Android의 Documents 위치로 제한할까요, 아니면 사용자가 SAF에서 선택한 모든 tree URI를 허용할까요? → A: Documents 위치에서 선택을 시작하되 사용자가 명시적으로 선택한 모든 SAF tree URI를 허용한다.
- Q: 기존 export를 덮어쓰는 중 실패해 부분 파일이 남으면, 앱이 그 대상 폴더를 자동 정리할까요? → A: 부분 파일을 자동 삭제하지 않고 `EXPORT_FAILED`로 표시하며, 다음 재시도에서 같은 대상 폴더를 다시 덮어쓴다.
- Q: 대상 bundle의 정확한 파일 집합과 부분 export 보존을 함께 보장하려면 어떤 publish 정책을 사용할까요? → A: 선택 tree 안의 새 임시 directory에 복사·검증한 뒤에만 최종 `<session_id>` directory를 덮어쓴다. 실패한 임시 directory는 자동 삭제하지 않고, 재시도는 새 임시 directory에서 시작한다.

## 사용자 시나리오 및 테스트 *(필수)*

### 사용자 스토리 1 - 연속 Capture Session 수집 (우선순위: P1)

수집자는 `DATA COLLECTION START`를 눌러 새 Session을 시작하고, ARCore tracking이 안정화된 뒤 다수의 Episode를 기록한다. Session이 끝날 때까지 RGB, raw IMU, ARCore pose의 수집은 중단되지 않는다.

**우선순위 근거**: 연속적인 센서·영상 timeline이 MVP의 핵심 데이터 가치다.

**독립 테스트**: 지원 대상 기기에서 약 2분 Session을 시작해 tracking 안정화 뒤 두 Episode를 END하고, 두 marker 사이의 idle 구간을 포함하는 Session raw bundle을 확인한다.

**인수 시나리오**:

1. **Given** IDLE 상태, **When** 수집자가 `DATA COLLECTION START`를 누르면, **Then** 새 UUID `session_id`와 staging Session directory가 만들어지고 raw stream 수집이 시작된다.
2. **Given** Session이 시작됐으나 ARCore tracking이 1초 연속 안정화되지 않았을 때, **When** 수집자가 Episode를 시작하려 하면, **Then** Episode START는 사용할 수 없다.
3. **Given** tracking이 1초 연속 안정화된 READY 상태와 비어 있지 않은 task·object 입력, **When** 수집자가 Episode START·END를 두 번 수행하면, **Then** 각 Episode의 UUID, task, object, outcome 및 monotonic start/end timestamp가 기록되고 raw stream은 계속 유지된다.
4. **Given** Episode 사이에 reposition 또는 idle 시간이 있을 때, **When** 다음 Episode를 시작하면, **Then** 두 marker 사이 시간도 Session raw 데이터에 남는다.

---

### 사용자 스토리 2 - Tracking 저하와 치명적 오류 처리 (우선순위: P1)

수집자는 짧은 tracking 저하 때문에 전체 Session을 잃지 않지만, 데이터 스트림을 보존할 수 없는 오류는 명확히 구분할 수 있다.

**우선순위 근거**: 불완전 데이터를 학습 후보로 오인하지 않으면서 가능한 raw trajectory를 보존해야 한다.

**독립 테스트**: Episode 중 0.5초 이상 tracking loss와 Camera/IMU writer 치명 오류를 각각 재현해 Episode와 Session 상태 전이를 확인한다.

**인수 시나리오**:

1. **Given** ACTIVE Episode 중 짧은 tracking loss, **When** tracking이 0.5초 미만으로 회복하면, **Then** raw recording은 계속되고 Episode는 ACTIVE로 유지된다.
2. **Given** ACTIVE Episode 중 tracking loss가 0.5초 이상 지속될 때, **When** 임계값에 도달하면, **Then** 해당 timestamp를 end timestamp로 하여 Episode를 자동 종료하고 `INVALID_TRACKING`을 기록하며 raw recording은 계속한다.
3. **Given** Camera, video writer, IMU writer 또는 저장 공간의 치명 오류, **When** 원시 스트림 보존이 불가능해지면, **Then** Session은 `INTERRUPTED`로 남고 completed dataset 후보가 되지 않는다.
4. **Given** tracking loss 후, **When** tracking이 다시 1초 연속 안정화되면, **Then** 새 Episode를 시작할 수 있는 READY 상태로 복귀한다.
5. **Given** recording 중인 Session, **When** 앱이 완전히 백그라운드로 전환되어 `onStop`이 발생하면, **Then** writers를 안전하게 정리하고 Session을 `INTERRUPTED`로 기록한다.

---

### 사용자 스토리 3 - Session 완료 및 사용자 선택 export (우선순위: P1)

수집자는 `DATA COLLECTION END`로 Session을 한 번만 finalize하고, 완결된 Session bundle을 로컬에서 확인한 뒤 Android Storage Access Framework로 선택한 Documents tree 아래로 export한다. 앱을 삭제해도 bundle을 보존하려면 완료 bundle을 명시적으로 export해야 한다.

**우선순위 근거**: Session 단위 데이터 무결성과 idempotent 전송이 후속 분석의 기본이다.

**독립 테스트**: main-only Session을 정상 종료해 필수 파일, 마지막 commit marker, `LOCAL_ONLY` 상태를 확인하고, 사용자가 선택한 tree URI 아래에 기본 제안 경로로 export된 bundle을 확인한다. 실패한 export를 다시 시도해 원본이 보존되는지도 확인한다.

**인수 시나리오**:

1. **Given** READY 상태이고 열린 Episode가 없을 때, **When** 수집자가 `DATA COLLECTION END`를 누르면, **Then** writers를 finalize하고 필수 파일·크기·무결성을 확인한 뒤 metadata를 마지막 commit marker로 기록한다.
2. **Given** 검증된 completed Session, **When** 수집자가 export를 선택하면, **Then** 시스템은 `Documents/TigerCapture/<session_id>/`를 기본 제안하고 사용자가 선택한 tree URI 하위에 completed bundle 전체를 쓴다.
3. **Given** export 중 사용자가 취소하거나 대상 쓰기·검증이 실패했을 때, **When** 수집자가 재시도를 선택하면, **Then** staging 및 completed 원본은 삭제되지 않고 같은 completed bundle으로 export를 다시 시도할 수 있다.
4. **Given** 검증된 completed Session, **When** 수집자가 업로드하면, **Then** Session 전체가 `POST /sessions`로 전송되고 `session_id`가 idempotency key로 사용된다.
5. **Given** 업로드가 실패했을 때, **When** 수집자가 재전송을 선택하면, **Then** 로컬 원본은 유지되고 같은 `session_id`로 전체 bundle을 다시 보낸다.

**Galaxy S10 검증 시나리오**: Galaxy S10에서 정상 finalize된 main-only Session을 만든 뒤 Documents 위치에서 tree 선택을 시작하고 `TigerCapture/<session_id>/` 기본 제안으로 export한다. 선택한 tree가 Documents 밖인 경우도 export가 tree URI 하위에만 기록되는지 확인한다. 이어서 tree 선택 취소, 권한 상실 또는 대상 공간 부족을 각각 재현해 export 실패 표시·원본 보존·재시도를 확인한다. 이 시나리오는 실제 기기에서 수행하며 단위 테스트로 대체하지 않는다.

---

### 사용자 스토리 4 - 선택적 Ultra-wide 검증 (우선순위: P2)

수집자는 main-only baseline을 우선 사용하고, 실기기 probe가 안정적으로 성공한 경우에만 같은 Session에 Ultra-wide stream을 포함한다.

**우선순위 근거**: 넓은 관찰 영상은 유용하지만 main RGB·IMU·ARCore 연속성보다 우선할 수 없다.

**독립 테스트**: tracking 상태에서 낮은 해상도·프레임률의 Ultra-wide stream을 1~2분 수집해 main recording과 tracking을 함께 확인한다.

**인수 시나리오**:

1. **Given** main-only baseline이 1~2분 안정적으로 동작할 때, **When** Ultra-wide probe를 수행하면, **Then** 기기 camera topology와 ARCore가 실제 사용하는 camera 식별 정보를 기록한다.
2. **Given** probe가 main recording, Ultra-wide frame, tracking을 모두 안정적으로 유지할 때, **When** 결과를 확정하면, **Then** 이후 Session metadata는 Ultra-wide 사용을 선언하고 관련 파일을 포함한다.
3. **Given** Ultra-wide open 또는 동시 수집이 main recording·tracking을 방해할 때, **When** 10~30분 이내에 실패가 확인되면, **Then** `UW_UNSUPPORTED_FOR_MVP`로 결정하고 main-only MVP를 계속한다.

### 예외 상황

- Camera timestamp source가 Android monotonic timeline과 비교 가능하다고 사전 확인되지 않으면 Session을 시작하지 않는다.
- ACTIVE Episode가 남아 있을 때 Session 종료는 Episode END 또는 CANCEL을 먼저 요구한다.
- task 또는 object가 비어 있으면 Episode START는 비활성화한다.
- `INVALID_TRACKING` Episode는 Session raw stream에는 남지만 학습 후보에서 제외한다. `CANCELLED` 상태는 사용하지 않는다.
- `onStop`, 앱 재시작 또는 비정상 종료 뒤 staging Session은 `INTERRUPTED`로 식별되며 completed 목록에 공개되지 않는다.
- export 대상 tree 선택이 취소되거나 쓰기 권한을 잃으면 export는 실패 상태가 되며, completed 원본과 staging 원본을 삭제하거나 변경하지 않는다.
- 앱 재시작 뒤에도 마지막으로 선택한 tree URI의 접근 권한이 유효하면 export 재시도에 재사용하며, 유효하지 않으면 사용자가 tree를 다시 선택해야 한다.
- export 대상에 일부 파일만 기록됐거나 manifest·metadata·CSV header 검증에 실패하면 bundle을 성공으로 표시해서는 안 되며, 사용자는 같은 Session으로 재시도할 수 있다.
- export는 선택된 tree 안의 새 임시 directory에 raw file을 먼저 쓰고 `metadata.json`을 마지막으로 쓴 뒤 검증해야 한다. 검증된 임시 bundle만 최종 `<session_id>` directory를 덮어쓸 수 있으며, 실패한 임시 directory는 자동 삭제하지 않는다. 다음 재시도는 새 임시 directory에서 시작한다.
- 사용자가 선택하지 않은 공용 Documents 경로에는 쓰지 않으며, 앱은 broad storage permission을 요청하지 않는다.
- Ultra-wide가 metadata 선언과 실제 파일 구성 중 하나와만 일치하면 Session 검증 또는 업로드를 거부한다.
- Capture Session에는 인위적인 시간 상한이 없으며, 저장 공간 부족은 Session interruption으로 처리한다.

## 요구사항 *(필수)*

### 기능 요구사항

- **FR-001**: 시스템은 `DATA COLLECTION START`마다 새 UUID `session_id`를 만들고, 사람용 display number와 분리된 Session directory를 생성해야 한다.
- **FR-002**: 시스템은 한 Session에서 main RGB, accelerometer, gyroscope, rotation vector, ARCore pose를 Session 시작부터 종료까지 연속 저장해야 하며, Episode event가 이 수집을 시작·정지해서는 안 된다.
- **FR-003**: 시스템은 ARCore tracking이 약 1초 연속 안정화될 때까지 `INITIALIZING`을 표시하고 Episode START를 비활성화해야 한다. 별도 수동 IMU calibration은 제공하지 않는다.
- **FR-004**: 시스템은 tracking이 READY 상태이고 task와 object가 모두 비어 있지 않을 때만 Episode START를 허용해야 하며, START 시 새 UUID `episode_id`, monotonic start timestamp와 두 metadata의 snapshot을 기록해야 한다.
- **FR-005**: 시스템은 Episode 종료 시 end timestamp와 `COMPLETED` outcome을 기록해야 하며, `CANCELLED` outcome이나 Episode 취소 조작을 제공해서는 안 된다. 각 Episode가 별도 raw directory를 소유하게 해서도 안 된다.
- **FR-006**: 시스템은 pose row마다 Android camera timestamp, pose translation·rotation, tracking state 및 tracking failure reason을 기록해야 한다.
- **FR-007**: 시스템은 Episode 중 tracking loss가 약 0.5초 이상 지속되면 0.5초 임계값 도달 timestamp를 end timestamp로 하여 해당 Episode를 자동 종료하고 `INVALID_TRACKING`으로 기록해야 한다. 짧은 `PAUSED`와 `INVALID_TRACKING`은 Session raw recording을 중단해서는 안 된다.
- **FR-008**: 시스템은 Camera, video writer, IMU writer 또는 저장 공간의 치명 오류가 raw stream을 깨뜨릴 때, 또는 recording 중 앱이 `onStop` 상태가 될 때 writers를 안전하게 정리하고 Session을 `INTERRUPTED`로 표시하여 정상 dataset 후보에서 제외해야 한다.
- **FR-009**: 시스템은 Episode/App event의 monotonic timestamp, raw IMU timestamp, Camera frame timestamp, ARCore Android camera timestamp를 동일 phone monotonic timeline에서 비교 가능하게 보존해야 한다. 지원 대상에서 Camera timestamp source가 `REALTIME`임을 사전 확인할 수 없으면 정상 Session을 시작해서는 안 된다.
- **FR-010**: 시스템은 각 main camera frame의 timestamp를 별도 기록해야 하며, 영상 파일 시간만을 Session timeline의 기준으로 사용해서는 안 된다.
- **FR-011**: 시스템은 main physical camera와 ARCore tracking을 일관되게 사용하고, 해상도·FPS·zoom·stabilization 같은 촬영 설정이 Session 중 변경되지 않도록 해야 한다.
- **FR-012**: 시스템은 Session metadata에 session ID, device model, main camera 및 ARCore camera 식별, 촬영 설정, stream 사용 여부, timebase 검증 결과 및 기기에서 제공되는 intrinsic·distortion·focal/sensor 정보를 기록해야 한다. 제공되지 않는 값은 임의로 생성하지 않는다.
- **FR-013**: 시스템은 모든 raw stream을 일반 파일 관리자가 직접 수정·삭제할 수 없는 앱 전용 내부 저장 영역 `capture/staging/<session_id>/`에 기록해야 한다. Session 종료 뒤 video·sensor·pose·marker writer를 finalize한 후 필수 파일의 존재와 크기를 확인하고, SHA-256 manifest를 기록한 뒤 `metadata.json`을 마지막 commit marker로 작성해야 한다. 이 검증을 통과한 Session만 completed로 공개해야 한다.
- **FR-013a**: 시스템은 Capture Session에 인위적인 최대 시간을 적용해서는 안 되며, 수집자가 `DATA COLLECTION END`로 종료하게 해야 한다. 시작 전 저장 가능 공간을 확인하고 수집 중 공간 부족으로 raw stream을 보존할 수 없으면 Session을 `INTERRUPTED`로 처리해야 한다.
- **FR-014**: main-only completed Session은 metadata, main RGB video, main frame timestamps, accelerometer, gyroscope, rotation vector, ARCore poses, episodes marker 파일을 모두 포함해야 한다. Ultra-wide 지원 Session은 Ultra-wide video와 frame timestamp 파일도 추가해야 한다.
- **FR-015**: 시스템은 Session·Camera·IMU·ARCore·Episode 상태와 tracking loss 또는 치명 오류를 수집자에게 즉시 표시해야 한다. `INITIALIZING`, `READY`, `ACTIVE`, finalization 및 upload 상태에 맞게 버튼을 활성화해야 한다.
- **FR-016**: 시스템은 completed Session 전체만 업로드하고 `POST /sessions`와 `Idempotency-Key = session_id`를 사용해야 한다. metadata가 선언한 stream과 multipart 파일 구성은 정확히 일치해야 한다.
- **FR-016a**: 시스템은 현재 프로젝트의 HTTP endpoint로 Session을 전송할 수 있도록 cleartext traffic을 허용해야 하며, MVP에서는 앱 또는 사용자 인증 정보를 전송·저장하지 않아야 한다. 서버가 HTTPS로 전환되면 endpoint와 Android 네트워크 설정을 함께 변경한다.
- **FR-017**: 시스템은 업로드 성공 전 또는 실패 후에도 local Session 원본을 보존하고 수동 재전송을 허용해야 한다. 자동 삭제, background upload, resumable upload는 MVP 범위 밖이다.
- **FR-018**: 시스템은 Galaxy S10에서 main+Ultra-wide 동시 수집을 짧은 실기기 probe로만 평가해야 한다. probe가 실패하면 main-only Session으로 진행해야 하며, Ultra-wide를 MVP 필수 조건으로 만들면 안 된다.
- **FR-019**: 시스템은 finalize 검증을 통과한 completed Session에만 export를 허용해야 하며, export 전과 대상 기록 후에 필수 파일 구성, CSV header, SHA-256 manifest 및 metadata 선언의 일치를 검증해야 한다.
- **FR-020**: 시스템은 사용자가 Android Storage Access Framework로 선택한 Documents tree URI 하위에만 export해야 한다. 기본 제안 경로는 `Documents/TigerCapture/<session_id>/`이되 실제 최종 위치는 사용자가 선택한 tree URI 하위여야 한다.
- **FR-021**: 시스템은 export 실패·취소·대상 검증 실패 때 staging 또는 completed 원본을 삭제·변경하지 않고, 사용자에게 같은 completed bundle의 수동 재시도 수단과 실패 원인을 제공해야 한다.
- **FR-022**: 시스템은 공용 Documents 저장소에 직접 쓰기 위한 broad storage permission을 요청하거나 사용해서는 안 된다. 앱 삭제 전에 bundle을 보존하려면 사용자가 완료 bundle을 명시적으로 export해야 한다.
- **FR-023**: 시스템은 export 상태를 `NOT_EXPORTED → EXPORTING → EXPORTED` 또는 `EXPORTING → EXPORT_FAILED`로 표시해야 하며, `EXPORT_FAILED`에서는 같은 completed bundle을 변경하지 않고 `EXPORTING`으로 재시도할 수 있게 해야 한다. export 상태는 recording 및 upload 상태를 변경해서는 안 된다.
- **FR-024**: 시스템은 선택된 tree URI 안의 새 임시 directory에 immutable completed source를 복사하고, 필수 파일·CSV header·SHA-256 manifest·metadata 선언을 검증한 뒤에만 같은 `session_id`의 최종 export directory를 덮어써야 한다. 대상 덮어쓰기 또는 publish 실패로 남은 임시 directory는 자동 삭제하지 않고 `EXPORT_FAILED`로 표시하며, staging 및 completed 원본을 변경해서는 안 된다. 재시도는 기존 임시 directory를 재개하지 않고 새 임시 directory에서 시작해야 한다.
- **FR-025**: 시스템은 사용자가 선택한 tree URI의 접근 권한을 앱 재시작 뒤에도 export 재시도에 사용할 수 있도록 유지해야 하며, 권한이 유효하지 않거나 철회되면 export를 `EXPORT_FAILED`로 표시하고 tree를 다시 선택하게 해야 한다.
- **FR-026**: 시스템은 Documents 위치에서 SAF tree 선택을 시작하되, 사용자가 명시적으로 선택한 모든 접근 가능한 tree URI를 export 대상으로 허용해야 한다. 선택된 tree가 Documents 밖이어도 실제 export는 해당 tree URI 하위로 제한해야 한다.
- **FR-027**: 시스템은 tree URI가 create, write, enumerate 및 publish에 필요한 rename/delete document operation을 제공할 때만 export를 시작해야 한다. 필요한 operation을 지원하지 않거나 권한이 유효하지 않으면 source를 변경하지 않고 `EXPORT_FAILED`로 표시하고 사용자가 다른 tree를 선택하게 해야 한다.

### 핵심 엔터티

- **Capture Session**: UUID `session_id`로 식별되는 연속 raw 수집·저장·업로드의 단위. recording state, upload state, bundle path와 설정 metadata를 가진다.
- **Episode Marker**: Session에 속하는 timestamp range와 UUID `episode_id`, task, object, outcome을 가진다. raw file을 소유하지 않는다.
- **Session Raw Stream**: main RGB, frame timestamp, IMU, ARCore pose 및 선택적 Ultra-wide stream으로 구성된 연속 timeline이다.
- **Session Metadata**: device, camera·ARCore 설정, stream 선언, timestamp comparability, file integrity 정보를 설명하는 마지막 commit marker다.
- **Session Export**: 검증된 completed bundle을 사용자가 선택한 Documents tree URI 하위로 복사하는 사용자의 명시적 보존 행위다. export 상태와 실패 원인을 가진다.
- **Ultra-wide Probe Result**: `UW_SUPPORTED` 또는 `UW_UNSUPPORTED_FOR_MVP`로 main-only baseline에 영향을 주지 않는 기기별 평가 결과다.

## 성공 기준 *(필수)*

### 측정 가능한 결과

- **SC-001**: 수집자는 하나의 Session에서 raw stream을 중단하지 않고 최소 두 개의 Episode marker와 그 사이 idle 구간을 기록할 수 있다.
- **SC-002**: Episode START는 tracking이 1초 연속 안정화되기 전에는 100% 비활성화되고, 안정화 후에는 활성화된다.
- **SC-003**: 0.5초 이상 tracking loss가 발생한 모든 ACTIVE Episode는 `INVALID_TRACKING`으로 식별되며 Session 자체는 raw stream이 정상인 한 계속 수집된다.
- **SC-004**: 정상 완료된 main-only Session마다 필수 여덟 파일과 마지막 metadata commit marker를 가진 completed bundle이 정확히 한 개 생성된다.
- **SC-005**: completed Session의 main camera frame, raw IMU sample, ARCore pose, Episode marker는 모두 나노초 timestamp를 통해 하나의 Session timeline에서 비교할 수 있다.
- **SC-006**: 업로드 실패 또는 duplicate 응답 후에도 Session 원본은 유지되며, 수집자는 같은 Session 전체를 다시 전송할 수 있다.
- **SC-007**: Ultra-wide probe는 10~30분 내에 supported 또는 unsupported 결론을 내고, unsupported일 때도 main-only capture 흐름은 사용할 수 있다.
- **SC-008**: 수집자는 저장 가능 공간이 유지되는 한 인위적인 시간 제한 없이 Session을 계속 기록하고 원하는 시점에 종료할 수 있다.
- **SC-009**: 정상 finalize된 completed Session은 사용자가 선택한 Documents tree URI 하위로 export할 때 필수 파일, 모든 CSV header, SHA-256 manifest 및 metadata 선언 검증을 모두 통과한 경우에만 성공으로 표시된다.
- **SC-010**: export가 실패하거나 취소된 경우 100%의 사례에서 staging 및 completed 원본이 보존되고, 사용자는 같은 Session을 다시 export할 수 있다.
- **SC-011**: 같은 `session_id`의 기존 export directory가 있을 때도 사용자는 검증된 임시 bundle을 통해 같은 tree URI 아래에서 bundle을 덮어써 다시 export할 수 있으며, 실패 시 source bundle은 보존되고 실패한 임시 directory는 성공 bundle으로 표시되지 않는다.

## 가정 및 범위

- 지원 대상은 Galaxy S10이며 main-only baseline은 30 FPS로 검증한다. 30 FPS는 기기 상한이기도 하다. 실기기에서 후면 Camera가 알리는 AE target FPS 범위의 최댓값이 30이고, ARCore가 제공하는 Camera config 후보도 모두 30 FPS였다. 60·120·240은 `CameraConstrainedHighSpeedCaptureSession` 전용 stream으로만 조회된다. 이 경로를 ARCore 공유 카메라와 함께 쓸 수 있는지는 시도해 보지 않았다.
- 녹화 해상도는 1920×1080이며 ARCore GPU 텍스처 stream 기준이다. ARCore가 추적에 쓰는 CPU 이미지 stream은 640×480으로 남는다. 둘을 함께 키우면 대상 기기가 stream 조합을 거부한다. 자세한 근거는 `specs/003-session-episode-tracking-gate/contracts/capture-state-machine.md`에 있다.
- ARCore pose의 canonical join key는 Android camera timestamp이며, 다른 ARCore frame timestamp는 선택적 진단 정보일 뿐이다.
- 서버의 ORB-SLAM3 처리, camera-to-end-effector 외부 보정, dataset 학습 선정 및 server-side video/frame correspondence 최종 검증은 범위 밖이다.
- 서버는 HTTP Session upload endpoint와 Session idempotency receipt를 제공한다. 모바일 앱은 서버 내부 저장·후처리 상태를 조회하지 않는다.
- Session upload endpoint는 신뢰된 폐쇄망에서 운영되며, 앱 수준 인증은 별도 보안 기능으로 유예한다.
- Session 또는 Episode 자동 복구, upload retry queue, background upload, 업로드 뒤 자동 삭제, 고해상도 Ultra-wide, 복잡한 tracking recovery UI는 MVP 범위 밖이다.
- export는 사용자가 명시적으로 시작하는 completed bundle 복사이며, 자동 export·앱 삭제 뒤 staging 보존·공용 저장소 직접 쓰기는 MVP 범위 밖이다.
