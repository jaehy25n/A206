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
                            SessionSummaryEntity("managed", 2, "FAILED", 100, 1, 2, managed.path, 3, "Door opening", "cup"),
                            SessionSummaryEntity("legacy", 1, "LOCAL_ONLY", 100, 1, 2, legacy.path, 9, "Legacy task", "bottle"),
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
            assertEquals("cup", summaries.single().objectName)
            assertEquals(UploadState.FAILED, summaries.single().uploadState)
            root.deleteRecursively()
        }
    }

    /**
     * Episode를 하나도 시작하지 않은 Session도 두 이름을 갖는다.
     *
     * 두 이름을 `episode_markers`에서 역산하던 때에는 이 Session이 둘 다 빈 문자열로 나와, 수집
     * 시작 때 분명히 입력한 값이 이름 없는 Task 묶음으로 떨어졌다. 이제 값의 출처가 Session 행이라
     * Episode 수와 무관하다. 쿼리가 실제로 `sessions` 컬럼을 읽는지는 계측 테스트가 확인한다.
     */
    @Test
    fun `a session without episodes still carries its task and object`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val managed = store.completedDirectory("no-episode").apply { mkdirs() }
            val repository =
                SessionRepository(
                    SummarySessionDao(
                        listOf(SessionSummaryEntity("no-episode", 1, "LOCAL_ONLY", 100, 1, 2, managed.path, 0, "mvi-check", "cup")),
                    ),
                    EmptyMarkerDao(),
                    store,
                )

            val summary = repository.observeCompletedSummaries().first().single()

            assertEquals(0, summary.completedEpisodeCount)
            assertEquals("mvi-check", summary.taskName)
            assertEquals("cup", summary.objectName)
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
