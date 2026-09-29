# 조사 결과: Session/Episode 분리와 Tracking 유효성 게이트

**작성일**: 2026-09-14 | **명세**: [spec.md](spec.md) | **계획**: [plan.md](plan.md)

## 출발점: 결함의 성격

코드를 확인한 결과, 이번 요청의 상당 부분은 신규 구현이 아니라 **이미 구현된 도메인 로직을 production 호출 경로에 연결하는 작업**이다. 이 사실이 이후 모든 결정의 전제가 된다.

- [`CaptureSessionCoordinator`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt)에 안정화 게이트(`READY_GATE_NS` = 1초), 유실 판정(`TRACKING_LOSS_NS` = 0.5초), `INVALID_TRACKING` 마감, `startEpisode`의 `READY` 선행 조건이 이미 정확히 구현되어 있고 단위 테스트도 있다. 그러나 이 클래스는 테스트에서만 인스턴스화되며 `MainActivity`도 `AndroidCaptureRuntime`도 참조하지 않는다.
- [`FrameTimestampWriter`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/capture/CaptureSessionCoordinator.kt)는 `append(frameNumber, timestampNs)` 시그니처로 올바른 형식을 쓰지만 역시 미사용이다. 실제 기록은 `AndroidCaptureRuntime`이 `"$timestampNs,$timestampNs,SENSOR_TIMESTAMP"`를 직접 써서 수행한다.
- `EpisodeState.INVALID_TRACKING`과 `RecordingState`의 전이 규칙도 이미 정의되어 있다.

`specs/AGENTS.md`의 완료 판정 규칙이 말하는 전형적인 `미연결` 사례다. 따라서 이번 구현은 새 상태 기계를 설계하는 것이 아니라, 기존 상태 기계를 실제 런타임의 유일한 판단 주체로 승격시키는 방향으로 진행한다.

---

## 결정 1: Tracking 신호를 Coordinator에 전달하는 경로

**결정**: ARCore pose 수집 스레드가 Tracking 여부를 `StateFlow<Boolean>`로 노출하고, 수집 화면이 **100ms 주기 ticker**로 그 최신 값을 `CaptureSessionCoordinator.onTracking()`에 반복 전달한다. Coordinator 호출은 전부 main 스레드에서 이루어진다.

(구현) 노출하는 값은 Tracking 여부와 그 pose의 카메라 시각을 함께 담은 `StateFlow<TrackingSample>`이다. 기록용 유실 시작 시각을 `arcore_poses.csv`와 맞추기 위해서이며, 근거는 [계약](contracts/capture-state-machine.md)의 "유실 시작 시각의 기준"에 있다.

**근거**: `onTracking()`은 호출 시점의 경과 시간을 기준으로 1초 안정화와 0.5초 유실을 판정한다. 즉 **상태가 변하지 않아도 계속 호출되어야** 마감 시점이 도래한다. Tracking 유실이 지속될 때 값이 `false`로 고정되므로, 값 변화에만 반응하는 구독은 0.5초 마감을 영영 발화시키지 못한다. 100ms 주기는 두 임계값(500ms, 1000ms)보다 충분히 촘촘해 판정 오차가 임계값의 20% 이내이며, 수집 중에만 도는 경량 루프라 비용이 무시할 수준이다.

**검토한 대안**:
- *pose 스레드에서 직접 `onTracking()` 호출*: Coordinator가 스레드 안전하지 않고, 화면 상태가 main 스레드에 있어 경쟁 조건이 생긴다. 기각.
- *모든 pose 업데이트를 Channel로 전달*: 마감 발화는 보장되지만 판정 주기가 ARCore 프레임 도착에 종속된다. `session.update()`가 지연되면 마감도 지연된다. ticker가 더 견고하다. 기각.
- *StateFlow 구독만 사용*: 위 근거대로 0.5초 마감이 발화하지 않는다. 기각.

---

## 결정 2: 수집 화면 상태 이름을 명세 어휘에 맞춘다

**결정**: [`CaptureWorkspaceControlState`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/ui/capture/CaptureControlPolicy.kt)를 `Idle`, `Initializing`, `Ready`, `EpisodeActive`, `Finalizing` 다섯 값으로 재정의한다.

| 기존 | 신규 | 의미 |
|---|---|---|
| `Ready` | `Idle` | Session 미시작. 재생 = Session START |
| — | `Initializing` | Session 수집 중, Tracking 미안정화. 재생 불가 |
| `SessionActive` | `Ready` | Session 수집 중, Tracking 안정화. 재생 = Episode START |
| `EpisodeActive` | `EpisodeActive` | Episode 진행 중 |
| `Finalizing` | `Finalizing` | Session 마감 중 |

**근거**: 기존 `Ready`는 "Session이 아직 시작되지 않음"을 뜻해 명세와 수신 측이 쓰는 `READY`(= Episode 시작 가능)와 정반대다. FR-003이 화면에 `INITIALIZING` / `READY` / `EPISODE ACTIVE` / `FINALIZING`을 구분해 표시하도록 요구하므로, 이 상태에서 이름을 그대로 두면 코드와 명세가 영구적으로 어긋난다. 영향 범위는 enum 1개, `CaptureControlPolicy`, `MainActivity`의 상태 계산, 단위 테스트 1개, Compose 테스트 1개로 한정된다.

**검토한 대안**: *`Initializing`만 추가하고 기존 이름 유지*. 변경량은 작지만 `Ready`가 두 문서에서 반대 의미를 갖게 되어, 이후 작업자가 매번 오해할 비용이 크다. 기각.

---

## 결정 3: Session START와 Episode START의 조작 분리 지점

**결정**: 현재 재생 버튼의 분기(`if (!collecting) Session START else Episode START`)를 유지하되, `Idle`과 `Ready` 두 상태에서만 재생이 활성화되고 `Initializing`에서는 비활성화된다. 버튼 자체를 둘로 늘리지 않는다.

**근거**: 화면은 전체 화면 프리뷰 위의 하단 중앙 오버레이 3버튼 구성이며, 002에서 확정된 UX다. 상태별로 같은 버튼이 다른 의미를 갖는 구성은 이미 문자열 리소스에 반영되어 있다(`capture_control_start` = "수집 시작", `capture_control_resume` = "작업 구간 시작"). 버튼을 추가하면 002의 레이아웃 결정을 되돌리게 되고, 명세는 조작의 **분리**를 요구할 뿐 버튼 개수를 지정하지 않는다. `Initializing`에서 재생이 비활성화되고 그 이유가 표시되면 FR-009가 충족된다.

**검토한 대안**: *Session START와 Episode START를 별개 버튼으로 배치*. 명세 의도에는 더 직설적이지만 002에서 확정한 3버튼 오버레이를 재설계해야 하고, 두 버튼 중 하나는 항상 비활성이라 화면만 복잡해진다. 기각.

(2026-09-23) 분기는 `state.phase == Idle`이면 Session START, 아니면 Episode START다. 제어는 화면 우측 가장자리에 세로로 쌓이고 상태마다 한두 개만 보이며(002 FR-004), `capture_control_start`는 "세션 시작"이다. 재생 버튼 하나가 상태에 따라 두 조작을 맡는 결정은 그대로다.

---

## 결정 4: task / object 입력 시점

**결정**: 수집 화면 진입 시 1회 입력받는 기존 모달을 유지하고, 각 Episode는 **시작 시점의 입력 값을 자신의 값으로 복사**해 기록한다.

**근거**: FR-007은 task/object가 각 Episode에 귀속될 것을 요구하며, 입력을 Episode마다 다시 받으라고 요구하지 않는다. 현재 코드도 이미 Episode 생성 시점에 값을 복사한다. 한 Session 안에서 대상을 바꾸려면 사용자가 모달을 다시 열 수 있어야 하지만, 이는 별도의 UX 요구이며 이번 명세에 없다.

**검토한 대안**: *Episode START마다 모달 표시*. FR-007을 더 강하게 만족시키지만 반복 수집의 조작 비용이 커진다. 명세 범위를 넘어서므로 기각.

---

## 결정 5: `frame_number` 생성과 중복 방지

**결정**: 카메라 핸들러 스레드에서만 접근하는 카운터를 두고, CSV에 실제로 기록한 행에 대해서만 0부터 증가시킨다. 기존의 `timestampNs != lastFrameTimestampNs` 중복 제거를 반드시 유지한다. (구현) 카운터와 중복 제거는 `FrameTimestampWriter.record()`가 들며, 변수 이름은 `lastTimestampNs`다.

**근거**: 현재 코드는 **동일한 `CaptureCallback` 인스턴스를 두 번 등록**한다 — `setRepeatingRequest(request, captureCallback, handler)`와 `sharedCamera.setCaptureCallback(captureCallback, handler)`. (2026-09-23) 지금은 `ArSharedCameraSession`의 `frameCallback`이 같은 두 곳에 등록된다. 같은 프레임에 대해 콜백이 두 번 불릴 수 있으며, 기존 타임스탬프 중복 제거가 그 결과를 걸러내고 있다. 이 방어를 제거한 채 카운터만 추가하면 `frame_number`가 프레임당 2씩 증가해 결함이 더 나빠진다. 카운터는 중복 제거를 통과한 행에 대해서만 증가해야 한다.

**검토한 대안**: *Camera2의 `CaptureResult.FRAME_NUMBER`를 사용*. 이 값은 CaptureSession 수명 기준 요청 일련번호이며 0에서 시작하지 않고, 드롭된 요청에 대해서도 증가한다. 수신 측이 요구한 "Camera Stream의 순차 frame index"와 다르다. 기각.

---

## 결정 6: Timestamp 기록 구간을 녹화 구간에 맞춘다

**결정**: `@Volatile` 플래그를 두어 `recorder.start()` 직후 활성화하고 `mediaRecorder.stop()` 직전에 비활성화한다. 플래그가 꺼진 동안 도착한 `CaptureResult`는 CSV에 기록하지 않는다.

**근거**: 수신 측이 보고한 3~9 frame 차이의 원인을 코드에서 특정했다.
- **시작부**: `setRepeatingRequest`는 `onConfigured`에서 시작되지만 `recorder.start()`는 그 다음 콜백인 `onActive`에서 호출된다. 그 사이 프레임의 `CaptureResult`는 CSV에 남지만 MP4에는 없다.
- **종료부**: `mediaRecorder.stop()`이 먼저 실행되고 `captureSession.close()`는 `releaseResources()`에서 나중에 실행된다. 그 사이 프레임도 CSV에만 남는다.

두 경계가 차이의 전부이며 영상 중간의 지속적 frame drop이 아니다. 플래그 하나로 양쪽 경계가 모두 닫히고, 인코더 동작에는 손대지 않는다.

**한계**: MediaRecorder가 인코딩을 시작하는 정확한 프레임 경계는 제어할 수 없으므로 1:1 대응을 보장하지 않는다. SC-009의 목표를 2 frame 이하로 둔 이유이며, 수신 측도 서버 전처리의 Temporal Crop으로 처리하기로 했다.

---

## 결정 7: Camera Intrinsic의 획득 출처

> (2026-09-16) 이 결정을 뒤집었다. 녹화를 1920×1080으로 올리려고 MediaRecorder 해상도와 Intrinsic을 GPU
> 텍스처 스트림(`cameraConfig.textureSize`, `Camera.getTextureIntrinsics()`)으로 옮겼다. CPU 이미지
> (`imageSize`)는 640×480으로 남아야 stream 조합이 성립한다. 근거는 [계약](contracts/capture-state-machine.md)의
> "Session 중 화면 프리뷰"에 있고, 아래는 당시의 결정이다.

**결정**: ARCore `Frame.getCamera().getImageIntrinsics()`를 1차 출처로 사용하고, Camera2 `CameraCharacteristics`로 부가 광학 값을 보완한다. 첫 유효 프레임에서 1회 획득해 보관했다가 Session 마감 시 기록한다.

| 필드 | 출처 | 확보 |
|---|---|---|
| `camera_id` | ARCore `Session.getCameraConfig().getCameraId()` | 항상 |
| `image_width` / `image_height` | `CameraIntrinsics.getImageDimensions()` | 항상 |
| `fx` / `fy` | `CameraIntrinsics.getFocalLength()` | 항상 |
| `cx` / `cy` | `CameraIntrinsics.getPrincipalPoint()` | 항상 |
| `focal_length_mm` | Camera2 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS` | 대체로 |
| `sensor_width_mm` / `sensor_height_mm` | Camera2 `SENSOR_INFO_PHYSICAL_SIZE` | 대체로 |
| `distortion_coefficients` | Camera2 `LENS_DISTORTION` | 기기 의존 |

**근거**: `getImageIntrinsics()`는 ARCore가 실제로 사용하는 CPU 이미지 스트림에 대응하는 값을 돌려준다. 그리고 현행 구현은 MediaRecorder 해상도를 `session.cameraConfig.imageSize`로 설정하므로([`AndroidCaptureRuntime`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/capture/AndroidCaptureRuntime.kt)), **녹화 해상도와 intrinsics 기준 해상도가 자동으로 일치한다.** 수신 측이 요구한 "기기 대표값이 아니라 실제 촬영 Camera ID 및 Resolution에 대응하는 값"이 별도 보정 없이 충족된다. FR-022와 SC-007의 근거가 이것이다.

`LENS_DISTORTION`은 API 28 이상에서 정의되지만 기기가 제공하지 않으면 `null`이다. FR-024에 따라 이 경우 값을 계산해 채우지 않고 `null`로 남긴다.

**검토한 대안**:
- *`getTextureIntrinsics()` 사용*: GPU 텍스처 스트림(`cameraConfig.textureSize`) 기준이라 녹화 해상도와 다를 수 있다. 기각.
- *`CameraCapabilityPreflight` 재사용*: 이미 focal/sensor/activeArray를 읽지만, Galaxy S10 1× 프로파일 값과 하드코딩 비교해 불일치 시 실패시킨다. 메타데이터 수집에 그대로 쓰면 FR-025(메타데이터 실패가 Session을 실패시키지 않음)를 위반한다. 값 읽기 로직만 참고하고 판정 로직은 쓰지 않는다. (2026-09-23) 이 클래스는 쓰는 곳이 없어 지웠다.

---

## 결정 8: Intrinsic 기록 실패가 Session을 실패시키지 않게 한다

**결정**: Camera Metadata 수집은 전부 `runCatching`으로 감싸고, 실패 시 해당 필드를 생략하거나 `null`로 두고 Session 마감을 계속 진행한다. `SessionFinalizer.finalize()`는 메타데이터를 선택적 인자로 받는다.

**근거**: FR-025가 명시적으로 요구한다. 수집이 끝난 영상·IMU·Pose 데이터는 그 자체로 가치가 있으므로, 부가 메타데이터 획득 실패로 Session 전체를 잃어서는 안 된다.

**호환성 확인**: [`SessionBundleValidator`](../../app/src/main/java/com/ssafy/s15p21a206/tiger/episode/EpisodeBundleValidator.kt)는 `metadata.json`에서 `session_id`, `camera_streams`, `files`만 읽고 알 수 없는 키는 무시한다. 새 필드 추가는 검증을 깨지 않는다. FR-026과 SC-008이 충족된다.

---

## 결정 9: Episode 마감 사건의 전파

**결정**: `CaptureSessionCoordinator`에 `onEpisodeClosed: (EpisodeMarker) -> Unit` 생성자 콜백을 추가한다. `endEpisode()`(사용자 조작)와 `onTracking()`의 `INVALID_TRACKING` 자동 마감이 모두 이 콜백을 통해 Episode를 확정한다. 화면은 이 콜백에서 Room 저장과 `episodes.csv` 기록을 수행한다.

**근거**: `INVALID_TRACKING` 마감은 사용자 조작 없이 ticker 안에서 발생하므로, 화면이 `latestClosedEpisode`를 폴링하지 않는 한 기록 시점을 알 수 없다. 기존 `onInterrupted` 콜백과 같은 방식이라 클래스의 설계 결을 따른다. 두 경로가 같은 출구를 쓰므로 FR-015의 두 상태가 동일한 형식으로 기록된다.

**중복 마감 방지**: `endEpisode()`는 `activeEpisode`가 `null`이면 예외를 던진다. `INVALID_TRACKING` 자동 마감이 `activeEpisode`를 이미 비우므로, 그 직후 사용자가 일시 정지를 눌러도 화면 상태가 `Initializing`으로 바뀌어 있어 조작 자체가 차단된다. 엣지 케이스 항목이 이렇게 해소된다.

---

## 미해결 항목

없다. Technical Context의 `NEEDS CLARIFICATION`이 모두 해소되었다.

Ultra-wide Camera 동시 운용은 [spec.md](spec.md)의 **범위 밖** 절에서 이번 기능에서 제외했으므로 조사 대상이 아니다. 추후 다룬다면 실기기 timebox 확인 작업으로 분리한다.

---

## 결정 10: 수집 중 프리뷰는 ARCore Camera 텍스처를 직접 그려서 채운다

**결정**: pose 수집 스레드의 EGL context를 1×1 PBuffer 대신 프리뷰 Surface 위의 window surface로 만들고(`CaptureEgl`), `session.setCameraTextureName`으로 ARCore가 채우는 OES 텍스처를 매 프레임 그린다(`CameraTextureRenderer`). Camera2 출력 stream은 늘리지 않는다.

**먼저 시도했다가 기각한 안 — 프리뷰 surface를 카메라 출력으로 등록**: `SharedCamera.setAppSurfaces`에 MediaRecorder surface와 함께 프리뷰 surface를 등록하는 방식이다. 변경 폭이 훨씬 작고 자연스러워 이쪽을 먼저 구현했으나, 실기기에서 `createCaptureSession`이 실패했다.

```text
I TigerCapture: shared camera streams: arcore=2 app=2 total=4 preview=true valid=true
E TigerCapture: CAMERA_ERROR (3): endConfigure:704: Camera 0: Error configuring streams: Broken pipe (-32)
```

ARCore가 2개(GPU 텍스처 + CPU 이미지), MediaRecorder 1개에 프리뷰까지 더해 4개다. 프리뷰만 빼 3개로 줄이면 수집·마감·업로드가 모두 정상이므로, 원인은 stream 개수 조합이다. Camera2의 보장 조합표는 `LEVEL_3` 미만에서 동시 `PRIV` 3개를 보장하지 않으며 이 기기가 그 경계에 걸린다. `minSdk = 28`이라 `isSessionConfigurationSupported`(API 29)로 미리 확인할 수도 없다.

**근거**: 채택안은 stream을 하나도 늘리지 않아 이 제약을 원천 회피한다. 또한 ARCore가 이미 카메라 텍스처를 받고 있으므로 추가 카메라 대역폭도 들지 않는다. 실측 결과 실효 FPS는 29.998로 프리뷰 없는 대조군(30.004)과 차이가 없고, `main_frame_timestamps.csv` 행 수 대 MP4 frame 수 차이도 대조군과 같은 3이었다.

**비용**: OES 셰이더와 `Frame.transformCoordinates2d` 기반 UV 처리가 필요하고, pose 수집 스레드가 렌더 스레드를 겸한다. 기록 경로와 렌더링이 한 스레드에 묶이므로, 이후 렌더링을 무겁게 만들면 pose 기록 주기에 영향이 갈 수 있다. 그리기는 `runCatching`으로 감싸 실패가 pose 수집을 멈추지 않게 했다.

**화각 일치**: 프리뷰 버퍼와 `setDisplayGeometry`를 녹화와 같은 `cameraConfig.textureSize`로 잡는다(2026-09-16 갱신. 처음에는 `imageSize` 기준이었다). 표시 기하를 화면 크기로 잡으면 ARCore가 화면 비율에 맞춰 이미지를 잘라내므로 저장 영상보다 좁은 화각이 된다. 촬영 해상도를 기준으로 잡아야 저장되는 것과 같은 화각이 그대로 나온다.

**fallback을 넣지 않은 이유**: 대상 기기가 갤럭시 S10 하나이고 실제 배포가 없다. 채택안은 stream 제약을 받지 않으므로 애초에 fallback이 필요한 실패 모드가 없다.
