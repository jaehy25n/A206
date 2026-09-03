package com.ssafy.s15p21a206.tiger.episode

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureSessionModelsTest {
    @Test
    fun `recording state follows session lifecycle`() {
        assertTrue(RecordingState.IDLE.canTransitionTo(RecordingState.INITIALIZING))
        assertTrue(RecordingState.INITIALIZING.canTransitionTo(RecordingState.READY))
        assertTrue(RecordingState.READY.canTransitionTo(RecordingState.FINALIZING))
        assertTrue(RecordingState.FINALIZING.canTransitionTo(RecordingState.COMPLETED))
        assertTrue(RecordingState.READY.canTransitionTo(RecordingState.INTERRUPTED))
        assertFalse(RecordingState.COMPLETED.canTransitionTo(RecordingState.READY))
    }

    @Test
    fun `episode outcome is terminal after active`() {
        assertTrue(EpisodeState.ACTIVE.canTransitionTo(EpisodeState.COMPLETED))
        assertTrue(EpisodeState.ACTIVE.canTransitionTo(EpisodeState.CANCELLED))
        assertTrue(EpisodeState.ACTIVE.canTransitionTo(EpisodeState.INVALID_TRACKING))
        assertFalse(EpisodeState.COMPLETED.canTransitionTo(EpisodeState.ACTIVE))
    }
}
