package com.ssafy.s15p21a206.tiger.episode

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EpisodeModelsTest {
    @Test
    fun `recording can only complete or interrupt from recording`() {
        assertTrue(RecordingState.RECORDING.canTransitionTo(RecordingState.COMPLETED))
        assertTrue(RecordingState.RECORDING.canTransitionTo(RecordingState.INTERRUPTED))
        assertFalse(RecordingState.COMPLETED.canTransitionTo(RecordingState.RECORDING))
        assertFalse(RecordingState.INTERRUPTED.canTransitionTo(RecordingState.COMPLETED))
    }
}
