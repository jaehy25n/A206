package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.TrackingState
import com.ssafy.s15p21a206.tiger.episode.UploadState
import java.io.File
import java.util.UUID

interface SessionWriter {
    fun start()

    fun finalizeWriter()
}

fun interface MonotonicClock {
    fun nowNs(): Long
}

class SessionStartPreflight(
    private val availableBytes: () -> Long,
    private val requiredBytes: Long,
) {
    fun check(cameraTimestampRealtime: Boolean): SessionPreflightResult =
        when {
            !cameraTimestampRealtime -> SessionPreflightResult.Failed("Camera timestamp source is not REALTIME")
            availableBytes() < requiredBytes -> SessionPreflightResult.Failed("Insufficient storage")
            else -> SessionPreflightResult.Ready
        }
}

sealed interface SessionPreflightResult {
    data object Ready : SessionPreflightResult

    data class Failed(
        val reason: String,
    ) : SessionPreflightResult
}

class CaptureSessionCoordinator(
    private val clock: MonotonicClock,
    private val writers: List<SessionWriter>,
    private val onInterrupted: (CaptureSession, SessionDiagnostic) -> Unit = { _, _ -> },
) {
    var session: CaptureSession? = null
        private set
    var activeEpisode: EpisodeMarker? = null
        private set
    var latestClosedEpisode: EpisodeMarker? = null
        private set
    var trackingState: TrackingState = TrackingState.INITIALIZING
        private set
    private var readySinceNs: Long? = null
    private var lossSinceNs: Long? = null

    fun start(
        sessionId: String = UUID.randomUUID().toString(),
        displayNumber: Int,
        bundlePath: String,
    ): CaptureSession {
        check(session == null) { "Session already exists" }
        writers.forEach(SessionWriter::start)
        return CaptureSession(
            sessionId,
            displayNumber,
            RecordingState.INITIALIZING,
            UploadState.LOCAL_ONLY,
            clock.nowNs(),
            bundlePath = bundlePath,
        ).also {
            session =
                it
        }
    }

    fun onTracking(
        isTracking: Boolean,
        failureReason: String? = null,
    ) {
        val now = clock.nowNs()
        if (isTracking) {
            lossSinceNs = null
            if (readySinceNs == null) readySinceNs = now
            if (now - readySinceNs!! >= READY_GATE_NS) trackingState = TrackingState.READY
            session?.takeIf { it.recordingState == RecordingState.INITIALIZING && trackingState == TrackingState.READY }?.let {
                session =
                    it.copy(recordingState = RecordingState.READY)
            }
        } else {
            readySinceNs = null
            trackingState = TrackingState.PAUSED
            if (lossSinceNs == null) lossSinceNs = now
            activeEpisode?.let { episode ->
                if (now - lossSinceNs!! >= TRACKING_LOSS_NS) {
                    latestClosedEpisode =
                        episode.copy(endTimestampNs = lossSinceNs!! + TRACKING_LOSS_NS, outcome = EpisodeState.INVALID_TRACKING)
                    activeEpisode = null
                }
            }
        }
    }

    fun startEpisode(
        task: String,
        objectName: String,
    ): EpisodeMarker {
        check(session?.recordingState == RecordingState.READY && trackingState == TrackingState.READY) { "Tracking is not ready" }
        check(task.isNotBlank() && objectName.isNotBlank()) { "Task and object are required" }
        check(activeEpisode == null) { "Episode is already active" }
        return EpisodeMarker(
            UUID.randomUUID().toString(),
            session!!.sessionId,
            clock.nowNs(),
            task = task,
            objectName = objectName,
            outcome = EpisodeState.ACTIVE,
        ).also {
            activeEpisode =
                it
        }
    }

    fun endEpisode(cancelled: Boolean = false): EpisodeMarker {
        val completed =
            requireNotNull(activeEpisode) {
                "No active episode"
            }.copy(endTimestampNs = clock.nowNs(), outcome = if (cancelled) EpisodeState.CANCELLED else EpisodeState.COMPLETED)
        activeEpisode = null
        latestClosedEpisode = completed
        return completed
    }

    fun interrupt(reason: String): CaptureSession {
        writers.forEach(SessionWriter::finalizeWriter)
        val interrupted =
            requireNotNull(
                session,
            ).copy(recordingState = RecordingState.INTERRUPTED, recordingEndMonotonicTimestampNs = clock.nowNs())
        session = interrupted
        onInterrupted(interrupted, SessionDiagnostic(reason, clock.nowNs()))
        return interrupted
    }

    fun finalizeSession(): CaptureSession {
        check(activeEpisode == null) { "End or cancel the active episode first" }
        writers.forEach(SessionWriter::finalizeWriter)
        return requireNotNull(
            session,
        ).copy(recordingState = RecordingState.FINALIZING, recordingEndMonotonicTimestampNs = clock.nowNs()).also {
            session =
                it
        }
    }

    companion object {
        const val READY_GATE_NS = 1_000_000_000L
        const val TRACKING_LOSS_NS = 500_000_000L
    }
}

data class SessionDiagnostic(
    val reason: String,
    val timestampNs: Long,
)

open class CsvWriter(
    private val file: File,
    private val header: String,
) : SessionWriter {
    override fun start() {
        file.parentFile?.mkdirs()
        if (!file.exists()) file.writeText("$header\n")
    }

    override fun finalizeWriter() = Unit

    fun append(row: String) {
        file.appendText("$row\n")
    }
}

class FrameTimestampWriter(
    file: File,
) : CsvWriter(file, "frame_number,timestamp_ns,timestamp_source") {
    fun append(
        frameNumber: Long,
        timestampNs: Long,
    ) = append("$frameNumber,$timestampNs,SENSOR_TIMESTAMP")
}

class ArCorePoseWriter(
    file: File,
) : CsvWriter(file, "android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason") {
    fun append(
        timestampNs: Long,
        values: List<Float>,
        tracking: String,
        failureReason: String?,
    ) = append("$timestampNs,${values.joinToString(",")},$tracking,${failureReason.orEmpty()}")
}
