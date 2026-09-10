package com.ssafy.s15p21a206.tiger.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CapturePreviewControllerTest {
    @Test
    fun `permission ar and camera preflight failures do not start preview`() {
        listOf("Camera permission is required", "ARCore is unavailable", "Rear camera is unavailable").forEach { reason ->
            val runtime = FakePreviewRuntime()
            val controller = CapturePreviewController(CapturePreviewPreflight { reason }, runtime)

            assertEquals(CapturePreviewState.Failed(reason), controller.prepare())
            assertFalse(runtime.started)
        }
    }

    @Test
    fun `preview preparation is independent from recording session creation`() {
        val runtime = FakePreviewRuntime()
        val controller = CapturePreviewController(CapturePreviewPreflight { null }, runtime)

        assertEquals(CapturePreviewState.Ready, controller.prepare())
        assertTrue(runtime.started)
        assertFalse(runtime.recordingStarted)
    }

    @Test
    fun `release returns preview to idle and supports recovery after failure`() {
        val runtime = FakePreviewRuntime(failStart = true)
        val controller = CapturePreviewController(CapturePreviewPreflight { null }, runtime)

        assertTrue(controller.prepare() is CapturePreviewState.Failed)
        runtime.failStart = false
        controller.release()

        assertEquals(CapturePreviewState.Ready, controller.prepare())
        assertTrue(runtime.released)
    }

    private class FakePreviewRuntime(
        var failStart: Boolean = false,
    ) : PreviewRuntime {
        var started = false
        var released = false
        var recordingStarted = false

        override fun startPreview() {
            if (failStart) error("Camera preview configuration failed")
            started = true
        }

        override fun releasePreview() {
            released = true
        }
    }
}
