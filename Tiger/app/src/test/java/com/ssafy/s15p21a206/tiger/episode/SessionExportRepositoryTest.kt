package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EXPORT_MIGRATION_SQL
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
import com.ssafy.s15p21a206.tiger.data.local.SessionSummaryEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

class SessionExportRepositoryTest {
    @Test
    fun `migration preserves export state tree uri and failure reason columns`() {
        assertEquals(3, EXPORT_MIGRATION_SQL.size)
        assertTrue(EXPORT_MIGRATION_SQL.any { it.contains("exportState") && it.contains("NOT_EXPORTED") })
        assertTrue(EXPORT_MIGRATION_SQL.any { it.contains("exportTreeUri") })
        assertTrue(EXPORT_MIGRATION_SQL.any { it.contains("exportFailureReason") })
    }

    @Test
    fun `export state tree uri and failure reason survive repository recreation`() {
        runBlocking {
            val dao = FakeSessionDao()
            val root = Files.createTempDirectory("store").toFile()
            val store = SessionBundleStore(root)
            val completed = store.completedDirectory("session").apply { mkdirs() }
            dao.upsert(CaptureSessionEntity("session", 1, "COMPLETED", "LOCAL_ONLY", 1, 2, completed.path))

            SessionRepository(dao, FakeMarkerDao(), store).updateExport(
                SessionExport("session").start("content://tree", "attempt").fail("grant lost"),
            )
            val restored = SessionRepository(dao, FakeMarkerDao(), store).exportFor("session")

            assertEquals(ExportState.EXPORT_FAILED, restored?.state)
            assertEquals("content://tree", restored?.treeUri)
            assertEquals("grant lost", restored?.failureReason)
            root.deleteRecursively()
        }
    }

    private class FakeSessionDao : CaptureSessionDao {
        private val sessions = mutableMapOf<String, CaptureSessionEntity>()

        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> =
            flowOf(sessions.values.filter { it.recordingState == "COMPLETED" })

        override fun observeCompletedSummaries(): Flow<List<SessionSummaryEntity>> = flowOf(emptyList())

        override suspend fun upsert(session: CaptureSessionEntity) {
            sessions[session.sessionId] = session
        }

        override suspend fun updateUploadState(
            sessionId: String,
            uploadState: String,
        ) {
            sessions[sessionId] =
                sessions.getValue(sessionId).copy(uploadState = uploadState)
        }

        override suspend fun failInterruptedUploads() = Unit

        override suspend fun updateExport(
            sessionId: String,
            state: String,
            treeUri: String?,
            failureReason: String?,
        ) {
            sessions[sessionId] =
                sessions.getValue(sessionId).copy(exportState = state, exportTreeUri = treeUri, exportFailureReason = failureReason)
        }

        override suspend fun completedSession(sessionId: String): CaptureSessionEntity? =
            sessions[sessionId]?.takeIf {
                it.recordingState ==
                    "COMPLETED"
            }

        override suspend fun session(sessionId: String): CaptureSessionEntity? = sessions[sessionId]

        override suspend fun activeSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun recoverableSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity> = sessions.values.toList()

        override suspend fun updateDisplayNumber(
            sessionId: String,
            displayNumber: Int,
        ) {
            sessions[sessionId] = sessions.getValue(sessionId).copy(displayNumber = displayNumber)
        }

        override suspend fun nextDisplayNumber(): Int = (sessions.values.maxOfOrNull(CaptureSessionEntity::displayNumber) ?: 0) + 1

        override suspend fun delete(sessionId: String) = Unit

        override suspend fun allSessionIds(): List<String> = sessions.keys.toList()
    }

    private class FakeMarkerDao : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> = flowOf(emptyList())

        override suspend fun upsert(marker: EpisodeMarkerEntity) = Unit

        override suspend fun deleteForSession(sessionId: String) = Unit
    }
}
