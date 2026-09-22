package com.ssafy.s15p21a206.tiger.data.local

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/**
 * 목록 조회가 Task와 Object를 어디서 읽는지 확인한다.
 *
 * `episode_markers` 집계로 역산하던 때에는 Episode가 0개인 Session의 두 이름이 빈 문자열로
 * 나왔다. 수집 시작 때 분명히 입력한 값인데, 목록에서 이름 없는 Task 묶음으로 떨어졌다.
 */
class SessionMetadataQueryTest {
    private lateinit var database: TigerDatabase

    @Before
    fun setUp() {
        database =
            Room
                .inMemoryDatabaseBuilder(
                    ApplicationProvider.getApplicationContext(),
                    TigerDatabase::class.java,
                ).build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun aSessionWithoutEpisodesKeepsItsTaskAndObject() {
        runBlocking {
            database.captureSessionDao().upsert(completedSession("no-episodes"))

            val summary =
                database
                    .captureSessionDao()
                    .observeCompletedSummaries()
                    .first()
                    .single()

            assertEquals(0, summary.completedEpisodeCount)
            assertEquals("mvi-check", summary.taskName)
            assertEquals("cup", summary.objectName)
        }
    }

    /** Episode 조인은 이제 개수를 세기 위해서만 남는다. 두 이름은 Session 행에서 온다. */
    @Test
    fun episodeRowsCountEpisodesWithoutSupplyingTheNames() {
        runBlocking {
            database.captureSessionDao().upsert(completedSession("with-episodes"))
            listOf("e1" to "COMPLETED", "e2" to "COMPLETED", "e3" to "INVALID_TRACKING").forEach { (episodeId, outcome) ->
                database.episodeMarkerDao().upsert(
                    EpisodeMarkerEntity(episodeId, "with-episodes", 1, 2, "stale task", "stale object", outcome),
                )
            }

            val summary =
                database
                    .captureSessionDao()
                    .observeCompletedSummaries()
                    .first()
                    .single()

            assertEquals(2, summary.completedEpisodeCount)
            assertEquals("mvi-check", summary.taskName)
            assertEquals("cup", summary.objectName)
        }
    }

    private fun completedSession(sessionId: String) =
        CaptureSessionEntity(
            sessionId = sessionId,
            displayNumber = 1,
            recordingState = "COMPLETED",
            uploadState = "LOCAL_ONLY",
            recordingStartNs = 1L,
            recordingEndNs = 2L,
            bundlePath = "/bundles/$sessionId",
            recordingStartEpochMs = 100L,
            task = "mvi-check",
            objectName = "cup",
        )
}
