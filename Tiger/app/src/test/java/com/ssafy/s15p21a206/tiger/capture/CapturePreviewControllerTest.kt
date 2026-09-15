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

    @Test
    fun `preview can be reopened after a capture releases the camera`() {
        val runtime = FakePreviewRuntime()
        val controller = CapturePreviewController(CapturePreviewPreflight { null }, runtime)

        assertEquals(CapturePreviewState.Ready, controller.prepare())
        // 수집이 시작되면 같은 camera id를 넘기기 위해 프리뷰를 놓는다.
        controller.release()
        assertEquals(CapturePreviewState.Idle, controller.state)

        // 수집이 끝난 뒤 다시 열 때 prepare가 Ready로 단락되지 않고 실제로 재개돼야 한다.
        assertEquals(CapturePreviewState.Ready, controller.prepare())
        assertEquals(2, runtime.startCount)
    }

    private class FakePreviewRuntime(
        var failStart: Boolean = false,
    ) : PreviewRuntime {
        var started = false
        var released = false
        var recordingStarted = false
        var startCount = 0

        override fun startPreview() {
            if (failStart) error("Camera preview configuration failed")
            started = true
            startCount++
        }

        override fun releasePreview() {
            released = true
        }
    }
}
