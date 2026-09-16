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
 * 재부팅을 거치면 `recordingStartNs`가 0부터 다시 시작한다. 재부팅 이후에 수집한 Session이
 * 더 작은 `recordingStartNs`를 갖게 되므로, 이 값으로 정렬하면 오래된 Session이 위로 올라온다.
 * 절대 시각으로 정렬하는지 확인한다.
 */
class CaptureSessionOrderTest {
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
    fun completedSessionsAreOrderedByWallClockAcrossReboot() {
        runBlocking {
            val dao = database.captureSessionDao()
            dao.upsert(completedSession(sessionId = "before-reboot", startEpochMs = 1_000L, startNs = 9_000_000_000L))
            dao.upsert(completedSession(sessionId = "after-reboot", startEpochMs = 2_000L, startNs = 1_000_000_000L))

            val sessions = dao.observeCompleted().first()
            val summaries = dao.observeCompletedSummaries().first()

            assertEquals(listOf("after-reboot", "before-reboot"), sessions.map { it.sessionId })
            assertEquals(listOf("after-reboot", "before-reboot"), summaries.map { it.sessionId })
        }
    }

    private fun completedSession(
        sessionId: String,
        startEpochMs: Long,
        startNs: Long,
    ) = CaptureSessionEntity(
        sessionId = sessionId,
        displayNumber = 1,
        recordingState = "COMPLETED",
        uploadState = "LOCAL_ONLY",
        recordingStartNs = startNs,
        recordingEndNs = startNs + 1_000_000_000L,
        bundlePath = "/bundles/$sessionId",
        recordingStartEpochMs = startEpochMs,
    )
}
