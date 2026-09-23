package com.ssafy.s15p21a206.tiger.ui.session

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
import com.ssafy.s15p21a206.tiger.data.local.SessionSummaryEntity
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.episode.UploadState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

/**
 * 내보내기·전송·삭제의 조율을 확인한다.
 *
 * 이 코드는 이전까지 Composable 안에 있어 테스트가 없었다. 아래 동작들은 화면 밖으로 나와야
 * 확인할 수 있는 것들이다.
 */
class SessionOperationsTest {
    private val immediate = Dispatchers.Unconfined

    private fun operations(
        dao: CaptureSessionDao,
        uploadService: com.ssafy.s15p21a206.tiger.upload.SessionUploadService? = null,
    ): Pair<SessionOperations, SessionRepository> {
        val root = Files.createTempDirectory("session-operations").toFile()
        val store = SessionBundleStore(root)
        val repository = SessionRepository(dao, FakeMarkerDao(), store)
        return SessionOperations(
            repository = repository,
            uploadService = uploadService,
            scope = CoroutineScope(immediate),
            ioDispatcher = immediate,
        ) to repository
    }

    @Test
    fun `a session being uploaded is refused instead of deleted`() {
        val (operations, _) = operations(FakeSessionDao(entity(uploadState = UploadState.UPLOADING)))
        var navigatedAway = false

        operations.delete("session") { navigatedAway = true }

        assertEquals(SessionDeleteFailure.UploadInProgress, operations.deleteFailure)
        // 거절당했으면 상세에 머무른다. 지워지지 않은 세션의 화면을 떠날 이유가 없다.
        assertFalse(navigatedAway)
    }

    @Test
    fun `deleting a session tells the caller so it can leave the detail screen`() {
        val (operations, _) = operations(FakeSessionDao(entity(uploadState = UploadState.LOCAL_ONLY)))
        var navigatedAway = false

        operations.delete("session") { navigatedAway = true }

        assertNull(operations.deleteFailure)
        assertTrue(navigatedAway)
    }

    @Test
    fun `a storage failure is reported without leaving the screen`() {
        val (operations, _) = operations(ThrowingSessionDao())
        var navigatedAway = false

        operations.delete("session") { navigatedAway = true }

        assertEquals(SessionDeleteFailure.Unavailable, operations.deleteFailure)
        assertFalse(navigatedAway)
    }

    @Test
    fun `a refusal is cleared once a later delete succeeds`() {
        val (operations, _) = operations(FakeSessionDao(entity(uploadState = UploadState.UPLOADING)))
        operations.delete("session") {}
        assertNotNull(operations.deleteFailure)

        val (fresh, _) = operations(FakeSessionDao(entity(uploadState = UploadState.LOCAL_ONLY)))
        fresh.delete("session") {}

        assertNull(fresh.deleteFailure)
    }

    @Test
    fun `there is nothing to upload when no endpoint was built in`() {
        val (operations, _) = operations(FakeSessionDao(entity(uploadState = UploadState.LOCAL_ONLY)))

        assertFalse(operations.canUpload)
        // 걸 곳이 없으면 아무 일도 하지 않는다. 호출한 쪽이 이유를 대신 보여 준다.
        operations.upload("session")
        assertFalse(operations.uploadInFlight)
        assertNull(operations.uploadFailureReason)
    }

    private fun entity(uploadState: UploadState) =
        CaptureSessionEntity(
            sessionId = "session",
            displayNumber = 1,
            recordingState = RecordingState.COMPLETED.name,
            uploadState = uploadState.name,
            recordingStartNs = 0L,
            recordingEndNs = 1L,
            bundlePath = "/does/not/exist",
        )

    private open class FakeSessionDao(
        private val stored: CaptureSessionEntity?,
    ) : CaptureSessionDao {
        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> = flowOf(listOfNotNull(stored))

        override fun observeCompletedSummaries(): Flow<List<SessionSummaryEntity>> = flowOf(emptyList())

        override suspend fun upsert(session: CaptureSessionEntity) = Unit

        override suspend fun updateUploadState(
            sessionId: String,
            uploadState: String,
        ) = Unit

        override suspend fun failInterruptedUploads() = Unit

        override suspend fun completedSession(sessionId: String): CaptureSessionEntity? = stored

        override suspend fun session(sessionId: String): CaptureSessionEntity? = stored

        override suspend fun activeSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun recoverableSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity> = listOfNotNull(stored)

        override suspend fun updateDisplayNumber(
            sessionId: String,
            displayNumber: Int,
        ) = Unit

        override suspend fun nextDisplayNumber(): Int = 1

        override suspend fun delete(sessionId: String) = Unit

        override suspend fun allSessionIds(): List<String> = listOfNotNull(stored?.sessionId)
    }

    private class ThrowingSessionDao : FakeSessionDao(null) {
        override suspend fun session(sessionId: String): CaptureSessionEntity = error("저장소를 열 수 없습니다")
    }

    private class FakeMarkerDao : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> = flowOf(emptyList())

        override suspend fun upsert(marker: EpisodeMarkerEntity) = Unit

        override suspend fun deleteForSession(sessionId: String) = Unit
    }
}
