package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
import com.ssafy.s15p21a206.tiger.data.local.SessionSummaryEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.file.Files

class SessionRepositoryTest {
    @Test
    fun `legacy external completed bundle is excluded from listing and upload`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val managed = store.completedDirectory("managed").apply { mkdirs() }
            val dao = FakeSessionDao(listOf(session("managed", managed.path), session("legacy", root.resolve("legacy").path)))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            assertEquals(listOf("managed"), repository.observeCompleted().first().map(CaptureSession::sessionId))
            assertNull(repository.completedSource("legacy"))
            root.deleteRecursively()
        }
    }

    @Test
    fun `managed summary keeps only completed episode count`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val managed = store.completedDirectory("managed").apply { mkdirs() }
            val legacy = root.resolve("legacy")
            val summaries =
                listOf(
                    SessionSummaryEntity("managed", 2, "FAILED", 100, 1, 2, managed.path, 3, "Door opening"),
                    SessionSummaryEntity("legacy", 1, "LOCAL_ONLY", 100, 1, 2, legacy.path, 9),
                )
            val repository = SessionRepository(FakeSessionDao(emptyList(), summaries), FakeMarkerDao(), store)

            val summary = repository.observeCompletedSummaries().first().single()

            assertEquals("managed", summary.sessionId)
            assertEquals(3, summary.completedEpisodeCount)
            assertEquals("Door opening", summary.taskName)
            assertEquals(UploadState.FAILED, summary.uploadState)
            root.deleteRecursively()
        }
    }

    @Test
    fun `normalizing display numbers makes existing sessions sequential`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val oldest = store.completedDirectory("oldest").apply { mkdirs() }
            val newest = store.completedDirectory("newest").apply { mkdirs() }
            val dao =
                FakeSessionDao(
                    listOf(
                        session("newest", newest.path).copy(recordingStartEpochMs = 20),
                        session("oldest", oldest.path).copy(recordingStartEpochMs = 10),
                    ),
                )
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.normalizeDisplayNumbers()

            assertEquals(1, dao.session("oldest")?.displayNumber)
            assertEquals(2, dao.session("newest")?.displayNumber)
            assertEquals(3, repository.nextDisplayNumber())
            root.deleteRecursively()
        }
    }

    private fun session(
        id: String,
        path: String,
    ) = CaptureSessionEntity(id, 1, "COMPLETED", "LOCAL_ONLY", 1, 2, path)

    private class FakeSessionDao(
        sessions: List<CaptureSessionEntity>,
        private val summaries: List<SessionSummaryEntity> = emptyList(),
    ) : CaptureSessionDao {
        private val values = sessions.associateBy(CaptureSessionEntity::sessionId).toMutableMap()

        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> =
            flowOf(values.values.filter { it.recordingState == "COMPLETED" })

        override fun observeCompletedSummaries(): Flow<List<SessionSummaryEntity>> = flowOf(summaries)

        override suspend fun upsert(session: CaptureSessionEntity) {
            values[session.sessionId] = session
        }

        override suspend fun updateUploadState(
            sessionId: String,
            uploadState: String,
        ) = Unit

        override suspend fun failInterruptedUploads() = Unit

        override suspend fun updateExport(
            sessionId: String,
            state: String,
            treeUri: String?,
            failureReason: String?,
        ) = Unit

        override suspend fun completedSession(sessionId: String): CaptureSessionEntity? =
            values[sessionId]?.takeIf {
                it.recordingState ==
                    "COMPLETED"
            }

        override suspend fun session(sessionId: String): CaptureSessionEntity? = values[sessionId]

        override suspend fun activeSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity> =
            values.values.sortedWith(
                compareBy(
                    CaptureSessionEntity::recordingStartEpochMs,
                    CaptureSessionEntity::recordingStartNs,
                    CaptureSessionEntity::sessionId,
                ),
            )

        override suspend fun updateDisplayNumber(
            sessionId: String,
            displayNumber: Int,
        ) {
            values[sessionId] = requireNotNull(values[sessionId]).copy(displayNumber = displayNumber)
        }

        override suspend fun nextDisplayNumber(): Int = (values.values.maxOfOrNull(CaptureSessionEntity::displayNumber) ?: 0) + 1
    }

    private class FakeMarkerDao : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> = flowOf(emptyList())

        override suspend fun upsert(marker: EpisodeMarkerEntity) = Unit
    }
}
