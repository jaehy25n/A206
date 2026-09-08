package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
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

    private fun session(
        id: String,
        path: String,
    ) = CaptureSessionEntity(id, 1, "COMPLETED", "LOCAL_ONLY", 1, 2, path)

    private class FakeSessionDao(
        sessions: List<CaptureSessionEntity>,
    ) : CaptureSessionDao {
        private val values = sessions.associateBy(CaptureSessionEntity::sessionId).toMutableMap()

        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> =
            flowOf(values.values.filter { it.recordingState == "COMPLETED" })

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
    }

    private class FakeMarkerDao : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> = flowOf(emptyList())

        override suspend fun upsert(marker: EpisodeMarkerEntity) = Unit
    }
}
