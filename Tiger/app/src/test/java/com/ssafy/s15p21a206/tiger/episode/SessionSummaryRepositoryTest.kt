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
import org.junit.Test
import java.nio.file.Files

class SessionSummaryRepositoryTest {
    @Test
    fun `managed summaries retain completed episode count and exclude legacy bundles`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val managed = store.completedDirectory("managed").apply { mkdirs() }
            val legacy = root.resolve("legacy")
            val repository =
                SessionRepository(
                    SummarySessionDao(
                        listOf(
                            SessionSummaryEntity("managed", 2, "FAILED", 100, 1, 2, managed.path, 3, "Door opening"),
                            SessionSummaryEntity("legacy", 1, "LOCAL_ONLY", 100, 1, 2, legacy.path, 9, "Legacy task"),
                        ),
                    ),
                    EmptyMarkerDao(),
                    store,
                )

            val summaries = repository.observeCompletedSummaries().first()

            assertEquals(1, summaries.size)
            assertEquals("managed", summaries.single().sessionId)
            assertEquals(3, summaries.single().completedEpisodeCount)
            assertEquals("Door opening", summaries.single().taskName)
            assertEquals(UploadState.FAILED, summaries.single().uploadState)
            root.deleteRecursively()
        }
    }

    private class SummarySessionDao(
        private val summaries: List<SessionSummaryEntity>,
    ) : CaptureSessionDao {
        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> = flowOf(emptyList())

        override fun observeCompletedSummaries(): Flow<List<SessionSummaryEntity>> = flowOf(summaries)

        override suspend fun upsert(session: CaptureSessionEntity) = Unit

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

        override suspend fun completedSession(sessionId: String): CaptureSessionEntity? = null

        override suspend fun session(sessionId: String): CaptureSessionEntity? = null

        override suspend fun activeSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun recoverableSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity> = emptyList()

        override suspend fun updateDisplayNumber(
            sessionId: String,
            displayNumber: Int,
        ) = Unit

        override suspend fun nextDisplayNumber(): Int = 1

        override suspend fun delete(sessionId: String) = Unit

        override suspend fun allSessionIds(): List<String> = emptyList()
    }

    private class EmptyMarkerDao : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> = flowOf(emptyList())

        override suspend fun upsert(marker: EpisodeMarkerEntity) = Unit

        override suspend fun deleteForSession(sessionId: String) = Unit
    }
}
