package com.ssafy.s15p21a206.tiger.ui.session

import org.junit.Assert.assertEquals
import org.junit.Test

class VideoResolutionStateTest {
    @Test
    fun rotationFreeCaptureKeepsStoredSize() {
        assertEquals(
            VideoResolutionState.Available(1920, 1080),
            displayResolution(width = 1920, height = 1080, rotationDegrees = 0),
        )
    }

    @Test
    fun quarterTurnCaptureSwapsSizeToWhatThePlayerShows() {
        assertEquals(
            VideoResolutionState.Available(1080, 1920),
            displayResolution(width = 1920, height = 1080, rotationDegrees = 90),
        )
        assertEquals(
            VideoResolutionState.Available(1080, 1920),
            displayResolution(width = 1920, height = 1080, rotationDegrees = 270),
        )
    }

    @Test
    fun halfTurnCaptureKeepsStoredSize() {
        assertEquals(
            VideoResolutionState.Available(1280, 720),
            displayResolution(width = 1280, height = 720, rotationDegrees = 180),
        )
    }

    @Test
    fun missingRotationIsTreatedAsNone() {
        assertEquals(
            VideoResolutionState.Available(1280, 720),
            displayResolution(width = 1280, height = 720, rotationDegrees = null),
        )
    }

    @Test
    fun missingOrNonPositiveSizeIsUnavailable() {
        assertEquals(VideoResolutionState.Unavailable, displayResolution(null, 1080, 0))
        assertEquals(VideoResolutionState.Unavailable, displayResolution(1920, null, 0))
        assertEquals(VideoResolutionState.Unavailable, displayResolution(0, 1080, 0))
        assertEquals(VideoResolutionState.Unavailable, displayResolution(1920, -1, 0))
    }
}
