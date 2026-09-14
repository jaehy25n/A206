# 데이터 모델: Session/Episode 분리와 Tracking 유효성 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](spec.md) | **계획**: [plan.md](plan.md)

기존 모델을 최대한 보존한다. 아래에서 **신규**로 표시한 것만 추가하고, **유지**는 변경하지 않는다.

---

## 1. CaptureWorkspaceControlState (변경)

수집 화면이 표시하고 제어 가능 여부를 결정하는 상태. 명세 FR-003의 어휘에 맞춰 재정의한다.

| 값 | 의미 | 재생 | 일시 정지 | 정지 |
|---|---|---|---|---|
| `Idle` | Session 미시작 | Session START (task/object 입력 완료 시) | 불가 | 불가 |
| `Initializing` | **신규.** Session 수집 중, ARCore Tracking 미안정화 | 불가 | 불가 | Session END |
| `Ready` | Session 수집 중, Tracking 안정화 | Episode START | 불가 | Session END |
| `EpisodeActive` | Episode 진행 중 | 불가 | Episode END | 확인 후 Session END |
| `Finalizing` | Session 마감 중 | 불가 | 불가 | 불가 |

기존 값에서의 변경: `Ready` → `Idle`, `SessionActive` → `Ready`, `Initializing` 추가. 근거는 [research.md](research.md) 결정 2.

**전이**

```text
Idle ──Session START──> Initializing
Initializing ──Tracking 1초 안정화──> Ready
Initializing ──Session END──> Finalizing
Ready ──Episode START──> EpisodeActive
Ready ──Tracking 유실──> Initializing
Ready ──Session END──> Finalizing
EpisodeActive ──Episode END──> Ready
EpisodeActive ──Tracking 0.5초 유실──> Initializing   (Episode는 INVALID_TRACKING으로 마감)
EpisodeActive ──Session END(확인)──> Finalizing
Finalizing ──완료──> Idle
```

`EpisodeActive`에서 Tracking이 0.5초 미만으로 유실되었다 회복되면 상태는 `EpisodeActive`를 유지한다(FR-010).

---

## 2. TrackingState (유지)

`INITIALIZING`, `READY`, `PAUSED`, `STOPPED`. `CaptureSessionCoordinator`가 소유하며 파일에 직접 기록되지 않는다. 화면 상태 `Initializing` / `Ready`의 판단 근거다.

ARCore가 보고하는 원시 tracking 값은 지금과 동일하게 `arcore_poses.csv`의 `tracking_state` 열에 계속 기록된다. 이번 변경은 그 값을 Episode 유효성 판정에 **사용**하는 것을 추가할 뿐, 기록 형식을 바꾸지 않는다.

---

## 3. EpisodeState (유지)

`NONE`, `ACTIVE`, `COMPLETED`, `INVALID_TRACKING`과 전이 규칙이 이미 정의되어 있다. 변경 없음.

이번 작업은 `ACTIVE → INVALID_TRACKING` 전이를 **실제로 발생시키는 경로를 연결**하는 것이다. 현재 이 전이는 코드상 정의만 되어 있고 production에서 한 번도 일어나지 않는다.

---

## 4. EpisodeMarker (유지)

필드 변경 없음. `episodes.csv`의 열 구성도 그대로다.

```text
episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome
```

`outcome` 열에 `COMPLETED`와 `INVALID_TRACKING`이 모두 나타나게 되는 것이 유일한 실질 변화다. 수신 측은 새 열 없이 같은 열에서 두 값을 구분한다(FR-015).

**검증 규칙**

- `start_timestamp_ns`는 그 Episode가 속한 Session의 시작 시각보다 크다.
- `INVALID_TRACKING`인 Episode의 `end_timestamp_ns`는 Tracking 유실 시작 시각 + 0.5초다. 사용자가 인지한 시점이 아니다(FR-012).
- `task`와 `object`는 그 Episode 시작 시점의 입력 값이다(FR-007).

---

## 5. CameraMetadata (신규)

Session 단위로 1회 확보해 `metadata.json`에 기록하는 촬영 카메라 정보. 첫 유효 ARCore 프레임에서 획득한다.

| 필드 | 타입 | 필수 | 출처 |
|---|---|---|---|
| `cameraId` | String | 예 | ARCore `CameraConfig.getCameraId()` |
| `imageWidth` | Int | 예 | `CameraIntrinsics.getImageDimensions()[0]` |
| `imageHeight` | Int | 예 | `CameraIntrinsics.getImageDimensions()[1]` |
| `fx` | Float | 예 | `CameraIntrinsics.getFocalLength()[0]` |
| `fy` | Float | 예 | `CameraIntrinsics.getFocalLength()[1]` |
| `cx` | Float | 예 | `CameraIntrinsics.getPrincipalPoint()[0]` |
| `cy` | Float | 예 | `CameraIntrinsics.getPrincipalPoint()[1]` |
| `focalLengthMm` | Float? | 아니오 | Camera2 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS` |
| `sensorWidthMm` | Float? | 아니오 | Camera2 `SENSOR_INFO_PHYSICAL_SIZE` |
| `sensorHeightMm` | Float? | 아니오 | Camera2 `SENSOR_INFO_PHYSICAL_SIZE` |
| `distortionCoefficients` | List\<Float\>? | 아니오 | Camera2 `LENS_DISTORTION` |

**검증 규칙**

- `imageWidth` / `imageHeight`는 같은 Session의 `main_rgb.mp4` 해상도와 일치한다(SC-007). 현행 구현이 MediaRecorder 해상도를 ARCore `cameraConfig.imageSize`로 설정하므로 구조적으로 보장된다.
- 선택 필드는 기기가 제공하지 않으면 `null`이며, 값을 계산해 채우지 않는다(FR-024).
- 전체 객체가 `null`이어도 Session 마감과 업로드는 진행된다(FR-025).

기존 [`CameraConfig`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeModels.kt)와 필드가 일부 겹치지만, 그 타입은 `CameraCapabilityPreflight`의 Galaxy S10 프로파일 판정용이고 intrinsics(`fx`/`fy`/`cx`/`cy`)를 갖지 않는다. 별도 타입으로 둔다.

---

## 6. metadata.json (필드 추가)

기존 키는 형식과 의미를 그대로 유지하고 `camera` 객체만 추가한다. 상세 형식은 [contracts/session-metadata.md](contracts/session-metadata.md)를 따른다.

```text
session_id      유지
camera_streams  유지
files           유지 (manifest, metadata.json 자신은 제외)
camera          신규 — 위 CameraMetadata
```

`SessionBundleValidator`는 `session_id`, `camera_streams`, `files`만 읽고 알 수 없는 키를 무시하므로 이 추가로 검증이 깨지지 않는다(FR-026, SC-008).

---

## 7. main_frame_timestamps.csv (값 의미 정정)

헤더와 열 구성은 변경하지 않는다(FR-019).

```text
frame_number,timestamp_ns,timestamp_source
```

| 열 | 현재 | 변경 후 |
|---|---|---|
| `frame_number` | `timestamp_ns`와 동일한 값 | 0에서 시작해 행마다 1씩 증가하는 정수 |
| `timestamp_ns` | Camera Sensor 시각 | 변경 없음 |
| `timestamp_source` | `SENSOR_TIMESTAMP` | 변경 없음 |

**검증 규칙**

- `frame_number`는 첫 데이터 행에서 0이고 결번이 없다.
- `timestamp_ns`는 단조 증가하며 중복이 없다.
- 영상 녹화가 실제로 진행 중이지 않은 구간의 행은 기록되지 않는다(FR-020).
