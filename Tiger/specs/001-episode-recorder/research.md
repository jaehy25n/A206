# 조사 기록: Episode Recorder MVP

## 후면 main 1× 선택

**결정**: `LENS_FACING_BACK`만으로 1×를 가정하지 않는다. API 28+에서 physical camera ID와 focal length를 조사하고, 검증된 wide/main physical ID를 선택한다. 물리 output 미지원이면 조용히 logical camera로 대체하지 않고 preflight를 실패시킨다.

**근거**: logical back camera는 OEM/HAL에 따라 physical camera를 전환할 수 있다.

**참조**: [Camera enumeration](https://developer.android.com/media/camera/camera2/camera-enumeration), [multi-camera](https://developer.android.com/media/camera/camera2/multi-camera)

## 해상도와 30 FPS

**결정**: `StreamConfigurationMap`의 encoder size/minimum frame duration과 `CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES`의 (30,30)을 preflight에서 모두 확인한다.

**근거**: FPS request만으로 configured stream의 실제 지속 FPS는 보장되지 않는다.

**참조**: [StreamConfigurationMap](https://developer.android.com/reference/android/hardware/camera2/params/StreamConfigurationMap), [CaptureRequest](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest)

## Sensor event 보존

**결정**: sensor callback을 독립 record로 저장한다. SensorEvent timestamp와 accuracy를 원본대로 보존한다.

**근거**: timestamp는 `elapsedRealtimeNanos()` timebase이며 센서 event는 독립적으로 전달된다. requested rate는 hint일 뿐이다.

**참조**: [SensorEvent](https://developer.android.com/reference/android/hardware/SensorEvent), [SensorManager](https://developer.android.com/reference/android/hardware/SensorManager)

## frame correspondence와 timebase

**결정**: 대상 Galaxy S10 SM-G973N 후면 Camera device 0에서 실측한 `SENSOR_INFO_TIMESTAMP_SOURCE = REALTIME`를 preflight에서 확인한다. `CaptureResult.SENSOR_TIMESTAMP`와 `SensorEvent.timestamp`를 common monotonic timebase로 기록하고 `VERIFIED`를 metadata에 남긴다. MVP는 completed bundle의 모바일 서버 업로드를 구현하되, 서버 측 MP4 frame↔timestamp 대응·동기화 품질 검증은 구현하지 않는다.

**근거**: image buffer timestamp는 해당 capture의 sensor timestamp와 같지만, 일반 encoder Surface/MediaRecorder는 app-visible per-frame mapping을 주지 않는다. 앱은 원본 ns timestamp를 CSV에 보존하고 서버가 MP4와의 대응을 검증한다.

**실시간 실패 처리**: `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session, encoder·muxer·writer 오류는 앱이 즉시 감지해 `INTERRUPTED` 처리한다. frame number와 성공 capture timestamp는 보존하지만, MP4 sample과의 완전한 1:1 대응 검증은 이 MVP에 넣지 않는다.

**참조**: [CaptureResult](https://developer.android.com/reference/android/hardware/camera2/CaptureResult), [CameraCharacteristics](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics), [OutputConfiguration](https://developer.android.com/reference/android/hardware/camera2/params/OutputConfiguration), [MediaCodec.BufferInfo](https://developer.android.com/reference/android/media/MediaCodec.BufferInfo)

## S10 calibration metadata

**결정**: SM-G973N Camera device 0의 `dumpsys media.camera` 정적 metadata에서 `android.lens.intrinsicCalibration`, `android.lens.distortion`, `android.lens.poseRotation`, `android.lens.poseTranslation`, `android.lens.poseReference`는 제공되지 않았다. 해당 key는 null·optional로 모델링하지 않고 계약에서 제외한다.

**기록할 값**: focal length `4.32000017`, sensor physical size `[5.64499998, 4.23400021]`, active/pre-correction array `[0, 0, 4032, 3024]`, timestamp source `REALTIME` 및 실제 OIS/EIS 상태를 non-null으로 기록한다.

## 로컬 삭제

**결정**: completed episode는 확인 후 bundle directory 전체를 개별 삭제한다. CaptureLog는 개별 삭제·열람 UI 없이 확인 후 전체 삭제한다. 모두 앱 전용 영구 저장소에서 `File` API로 삭제하며 자동 삭제하지 않는다.

## 원자적 bundle 공개

**결정**: 모든 산출물을 staging directory에 쓴 뒤 여섯 파일의 완결성 검증 성공 시 metadata commit marker를 마지막으로 쓰고 completed로 공개한다.

**근거**: AtomicFile은 단일 파일만 원자적으로 처리한다. bundle 전체에는 staging + commit marker가 필요하다.

**참조**: [AtomicFile](https://developer.android.com/reference/android/util/AtomicFile), [app-specific storage](https://developer.android.com/training/data-storage/app-specific)
