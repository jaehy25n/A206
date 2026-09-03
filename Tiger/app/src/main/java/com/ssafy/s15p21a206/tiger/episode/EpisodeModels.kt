package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class RecordingState {
    IDLE, INITIALIZING, READY, FINALIZING, COMPLETED, INTERRUPTED;

    fun canTransitionTo(next: RecordingState): Boolean = when (this) {
        IDLE -> next == INITIALIZING
        INITIALIZING -> next == READY || next == INTERRUPTED
        READY -> next == FINALIZING || next == INTERRUPTED
        FINALIZING -> next == COMPLETED || next == INTERRUPTED
        COMPLETED, INTERRUPTED -> false
    }
}

@Serializable
enum class EpisodeState {
    NONE, ACTIVE, COMPLETED, CANCELLED, INVALID_TRACKING;

    fun canTransitionTo(next: EpisodeState): Boolean = when (this) {
        NONE -> next == ACTIVE
        ACTIVE -> next == COMPLETED || next == CANCELLED || next == INVALID_TRACKING
        COMPLETED, CANCELLED, INVALID_TRACKING -> false
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
    @SerialName("bundle_path") val bundlePath: String
)

@Serializable
data class EpisodeMarker(
    @SerialName("episode_id") val episodeId: String,
    @SerialName("session_id") val sessionId: String,
    @SerialName("start_timestamp_ns") val startTimestampNs: Long,
    @SerialName("end_timestamp_ns") val endTimestampNs: Long? = null,
    val task: String,
    @SerialName("object") val objectName: String,
    val outcome: EpisodeState
)

@Serializable data class ProbeResult(val result: UltraWideProbeResult, val detail: String? = null)

@Serializable
data class CameraConfig(
    val logicalCameraId: String, val selectedPhysicalCameraId: String, val lensFacing: String = "BACK",
    val lensLabel: String = "main_1x", val focalLengthMm: Float, val sensorPhysicalWidthMm: Float,
    val sensorPhysicalHeightMm: Float, val activeArray: IntRect, val preCorrectionActiveArray: IntRect,
    val resolution: RecordingResolution, val targetFps: Int = TARGET_FPS, val zoomRatio: Float = 1f,
    val oisEnabled: Boolean = false, val eisEnabled: Boolean = false, val timestampSource: String = "REALTIME"
) { companion object { const val TARGET_FPS = 30 } }

@Serializable data class IntRect(val left: Int, val top: Int, val right: Int, val bottom: Int)
@Serializable data class RecordingResolution(val width: Int, val height: Int)
@Serializable data class TimebaseMetadata(val cameraImuComparability: String = "VERIFIED")

@Serializable
data class CaptureLog(
    val id: Long = 0, val sessionId: String?, val reason: String, val summary: String, val timestampNs: Long,
    val frameCount: Long, val accelerometerCount: Long, val gyroscopeCount: Long, val rotationVectorCount: Long
)

@Serializable data class FileManifest(val path: String, @SerialName("size_bytes") val sizeBytes: Long, val sha256: String)
@Serializable data class RemoteReceipt(@SerialName("session_id") val sessionId: String, val result: String)
@Serializable data class UploadError(val code: String? = null, val message: String? = null)
