package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.TrackingState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureSessionCoordinatorTest {
    private var now = 0L

    /** 실기기에서 측정된 ARCore pose 처리 지연(217 ms)에 해당한다. */
    private val poseLatencyNs = 217_000_000L
    private val writer = CountingWriter()
    private val closed = mutableListOf<EpisodeMarker>()
    private val coordinator = CaptureSessionCoordinator(MonotonicClock { now }, listOf(writer), onEpisodeClosed = closed::add)

    /** Session을 시작하고 Tracking을 안정화시켜 Episode를 시작할 수 있는 상태로 만든다. */
    private fun startReadySession() {
        coordinator.start(displayNumber = 1, bundlePath = "staging", task = "Door opening", objectName = "cup")
        coordinator.onTracking(true)
        now += CaptureSessionCoordinator.READY_GATE_NS
        coordinator.onTracking(true)
    }

    @Test fun `tracking ready gate enables episodes after one second`() {
        coordinator.start(displayNumber = 1, bundlePath = "staging", task = "Door opening", objectName = "cup")
        coordinator.onTracking(true)
        now += 999_999_999
        coordinator.onTracking(true)
        assertEquals(RecordingState.INITIALIZING, coordinator.session!!.recordingState)
        now += 1
        coordinator.onTracking(true)
        assertEquals(RecordingState.READY, coordinator.session!!.recordingState)
        assertEquals(EpisodeState.ACTIVE, coordinator.startEpisode("pick", "block").outcome)
    }

    @Test fun `tracking loss invalidates active episode at threshold`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        coordinator.onTracking(false)
        now += 500_000_000
        coordinator.onTracking(false)
        assertEquals(EpisodeState.INVALID_TRACKING, coordinator.latestClosedEpisode!!.outcome)
        assertEquals(1_500_000_000L, coordinator.latestClosedEpisode!!.endTimestampNs)
    }

    @Test fun `starting a session does not open an episode`() {
        coordinator.start(displayNumber = 1, bundlePath = "staging", task = "Door opening", objectName = "cup")
        assertNull(coordinator.activeEpisode)
        assertNull(coordinator.latestClosedEpisode)
        assertTrue(closed.isEmpty())
    }

    /**
     * Episode가 아니라 Session이 두 이름을 든다. Episode를 하나도 시작하지 않고 끝나는 Session이
     * 있고, 그때 두 이름을 아는 곳은 이 호출뿐이다.
     */
    @Test fun `a started session carries the task and object it was given`() {
        val session = coordinator.start(displayNumber = 1, bundlePath = "staging", task = "mvi-check", objectName = "cup")

        assertEquals("mvi-check", session.task)
        assertEquals("cup", session.objectName)
        assertEquals("mvi-check", coordinator.session!!.task)
        assertEquals("cup", coordinator.session!!.objectName)
    }

    @Test fun `a session cannot start without both names`() {
        assertThrows(IllegalStateException::class.java) {
            coordinator.start(displayNumber = 1, bundlePath = "staging", task = "mvi-check", objectName = " ")
        }
        assertNull(coordinator.session)
    }

    @Test fun `episodes repeat inside one session without restarting it`() {
        startReadySession()
        val sessionId = coordinator.session!!.sessionId
        repeat(3) {
            coordinator.startEpisode("pick", "block")
            now += 1_000_000_000
            coordinator.endEpisode()
            assertNull(coordinator.activeEpisode)
        }
        assertEquals(3, closed.size)
        assertTrue(closed.all { it.outcome == EpisodeState.COMPLETED && it.sessionId == sessionId })
        assertEquals(sessionId, coordinator.session!!.sessionId)
    }

    @Test fun `an active episode blocks session finalization`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        assertThrows(IllegalStateException::class.java) { coordinator.finalizeSession() }
    }

    @Test fun `episode start is rejected before the ready gate elapses`() {
        coordinator.start(displayNumber = 1, bundlePath = "staging", task = "Door opening", objectName = "cup")
        coordinator.onTracking(true)
        now += CaptureSessionCoordinator.READY_GATE_NS - 1
        coordinator.onTracking(true)
        assertThrows(IllegalStateException::class.java) { coordinator.startEpisode("pick", "block") }
    }

    @Test fun `brief tracking loss keeps the episode active`() {
        startReadySession()
        val episode = coordinator.startEpisode("pick", "block")
        coordinator.onTracking(false)
        now += CaptureSessionCoordinator.TRACKING_LOSS_NS - 1
        coordinator.onTracking(false)
        assertEquals(episode.episodeId, coordinator.activeEpisode?.episodeId)
        assertTrue(closed.isEmpty())
    }

    /**
     * Tracking 값이 false로 고정된 채 반복 호출되어야 0.5초 마감이 발화한다.
     * 값 변화에만 반응하는 구현은 유실이 이어지는 동안 다시 호출되지 않아 이 검사를 통과하지 못한다.
     */
    @Test fun `repeated calls with an unchanged loss signal still fire the deadline`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        val lossStartedNs = now
        coordinator.onTracking(false)
        repeat(6) {
            now += 100_000_000
            coordinator.onTracking(false)
        }
        assertEquals(1, closed.size)
        assertEquals(EpisodeState.INVALID_TRACKING, closed.single().outcome)
        assertEquals(lossStartedNs + CaptureSessionCoordinator.TRACKING_LOSS_NS, closed.single().endTimestampNs)
    }

    @Test fun `an automatically invalidated episode is not closed twice`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        coordinator.onTracking(false)
        now += CaptureSessionCoordinator.TRACKING_LOSS_NS
        coordinator.onTracking(false)
        assertThrows(IllegalArgumentException::class.java) { coordinator.endEpisode() }
        assertEquals(1, closed.size)
    }

    @Test fun `tracking recovery reopens episode collection after the ready gate`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        coordinator.onTracking(false)
        now += CaptureSessionCoordinator.TRACKING_LOSS_NS
        coordinator.onTracking(false)
        coordinator.onTracking(true)
        now += CaptureSessionCoordinator.READY_GATE_NS
        coordinator.onTracking(true)
        assertEquals(TrackingState.READY, coordinator.trackingState)
        assertEquals(EpisodeState.ACTIVE, coordinator.startEpisode("place", "block").outcome)
        assertNotNull(coordinator.session)
    }

    /**
     * 기록용 시작 시각은 pose 시각을 쓰므로 `arcore_poses.csv`의 첫 유실 행과 정확히 맞는다.
     * 판정은 단조 시계로만 하므로 pose 처리 지연이 게이트를 앞당기지 않는다.
     */
    @Test fun `the recorded loss start comes from the pose timestamp`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        now += 2_000_000_000
        val poseNs = now - poseLatencyNs
        coordinator.onTracking(false, poseNs)
        now += CaptureSessionCoordinator.TRACKING_LOSS_NS
        coordinator.onTracking(false, poseNs)
        assertEquals(poseNs + CaptureSessionCoordinator.TRACKING_LOSS_NS, closed.single().endTimestampNs)
    }

    /**
     * pose 지연이 판정에 섞이면 안 된다. 실제 유실이 0.4초일 때 지연 0.2초를 더해
     * 0.6초로 잘못 재면 Episode가 무효로 마감된다. FR-010 위반이다.
     */
    @Test fun `pose latency does not shorten the tracking loss gate`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        now += 2_000_000_000
        val poseNs = now - poseLatencyNs
        coordinator.onTracking(false, poseNs)
        now += 400_000_000
        coordinator.onTracking(false, poseNs)
        assertNotNull(coordinator.activeEpisode)
        assertTrue(closed.isEmpty())
    }

    @Test fun `a pose timestamp from another timebase is ignored`() {
        startReadySession()
        val episode = coordinator.startEpisode("pick", "block")
        // 카메라 timestamp 소스가 REALTIME이 아니면 단조 시계와 다른 기준의 값이 들어온다.
        coordinator.onTracking(false, episode.startTimestampNs - 1)
        now += CaptureSessionCoordinator.TRACKING_LOSS_NS
        coordinator.onTracking(false, episode.startTimestampNs - 1)
        // 폴백은 판정 시각이므로 Episode 시작 이후다.
        assertTrue(closed.single().endTimestampNs!! > episode.startTimestampNs)
    }

    @Test fun `a pose timestamp in the future is ignored`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        val detectedAt = now
        coordinator.onTracking(false, now + 10_000_000_000)
        now += CaptureSessionCoordinator.TRACKING_LOSS_NS
        coordinator.onTracking(false, now + 10_000_000_000)
        assertEquals(detectedAt + CaptureSessionCoordinator.TRACKING_LOSS_NS, closed.single().endTimestampNs)
    }

    @Test fun `a new session can start after the previous one is released`() {
        startReadySession()
        val first = coordinator.session!!.sessionId
        coordinator.finalizeSession()
        coordinator.release()
        coordinator.start(displayNumber = 2, bundlePath = "staging", task = "Door opening", objectName = "cup")
        assertNotEquals(first, coordinator.session!!.sessionId)
    }

    @Test fun `a released session does not carry its tracking verdict into the next one`() {
        startReadySession()
        coordinator.finalizeSession()
        coordinator.release()
        assertEquals(TrackingState.INITIALIZING, coordinator.trackingState)
        coordinator.start(displayNumber = 2, bundlePath = "staging", task = "Door opening", objectName = "cup")
        // 이전 Session의 안정화 결과를 물려받으면 gate 없이 Episode가 시작된다.
        assertThrows(IllegalStateException::class.java) { coordinator.startEpisode("pick", "block") }
        coordinator.onTracking(true)
        now += CaptureSessionCoordinator.READY_GATE_NS
        coordinator.onTracking(true)
        assertEquals(EpisodeState.ACTIVE, coordinator.startEpisode("pick", "block").outcome)
    }

    @Test fun `release clears the closed episode of the previous session`() {
        startReadySession()
        coordinator.startEpisode("pick", "block")
        coordinator.endEpisode()
        coordinator.release()
        assertNull(coordinator.latestClosedEpisode)
        assertNull(coordinator.activeEpisode)
    }

    @Test fun `fatal interruption finalizes writers once`() {
        coordinator.start(displayNumber = 1, bundlePath = "staging", task = "Door opening", objectName = "cup")
        coordinator.interrupt("camera")
        assertEquals(1, writer.started)
        assertEquals(1, writer.finalized)
        assertEquals(RecordingState.INTERRUPTED, coordinator.session!!.recordingState)
    }

    @Test fun `storage and timebase preflight block starts`() {
        assertTrue(SessionStartPreflight({ 100 }, 50).check(true) is SessionPreflightResult.Ready)
        assertFalse(SessionStartPreflight({ 49 }, 50).check(true) is SessionPreflightResult.Ready)
        assertFalse(SessionStartPreflight({ 100 }, 50).check(false) is SessionPreflightResult.Ready)
    }

    private class CountingWriter : SessionWriter {
        var started = 0
        var finalized = 0

        override fun start() {
            started++
        }

        override fun finalizeWriter() {
            finalized++
        }
    }
}
