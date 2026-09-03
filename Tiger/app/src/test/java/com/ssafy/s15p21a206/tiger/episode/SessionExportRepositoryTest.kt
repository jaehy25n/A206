package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
import java.nio.file.Files
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SessionExportRepositoryTest {
    @Test
    fun `export state tree uri and failure reason survive repository recreation`() {
        runBlocking {
            val dao = FakeSessionDao()
            dao.upsert(CaptureSessionEntity("session", 1, "COMPLETED", "LOCAL_ONLY", 1, 2, "/completed/session"))
            val root = Files.createTempDirectory("store").toFile()

            SessionRepository(dao, FakeMarkerDao(), SessionBundleStore(root)).updateExport(
                SessionExport("session").start("content://tree", "attempt").fail("grant lost")
            )
            val restored = SessionRepository(dao, FakeMarkerDao(), SessionBundleStore(root)).exportFor("session")

            assertEquals(ExportState.EXPORT_FAILED, restored?.state)
            assertEquals("content://tree", restored?.treeUri)
            assertEquals("grant lost", restored?.failureReason)
            root.deleteRecursively()
        }
    }

    private class FakeSessionDao : CaptureSessionDao {
        private val sessions = mutableMapOf<String, CaptureSessionEntity>()
        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> = flowOf(sessions.values.filter { it.recordingState == "COMPLETED" })
        override suspend fun upsert(session: CaptureSessionEntity) { sessions[session.sessionId] = session }
        override suspend fun updateUploadState(sessionId: String, uploadState: String) { sessions[sessionId] = sessions.getValue(sessionId).copy(uploadState = uploadState) }
        override suspend fun updateExport(sessionId: String, state: String, treeUri: String?, failureReason: String?) { sessions[sessionId] = sessions.getValue(sessionId).copy(exportState = state, exportTreeUri = treeUri, exportFailureReason = failureReason) }
        override suspend fun completedSession(sessionId: String): CaptureSessionEntity? = sessions[sessionId]?.takeIf { it.recordingState == "COMPLETED" }
        override suspend fun session(sessionId: String): CaptureSessionEntity? = sessions[sessionId]
        override suspend fun activeSessions(): List<CaptureSessionEntity> = emptyList()
    }

    private class FakeMarkerDao : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> = flowOf(emptyList())
        override suspend fun upsert(marker: EpisodeMarkerEntity) = Unit
    }
}
