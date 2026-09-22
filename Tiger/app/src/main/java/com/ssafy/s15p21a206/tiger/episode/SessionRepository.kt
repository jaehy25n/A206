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

    /**
     * Session을 기기에서 지운다.
     *
     * 서버에는 DELETE API가 없다. 이미 올린 Session의 사본은 서버에 그대로 남으므로, 이 동작은
     * 기기 저장 공간을 비우는 것이지 업로드를 취소하는 것이 아니다.
     *
     * 색인을 먼저 지우고 디렉터리를 지운다. 디렉터리 삭제가 실패해도 남는 것은 고아 디렉터리뿐이고
     * 다음 실행의 [purgeOrphanBundles]가 회수한다. 반대 순서였다면 번들이 사라진 Session이 목록에
     * 남아 재생도 업로드도 되지 않는다.
     */
    suspend fun delete(sessionId: String): SessionDeleteResult {
        val session = sessionDao.session(sessionId) ?: return SessionDeleteResult.DELETED
        // 업로드 중인 번들은 업로드가 읽고 있다. 먼저 끝나거나 실패해야 지울 수 있다.
        if (session.uploadState == UploadState.UPLOADING.name) return SessionDeleteResult.UPLOAD_IN_PROGRESS
        markerDao.deleteForSession(sessionId)
        sessionDao.delete(sessionId)
        return if (bundleStore.deleteCompletedBundle(session.bundlePath)) {
            SessionDeleteResult.DELETED
        } else {
            SessionDeleteResult.BUNDLE_RETAINED
        }
    }

    /**
     * 색인에 없는 번들 디렉터리를 회수한다.
     *
     * 삭제 도중 디렉터리를 지우지 못했거나 앱이 끝난 경우에 남는다. 목록에는 이미 보이지 않으므로
     * 저장 공간만 차지한다.
     */
    suspend fun purgeOrphanBundles() {
        val known = sessionDao.allSessionIds().toSet()
        bundleStore.orphanCompletedBundles(known).forEach(File::deleteRecursively)
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

/** [SessionRepository.delete]의 결과. */
enum class SessionDeleteResult {
    /** 색인과 번들이 모두 사라졌다. */
    DELETED,

    /** 색인은 지웠지만 디렉터리가 남았다. 목록에서는 사라지며, 다음 실행이 디렉터리를 회수한다. */
    BUNDLE_RETAINED,

    /** 업로드가 진행 중이라 지우지 않았다. */
    UPLOAD_IN_PROGRESS,
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
        task,
        objectName,
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
        objectName,
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
        task = task,
        objectName = objectName,
    )

private fun EpisodeMarkerEntity.toEpisodeMarker() =
    EpisodeMarker(episodeId, sessionId, startTimestampNs, endTimestampNs, task, objectName, EpisodeState.valueOf(outcome))

private fun EpisodeMarker.toEntity() =
    EpisodeMarkerEntity(episodeId, sessionId, startTimestampNs, endTimestampNs, task, objectName, outcome.name)

private fun CaptureSessionEntity.toSessionExport() =
    SessionExport(sessionId, ExportState.valueOf(exportState), exportTreeUri, exportFailureReason)
