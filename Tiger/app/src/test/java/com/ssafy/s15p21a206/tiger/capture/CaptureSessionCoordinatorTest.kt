package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureSessionCoordinatorTest {
    private var now = 0L
    private val writer = CountingWriter()
    private val coordinator = CaptureSessionCoordinator(MonotonicClock { now }, listOf(writer))

    @Test fun `tracking ready gate enables episodes after one second`() {
        coordinator.start(displayNumber = 1, bundlePath = "staging")
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
        coordinator.start(displayNumber = 1, bundlePath = "staging")
        coordinator.onTracking(true); now += 1_000_000_000; coordinator.onTracking(true)
        coordinator.startEpisode("pick", "block")
        coordinator.onTracking(false); now += 500_000_000; coordinator.onTracking(false)
        assertEquals(EpisodeState.INVALID_TRACKING, coordinator.latestClosedEpisode!!.outcome)
        assertEquals(1_500_000_000L, coordinator.latestClosedEpisode!!.endTimestampNs)
    }

    @Test fun `fatal interruption finalizes writers once`() {
        coordinator.start(displayNumber = 1, bundlePath = "staging")
        coordinator.interrupt("camera")
        assertEquals(1, writer.started); assertEquals(1, writer.finalized)
        assertEquals(RecordingState.INTERRUPTED, coordinator.session!!.recordingState)
    }

    @Test fun `storage and timebase preflight block starts`() {
        assertTrue(SessionStartPreflight({ 100 }, 50).check(true) is SessionPreflightResult.Ready)
        assertFalse(SessionStartPreflight({ 49 }, 50).check(true) is SessionPreflightResult.Ready)
        assertFalse(SessionStartPreflight({ 100 }, 50).check(false) is SessionPreflightResult.Ready)
    }

    private class CountingWriter : SessionWriter { var started = 0; var finalized = 0; override fun start() { started++ }; override fun finalizeWriter() { finalized++ } }
}
