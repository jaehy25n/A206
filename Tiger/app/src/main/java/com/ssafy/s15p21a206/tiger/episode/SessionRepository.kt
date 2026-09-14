package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
import com.ssafy.s15p21a206.tiger.data.local.SessionSummaryEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.io.File

class SessionRepository(
    private val sessionDao: CaptureSessionDao,
    private val markerDao: EpisodeMarkerDao,
    private val bundleStore: SessionBundleStore,
) : com.ssafy.s15p21a206.tiger.upload.UploadSessionStore {
    fun observeCompleted(): Flow<List<CaptureSession>> =
        sessionDao.observeCompleted().map { sessions ->
            sessions.filter { bundleStore.isManagedCompletedDirectory(it.bundlePath) }.map(CaptureSessionEntity::toCaptureSession)
        }

    fun observeCompletedSummaries(): Flow<List<SessionSummary>> =
        sessionDao.observeCompletedSummaries().map { summaries ->
            summaries
                .filter { bundleStore.isManagedCompletedDirectory(it.bundlePath) }
                .map(SessionSummaryEntity::toSessionSummary)
        }

    fun observeMarkers(sessionId: String): Flow<List<EpisodeMarker>> =
        markerDao.observeForSession(sessionId).map { markers -> markers.map(EpisodeMarkerEntity::toEpisodeMarker) }

    suspend fun save(session: CaptureSession) = sessionDao.upsert(session.toEntity())

    suspend fun save(marker: EpisodeMarker) = markerDao.upsert(marker.toEntity())

    override suspend fun updateUploadState(
        sessionId: String,
        state: UploadState,
    ) = sessionDao.updateUploadState(sessionId, state.name)

    override suspend fun completedSource(sessionId: String): CaptureSession? =
        sessionDao
            .completedSession(sessionId)
            ?.takeIf { bundleStore.isManagedCompletedDirectory(it.bundlePath) }
            ?.toCaptureSession()

    suspend fun failInterruptedUploads() = sessionDao.failInterruptedUploads()

    suspend fun exportFor(sessionId: String): SessionExport? =
        sessionDao
            .session(sessionId)
            ?.takeIf { bundleStore.isManagedCompletedDirectory(it.bundlePath) }
            ?.toSessionExport()

    suspend fun updateExport(export: SessionExport) =
        sessionDao.updateExport(export.sessionId, export.state.name, export.treeUri, export.failureReason)

    /**
     * staging에 남은 Session을 구제한다.
     *
     * 홈 버튼이나 화면 꺼짐으로 수집 화면이 중단되면 번들이 마감되지 못한 채 staging에 남는다.
     * 그때까지 수집된 영상·IMU·pose·Episode는 그 자체로 유효한 데이터이므로 버리지 않고
     * 정상 Session으로 마감한다. 마감할 수 없을 만큼 손상된 번들만 `INTERRUPTED`로 남긴다.
     */
    suspend fun recoverInterruptedStaging() {
        val stagingDirectories = bundleStore.interruptedStagingBundles().associateBy(File::getAbsolutePath)
        sessionDao.recoverableSessions().filter { it.bundlePath in stagingDirectories }.forEach { session ->
            val directory = stagingDirectories.getValue(session.bundlePath)
            val bundle = SessionBundle(session.sessionId, session.displayNumber, directory.name, directory)
            // 손상된 번들에서 예외가 나더라도 나머지 Session 구제를 막지 않는다.
            val result =
                runCatching { SessionFinalizer(bundleStore).finalize(bundle) }
                    .getOrElse { FinalizeResult.Failed(it.message.orEmpty()) }
            when (result) {
                is FinalizeResult.Completed ->
                    sessionDao.upsert(
                        session.copy(
                            recordingState = RecordingState.COMPLETED.name,
                            bundlePath = result.directory.absolutePath,
                        ),
                    )
                is FinalizeResult.Failed ->
                    sessionDao.upsert(session.copy(recordingState = RecordingState.INTERRUPTED.name))
            }
        }
    }

    suspend fun normalizeDisplayNumbers() {
        sessionDao.sessionsInCaptureOrder().forEachIndexed { index, session ->
            val displayNumber = index + 1
            if (session.displayNumber != displayNumber) {
                sessionDao.updateDisplayNumber(session.sessionId, displayNumber)
            }
        }
    }

    suspend fun nextDisplayNumber(): Int = sessionDao.nextDisplayNumber()
}

private fun CaptureSessionEntity.toCaptureSession() =
    CaptureSession(
        sessionId,
        displayNumber,
        RecordingState.valueOf(recordingState),
        UploadState.valueOf(uploadState),
        recordingStartNs,
        recordingEndNs,
        bundlePath,
        recordingStartEpochMs,
    )

private fun SessionSummaryEntity.toSessionSummary() =
    SessionSummary(
        sessionId,
        displayNumber,
        UploadState.valueOf(uploadState),
        recordingStartEpochMs,
        recordingStartNs,
        recordingEndNs,
        bundlePath,
        completedEpisodeCount,
        taskName,
    )

private fun CaptureSession.toEntity() =
    CaptureSessionEntity(
        sessionId,
        displayNumber,
        recordingState.name,
        uploadState.name,
        recordingStartMonotonicTimestampNs,
        recordingEndMonotonicTimestampNs,
        bundlePath,
        recordingStartEpochMs = recordingStartEpochMs,
    )

private fun EpisodeMarkerEntity.toEpisodeMarker() =
    EpisodeMarker(episodeId, sessionId, startTimestampNs, endTimestampNs, task, objectName, EpisodeState.valueOf(outcome))

private fun EpisodeMarker.toEntity() =
    EpisodeMarkerEntity(episodeId, sessionId, startTimestampNs, endTimestampNs, task, objectName, outcome.name)

private fun CaptureSessionEntity.toSessionExport() =
    SessionExport(sessionId, ExportState.valueOf(exportState), exportTreeUri, exportFailureReason)
