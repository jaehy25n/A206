package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class RecordingState {
    IDLE,
    INITIALIZING,
    READY,
    FINALIZING,
    COMPLETED,
    INTERRUPTED,
    ;

    fun canTransitionTo(next: RecordingState): Boolean =
        when (this) {
            IDLE -> next == INITIALIZING
            INITIALIZING -> next == READY || next == INTERRUPTED
            READY -> next == FINALIZING || next == INTERRUPTED
            FINALIZING -> next == COMPLETED || next == INTERRUPTED
            COMPLETED, INTERRUPTED -> false
        }
}

@Serializable
enum class EpisodeState {
    NONE,
    ACTIVE,
    COMPLETED,
    INVALID_TRACKING,
    ;

    fun canTransitionTo(next: EpisodeState): Boolean =
        when (this) {
            NONE -> next == ACTIVE
            ACTIVE -> next == COMPLETED || next == INVALID_TRACKING
            COMPLETED, INVALID_TRACKING -> false
        }
}

@Serializable enum class TrackingState { INITIALIZING, READY, PAUSED, STOPPED }

@Serializable enum class UltraWideProbeResult { UW_SUPPORTED, UW_UNSUPPORTED_FOR_MVP }

@Serializable enum class UploadState { LOCAL_ONLY, UPLOADING, UPLOADED, FAILED }

@Serializable
data class CaptureSession(
    @SerialName("session_id") val sessionId: String,
    @SerialName("display_number") val displayNumber: Int,
    val recordingState: RecordingState,
    val uploadState: UploadState,
    @SerialName("recording_start_monotonic_timestamp_ns") val recordingStartMonotonicTimestampNs: Long,
    @SerialName("recording_end_monotonic_timestamp_ns") val recordingEndMonotonicTimestampNs: Long? = null,
    @SerialName("bundle_path") val bundlePath: String,
    @SerialName("recording_start_epoch_ms") val recordingStartEpochMs: Long = 0L,
    /**
     * 수집 정보 입력에서 받은 두 이름. 기본값을 두지 않는다.
     *
     * 이 Session을 저장하는 모든 경로가 두 값을 명시하게 만드는 것이 이 필드의 목적이다. 빈
     * 문자열을 기본값으로 두면, 넘기는 것을 잊은 저장 경로가 조용히 이름 없는 Session을 남긴다.
     * 그것이 애초에 이 필드를 만든 사고였다. 과거 Session은 이관에서 채우지 못하면 빈 값을 갖지만,
     * 그것은 읽는 쪽의 사실이지 쓰는 쪽의 기본값이 아니다.
     */
    val task: String,
    @SerialName("object") val objectName: String,
)

data class SessionSummary(
    val sessionId: String,
    val displayNumber: Int,
    val uploadState: UploadState,
    val recordingStartEpochMs: Long,
    val recordingStartMonotonicTimestampNs: Long,
    val recordingEndMonotonicTimestampNs: Long?,
    val bundlePath: String,
    val completedEpisodeCount: Int,
    val taskName: String = "",
    val objectName: String = "",
)

@Serializable
data class EpisodeMarker(
    @SerialName("episode_id") val episodeId: String,
    @SerialName("session_id") val sessionId: String,
    @SerialName("start_timestamp_ns") val startTimestampNs: Long,
    @SerialName("end_timestamp_ns") val endTimestampNs: Long? = null,
    val task: String,
    @SerialName("object") val objectName: String,
    val outcome: EpisodeState,
)

/**
 * 실제 촬영에 사용된 Camera의 식별자·해상도·Intrinsic.
 *
 * 필수 값은 ARCore가 사용하는 이미지 스트림에서 얻으므로 촬영 해상도와 대응이 보장된다.
 * nullable 필드는 기기가 제공할 때만 채운다. 값을 억지로 계산해 채우지 않는다.
 */
@Serializable
data class CameraMetadata(
    @SerialName("camera_id") val cameraId: String,
    @SerialName("image_width") val imageWidth: Int,
    @SerialName("image_height") val imageHeight: Int,
    val fx: Float,
    val fy: Float,
    val cx: Float,
    val cy: Float,
    @SerialName("focal_length_mm") val focalLengthMm: Float? = null,
    @SerialName("sensor_width_mm") val sensorWidthMm: Float? = null,
    @SerialName("sensor_height_mm") val sensorHeightMm: Float? = null,
    @SerialName("distortion_coefficients") val distortionCoefficients: List<Float>? = null,
    /** `main_rgb.mp4`에 적용된 시계 방향 회전. 이 값을 반영한 뒤의 기하가 위 필드에 담긴다. */
    @SerialName("video_rotation_degrees") val videoRotationDegrees: Int = 0,
) {
    /**
     * 영상에 적용한 시계 방향 회전을 Intrinsic에도 반영한다.
     *
     * 회전을 반영하는 도구로 영상을 열면 프레임이 이미 돌아간 상태로 나오므로, Intrinsic도 같은
     * 기하를 가리켜야 투영이 맞는다. 90도와 270도에서는 가로세로와 초점거리 축이 바뀐다.
     *
     * 픽셀 좌표 `(x, y)`는 90도에서 `(H - y, x)`로, 270도에서 `(y, W - x)`로, 180도에서
     * `(W - x, H - y)`로 옮겨진다. `W`, `H`는 회전 전 가로·세로다.
     */
    fun rotatedClockwise(degrees: Int): CameraMetadata =
        when (((degrees % 360) + 360) % 360) {
            90 ->
                copy(
                    imageWidth = imageHeight,
                    imageHeight = imageWidth,
                    fx = fy,
                    fy = fx,
                    cx = imageHeight - cy,
                    cy = cx,
                    videoRotationDegrees = 90,
                )
            180 ->
                copy(
                    cx = imageWidth - cx,
                    cy = imageHeight - cy,
                    videoRotationDegrees = 180,
                )
            270 ->
                copy(
                    imageWidth = imageHeight,
                    imageHeight = imageWidth,
                    fx = fy,
                    fy = fx,
                    cx = cy,
                    cy = imageWidth - cx,
                    videoRotationDegrees = 270,
                )
            else -> copy(videoRotationDegrees = 0)
        }
}

@Serializable data class ProbeResult(
    val result: UltraWideProbeResult,
    val detail: String? = null,
)

@Serializable
data class CameraConfig(
    val logicalCameraId: String,
    val selectedPhysicalCameraId: String,
    val lensFacing: String = "BACK",
    val lensLabel: String = "main_1x",
    val focalLengthMm: Float,
    val sensorPhysicalWidthMm: Float,
    val sensorPhysicalHeightMm: Float,
    val activeArray: IntRect,
    val preCorrectionActiveArray: IntRect,
    val resolution: RecordingResolution,
    val targetFps: Int = TARGET_FPS,
    val zoomRatio: Float = 1f,
    val oisEnabled: Boolean = false,
    val eisEnabled: Boolean = false,
    val timestampSource: String = "REALTIME",
) {
    companion object {
        const val TARGET_FPS = 30
    }
}

@Serializable data class IntRect(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
)

@Serializable data class RecordingResolution(
    val width: Int,
    val height: Int,
)

@Serializable data class TimebaseMetadata(
    val cameraImuComparability: String = "VERIFIED",
)

@Serializable data class FileManifest(
    val path: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val sha256: String,
)

@Serializable data class RemoteReceipt(
    @SerialName("session_id") val sessionId: String,
    val result: String,
)

@Serializable data class UploadError(
    val code: String? = null,
    val message: String? = null,
)
