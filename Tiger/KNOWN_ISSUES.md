# 알려진 결함

코드와 문서를 대조하다 찾은 것 가운데, 명세가 요구하거나 코드 스스로 밝힌 의도와 실제 동작이 다른
곳이다. 명세·계약에는 지금 동작을 적거나 이 문서를 가리키는 표시를 두었다. 고치면 여기서 지우고,
표시해 둔 명세·계약도 함께 되돌린다.

2026-09-29에 코드를 읽어 정리했다. 실기기로 재현하지 않은 항목은 제목에 그렇게 적었다. 경로는
`app/src/main/java/com/ssafy/s15p21a206/tiger/` 기준이다.

## 데이터

### 화면 중단 때 진행 중이던 Episode가 기록되지 않는다

- **현상**: Episode 도중 홈 버튼·화면 꺼짐으로 `ON_STOP`이 오면 그 Episode는 `episodes.csv`에도
  색인에도 남지 않는다. 다음 실행의 구제로 raw stream은 살아나지만 그 작업 구간의 경계가 사라진다.
- **근거**: `ui/capture/CaptureDriver.kt`의 `ON_STOP` 처리가 `coordinator.release()`를 부르고,
  `capture/CaptureSessionCoordinator.kt`의 `release()`는 `activeEpisode`를 `onEpisodeClosed` 없이 비운다.
- **관련 요구**: 003 FR-027(그때까지 수집된 데이터를 폐기하지 않는다).
- **고치는 방향**: 비우기 전에 열린 Episode를 마감해 기록한다. 그때의 `outcome`을 무엇으로 둘지는
  수신 측 계약(`COMPLETED`·`INVALID_TRACKING`만 허용)이라 먼저 정해야 한다.

### 구제된 Session의 metadata에 `camera`와 `capture_settings`가 없다

- **현상**: staging에 남았다가 다음 실행에서 구제된 Session은 수동 촬영 조건으로 찍었어도 두 객체 없이
  마감된다. 촬영 Camera의 Intrinsic과 촬영 조건을 잃는다.
- **근거**: `episode/SessionRepository.kt`의 `recoverInterruptedStaging`이 `SessionFinalizer.finalize(bundle)`를
  `camera`·`captureSettings` 없이 부른다. 두 값은 수집 중 메모리에만 있다
  (`ArPoseCollector.cameraMetadata`, `AndroidCaptureRuntime.manualConfig`).
- **관련 요구**: 003 FR-021(마감 시 Camera 정보 기록), 002 FR-017f(촬영 조건 기록).
  [session-metadata 계약](specs/003-session-episode-tracking-gate/contracts/session-metadata.md)에는 이때의
  키 부재를 "기록되지 않음"으로 읽으라고 적었다.
- **고치는 방향**: 확보하는 대로 staging에 따로 적어 두고(시작 시 촬영 조건, 첫 유효 프레임 뒤 Camera
  정보), 구제가 그것을 읽어 metadata에 넣는다.

### `video_rotation_degrees`가 metadata에 쓰이지 않는다

- **현상**: 회전이 없어 값이 기본값 `0`이면 `camera` 객체에서 키가 빠진다. 지금은 모든 Session이 그렇다.
- **근거**: `episode/EpisodeModels.kt`의 `CameraMetadata.videoRotationDegrees`는 기본값이 `0`인데
  `@EncodeDefault`가 없고, `SessionFinalizer`는 기본값을 생략하는 기본 `Json`으로 직렬화한다. 같은 문제를
  피하려고 `CaptureSettingsMetadata`의 `awb_fixed`·`fps_target`에는 `@EncodeDefault`를 붙여 두었다.
- **관련 요구**: 003 FR-037(적용한 회전 각도를 함께 기록), SC-013. 계약에는 지금 동작(0이면 생략,
  없으면 0)을 적었다.
- **고치는 방향**: `@EncodeDefault` 한 줄이다. metadata 출력이 바뀌므로 계약을 먼저 되돌린다.

### 비정상 종료·마감 실패 뒤 구제된 영상이 완결되지 않았을 수 있다 (실기기 미확인)

- **현상**: 프로세스가 죽거나 `MediaRecorder.stop()`이 실패한 Session은 MP4가 마무리되지 않은 채 staging에
  남는다. 구제는 영상 크기가 0보다 큰지만 보므로, 재생할 수 없는 영상을 담은 채 `COMPLETED`로 공개하고
  업로드 대상에 넣을 수 있다.
- **근거**: `episode/EpisodeBundleValidator.kt`의 `hasContent()`는 `length() > 0`만 확인한다. `ON_STOP`
  경로는 `AndroidCaptureRuntime.interrupt()`에서 `stop()`을 부르므로 해당하지 않는다.
- **관련 요구**: 003 FR-029(마감할 수 없을 만큼 손상된 Session만 중단으로 남긴다).
- **고치는 방향**: 구제할 때 MP4를 열어 길이를 읽어 보고, 읽지 못하면 `INTERRUPTED`로 남긴다.

## 수집 화면

### Episode 도중 정지·X가 일어나지 않을 일을 확인받는다

- **현상**: Episode 진행 중 정지·X·시스템 뒤로 가기를 누르면 "현재 녹화를 종료하고 세션을 완료한 뒤
  전송을 시작합니다." 확인이 뜬다. 확인하면 마감하지 않고 "ACTIVE Episode를 먼저 END 또는 CANCEL 하세요."를
  띄운다. 확인 문구가 약속한 일은 일어나지 않고, 안내가 말하는 CANCEL 조작은 없다(UI의 동사는 일시 정지).
- **근거**: `ui/capture/CaptureControlPolicy.kt`의 `exitAction`이 `EpisodeActive`에서도 `Confirm`을 주고,
  `ui/capture/CaptureDriver.kt`의 `finalizeCapture`가 확인 뒤에 거부한다. 문구는 `strings.xml`의
  `capture_stop_message`, `active_episode_end_required`다.
- **관련 요구**: 003 FR-006(거부하고 안내한다), 002 FR-013a·001 FR-005(Episode 취소 조작을 두지 않는다).
  계약에는 지금 동작(확인 후 거부)을 적었다.
- **고치는 방향**: `EpisodeActive`에서는 확인 없이 바로 안내하고, 문구를 실제 조작(일시 정지)으로 바꾼다.
  문자열과 화면을 바꾸므로 계측 테스트를 돌린다.

### 마감에 성공한 뒤에도 유휴 프리뷰를 다시 연다 (실기기 미확인)

- **현상**: 마감을 마치고 상세로 넘어가는 경로에서도 유휴 Camera2 프리뷰를 한 번 다시 열었다가, 작업
  공간이 사라질 때 닫는다.
- **근거**: `ui/capture/CaptureDriver.kt`의 `finalizeCapture`가 `finally`에서 `if (state.open) restoreIdlePreview()`를
  부른다. `state`는 마감을 시작한 시점의 값이라 늘 `open`이고, 그 순간에는 작업 공간을 닫는 상태 변경이
  아직 화면에 반영되지 않아 Surface도 남아 있다. 의도는 작업 공간에 남는 경로에서만 다시 여는 것이다.
- **영향**: 카메라를 한 번 열고 곧 닫는다. 늦게 온 콜백은 `CameraPreviewController`가 세대 번호로 걸러,
  드러난 문제는 확인하지 못했다.
- **고치는 방향**: 마감 결과를 보고 작업 공간에 남는 경로(마감 실패, 업로드 서버 주소 없음)에서만 부른다.

### 고른 해상도의 Camera config가 없으면 화면 상태가 고른 값으로 되돌아간다

- **현상**: 고른 해상도를 가진 ARCore Camera config가 없어 기본 config로 수집하면, 프리뷰 버퍼는 실제
  크기로 맞추지만 상태의 `resolution`·`idlePreviewSize`는 시작 전에 고른 값으로 되돌아간다.
- **근거**: `ui/capture/CaptureDriver.kt`가 `SelectResolution(actual)`을 보낸 뒤 `SessionStarted`에 시작 전의
  `state.resolution`을 넘긴다. `ui/capture/CaptureState.kt`의 주석은 이 값을 "ARCore가 실제로 고른 크기"라고 적는다.
- **영향**: 기준 기기(SM-G973N)는 두 해상도의 config를 모두 가져 일어나지 않는다.
- **고치는 방향**: `previewSurfaces` 콜백이 받은 실제 크기를 `SessionStarted`에 넘긴다.

### 카메라 능력을 읽지 못하면 설정 시트가 "읽는 중"에 머문다

- **현상**: 녹화 카메라의 능력을 읽지 못하면 시트가 "카메라 정보를 읽는 중입니다."를 계속 보여 준다.
  화이트 밸런스만 지원하지 않는 기기에서는 단추가 꺼질 뿐 이유가 나오지 않는다.
- **근거**: `ui/capture/CaptureDriver.kt`의 설정 읽기 `LaunchedEffect`는 `ManualCameraProfile.read()`가 null이면
  아무 intent 없이 돌아간다. `ui/capture/CaptureCameraPanel.kt`의 `WhiteBalanceRow`에는 사유 문구가 없다.
- **관련 요구**: 002 FR-017c(지원하지 않는 항목은 이유를 보인다).
- **고치는 방향**: 읽기 실패를 사유와 함께 상태로 올리고, 화이트 밸런스 줄에도 사유를 둔다.

## 전송

### 전송이 겹치면 앞의 전송이 백그라운드에서도 계속된다

- **현상**: 한 Session을 보내는 중에 다른 Session의 전송을 걸면 앱이 추적하는 Job이 뒤의 것으로 바뀐다.
  이후 앱을 백그라운드로 보내면 뒤의 전송만 끊기고 앞의 전송은 계속된다.
- **근거**: `ui/session/SessionOperations.kt`의 `upload()`가 `uploadJob`을 덮어쓰고, `cancelUpload()`와
  `uploadInFlight`는 그 하나만 본다.
- **관련 요구**: 002 FR-014d(백그라운드 전환 시 즉시 중단).
- **고치는 방향**: Job을 Session마다 두거나, 전송 중에는 다른 전송을 막는다.

### 실패 사유가 다른 Session의 상세에 보인다

- **현상**: 실패 사유는 앱 전체에 하나뿐이고, `FAILED`인 Session의 상세는 모두 그 값을 보여 준다. 마지막으로
  실패한 전송의 사유가 다른 Session에 붙을 수 있다.
- **근거**: `ui/session/SessionOperations.kt`의 `uploadFailureReason`, `ui/session/SessionDetailScreen.kt`의 실패
  사유 표시.
- **관련 요구**: 002 FR-014b-1(그 Session의 실패 사유와 재전송을 함께 표시한다).
- **고치는 방향**: 사유를 Session 식별자와 함께 든다.

### 업로드 서버 주소가 없는 빌드에서 상세의 `업로드`가 반응하지 않는다

- **현상**: `tigerUploadBaseUrl` 없이 빌드하면 상세에 `업로드` 단추가 보이지만, 눌러도 아무 일이 일어나지
  않고 문구도 뜨지 않는다.
- **근거**: `TigerApp.kt`의 `startUpload`는 전송 기능이 없으면 수집 상태에 알림(`CaptureIntent.Notify`)만
  남기는데, 그 알림은 작업 공간이 열려 있을 때만 보인다. `ui/session/SessionDetailPresentation.kt`는 전송
  기능 유무와 관계없이 `LOCAL_ONLY`에 단추를 둔다.
- **고치는 방향**: 전송 기능이 없으면 단추를 두지 않거나, 상세에 사유를 보인다.

## 명세에 있으나 구현되지 않은 요구

### 시작 전 저장 공간 확인

001 FR-013a와 002의 엣지 케이스는 시작 전에 저장 공간을 확인하고, 모자라면 시작하지 않거나
`INTERRUPTED`로 처리하라고 요구한다. 확인하는 코드가 없다(`StatFs`·`usableSpace`를 쓰는 곳이 없다).
`recording_storage_insufficient` 문구도 쓰이지 않는다. 판정 클래스(`SessionStartPreflight`)는 배선된 적
없이 2026-09-23에 지웠다.

### 수집 중 치명 오류 감지

001 FR-008은 Camera·영상 writer·IMU writer의 치명 오류가 나면 Session을 `INTERRUPTED`로 표시하라고
요구한다. 수집이 시작된 뒤에는 그 오류를 받는 경로가 없다.

- `capture/ArSharedCameraSession.kt`의 `onDisconnected`·`onError`는 카메라를 닫고, 이미 끝난 열기 대기를
  다시 실패시킬 뿐 수집 쪽에 알리지 않는다.
- `MediaRecorder` 오류 리스너가 없다.
- `capture/ArPoseCollector.kt`의 수집 스레드는 예외를 다시 던져 프로세스를 끝낸다. 그때는 다음 실행의
  구제가 번들을 살린다.

### IMU·Camera 상태 표시

001 FR-015는 Camera·IMU 상태와 치명 오류를 수집자에게 바로 보이라고 요구한다. 화면은 ARCore Tracking
상태 배지만 보인다. 기기에 없는 센서는 `capture/SensorLogWriter.kt`가 조용히 건너뛰어 그 CSV가 헤더만
남고, `recording_sensor_unavailable` 문구는 쓰이지 않는다.
