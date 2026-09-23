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

class CaptureSessionCoordinator(
    private val clock: MonotonicClock,
    private val writers: List<SessionWriter>,
    private val onInterrupted: (CaptureSession, SessionDiagnostic) -> Unit = { _, _ -> },
    // 사용자 종료와 Tracking 유실 자동 마감이 같은 출구를 쓰도록 한다.
    private val onEpisodeClosed: (EpisodeMarker) -> Unit = {},
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
    private var lossDetectedAtNs: Long? = null
    private var lossObservedAtNs: Long? = null

    /**
     * Session을 연다. [task]와 [objectName]은 이 Session 전체에 적용되는 두 이름이다.
     *
     * Episode 시작 때 다시 받는 것과 같은 값이지만 여기서도 받는다. Episode를 하나도 시작하지
     * 않고 끝나는 Session이 있고, 그때 두 이름을 아는 곳은 이 호출뿐이다.
     */
    fun start(
        sessionId: String = UUID.randomUUID().toString(),
        displayNumber: Int,
        bundlePath: String,
        task: String,
        objectName: String,
    ): CaptureSession {
        check(session == null) { "Session already exists" }
        check(task.isNotBlank() && objectName.isNotBlank()) { "Task and object are required" }
        writers.forEach(SessionWriter::start)
        return CaptureSession(
            sessionId,
            displayNumber,
            RecordingState.INITIALIZING,
            UploadState.LOCAL_ONLY,
            clock.nowNs(),
            bundlePath = bundlePath,
            task = task,
            objectName = objectName,
        ).also {
            session =
                it
        }
    }

    /**
     * Tracking 신호를 전달한다. 값이 변하지 않아도 반복 호출되어야 시간 기반 판정이 발화한다.
     *
     * [observedAtNs]는 이 신호를 만든 ARCore 프레임의 카메라 시각이다. 주어지면 유실 구간의
     * **기록용** 시작 시각으로 쓰여 `arcore_poses.csv`의 첫 유실 행과 정확히 맞는다.
     * 판정용 경과 시간은 항상 [clock]으로만 재므로, pose 처리 지연이 게이트를 앞당기지 않는다.
     */
    fun onTracking(
        isTracking: Boolean,
        observedAtNs: Long? = null,
        failureReason: String? = null,
    ) {
        val now = clock.nowNs()
        if (isTracking) {
            lossDetectedAtNs = null
            lossObservedAtNs = null
            if (readySinceNs == null) readySinceNs = now
            if (now - readySinceNs!! >= READY_GATE_NS) trackingState = TrackingState.READY
            session?.takeIf { it.recordingState == RecordingState.INITIALIZING && trackingState == TrackingState.READY }?.let {
                session =
                    it.copy(recordingState = RecordingState.READY)
            }
        } else {
            readySinceNs = null
            trackingState = TrackingState.PAUSED
            if (lossDetectedAtNs == null) {
                lossDetectedAtNs = now
                lossObservedAtNs = trustedObservation(observedAtNs, now)
            }
            activeEpisode?.let { episode ->
                if (now - lossDetectedAtNs!! >= TRACKING_LOSS_NS) {
                    val lossStartedNs = lossObservedAtNs ?: lossDetectedAtNs!!
                    val invalidated =
                        episode.copy(endTimestampNs = lossStartedNs + TRACKING_LOSS_NS, outcome = EpisodeState.INVALID_TRACKING)
                    activeEpisode = null
                    latestClosedEpisode = invalidated
                    onEpisodeClosed(invalidated)
                }
            }
        }
    }

    /**
     * 카메라 시각을 기록용으로 쓸 수 있을 때만 돌려준다.
     *
     * 카메라 timestamp 소스가 `REALTIME`이 아닌 기기에서는 [observedAtNs]가 단조 시계와 다른
     * 시간축이라 그대로 쓰면 엉뚱한 값이 기록된다. 진행 중 Episode의 시작보다 이르거나 현재보다
     * 미래인 값은 다른 시간축으로 보고 버린다.
     */
    private fun trustedObservation(
        observedAtNs: Long?,
        now: Long,
    ): Long? {
        val candidate = observedAtNs ?: return null
        if (candidate > now) return null
        activeEpisode?.let { if (candidate < it.startTimestampNs) return null }
        return candidate
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

    fun endEpisode(): EpisodeMarker {
        val completed =
            requireNotNull(activeEpisode) {
                "No active episode"
            }.copy(endTimestampNs = clock.nowNs(), outcome = EpisodeState.COMPLETED)
        activeEpisode = null
        latestClosedEpisode = completed
        onEpisodeClosed(completed)
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

    /**
     * Session 경계를 닫아 다음 Session을 시작할 수 있게 한다.
     *
     * Tracking 판정 상태까지 함께 되돌린다. 이월되면 새 Session이 이전 Session의 안정화 결과를
     * 물려받아 READY gate 없이 Episode를 시작할 수 있게 된다.
     */
    fun release() {
        session = null
        activeEpisode = null
        latestClosedEpisode = null
        trackingState = TrackingState.INITIALIZING
        readySinceNs = null
        lossDetectedAtNs = null
        lossObservedAtNs = null
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
    // 영상 녹화가 실제로 진행 중인 구간만 기록한다. 카메라 스레드가 읽고 수집 수명주기가 쓴다.
    @Volatile var recording: Boolean = false

    private var nextFrameNumber = 0L
    private var lastTimestampNs: Long? = null

    /**
     * 프레임 하나를 기록하고 실제로 기록했는지 돌려준다.
     * 같은 timestamp가 연속으로 도착하면 중복으로 보고 버린다. ARCore SharedCamera 구성에서
     * 동일한 CaptureCallback이 두 번 등록되어 한 프레임이 두 번 전달될 수 있기 때문이다.
     */
    fun record(timestampNs: Long): Boolean {
        if (!recording || timestampNs == lastTimestampNs) return false
        lastTimestampNs = timestampNs
        append("${nextFrameNumber++},$timestampNs,SENSOR_TIMESTAMP")
        return true
    }
}
