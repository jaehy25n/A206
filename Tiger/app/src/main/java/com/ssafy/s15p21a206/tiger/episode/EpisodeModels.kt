package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class RecordingState {
    RECORDING,
    COMPLETED,
    INTERRUPTED;

    fun canTransitionTo(next: RecordingState): Boolean = when (this) {
        RECORDING -> next == COMPLETED || next == INTERRUPTED
        COMPLETED, INTERRUPTED -> false
    }
}

@Serializable
enum class UploadState {
    LOCAL_ONLY,
    UPLOADING,
    UPLOADED,
    FAILED
}

@Serializable
data class Episode(
    val episodeId: String,
    val displayName: String,
    val task: String,
    val objectName: String,
    val recordingState: RecordingState,
    val uploadState: UploadState,
    val recordingStartMonotonicTimestampNs: Long,
    val recordingEndMonotonicTimestampNs: Long? = null,
    val bundlePath: String
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
    val timestampSource: String = "REALTIME"
) {
    companion object {
        const val TARGET_FPS = 30
    }
}

@Serializable
data class IntRect(val left: Int, val top: Int, val right: Int, val bottom: Int)

@Serializable
data class RecordingResolution(val width: Int, val height: Int)

@Serializable
data class TimebaseMetadata(
    val cameraImuComparability: String = "VERIFIED"
)

@Serializable
data class CaptureLog(
    val id: Long = 0,
    val episodeId: String?,
    val reason: String,
    val summary: String,
    val timestampNs: Long,
    val frameCount: Long,
    val accelerometerCount: Long,
    val gyroscopeCount: Long,
    val rotationVectorCount: Long
)

@Serializable
data class FileManifest(
    val path: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val sha256: String
)

@Serializable
data class EpisodeMetadata(
    @SerialName("episode_id") val episodeId: String,
    val task: String,
    @SerialName("object") val objectName: String,
    val outcome: String,
    @SerialName("recording_start_monotonic_timestamp_ns") val recordingStartMonotonicTimestampNs: String,
    @SerialName("recording_end_monotonic_timestamp_ns") val recordingEndMonotonicTimestampNs: String,
    @SerialName("recording_duration_ns") val recordingDurationNs: String,
    val camera: CameraConfig,
    val timebase: TimebaseMetadata,
    val files: Map<String, FileManifest>
)

@Serializable
data class RemoteReceipt(
    @SerialName("episode_id") val episodeId: String,
    val result: String
)

@Serializable
data class UploadError(
    val code: String? = null,
    val message: String? = null
)
