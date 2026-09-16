package com.ssafy.s15p21a206.tiger.capture

import android.view.Surface
import org.junit.Assert.assertEquals
import org.junit.Test

class CameraPreviewTransformTest {
    @Test
    fun `landscape needs a counter clockwise quarter turn`() {
        assertEquals(270, CameraPreviewTransform.rotationDegrees(90, Surface.ROTATION_90))
    }

    @Test
    fun `reverse landscape needs a clockwise quarter turn`() {
        assertEquals(90, CameraPreviewTransform.rotationDegrees(90, Surface.ROTATION_270))
    }

    @Test
    fun `natural orientation needs no correction on a ninety degree sensor`() {
        assertEquals(0, CameraPreviewTransform.rotationDegrees(90, Surface.ROTATION_0))
    }

    @Test
    fun `a different sensor orientation shifts the correction by the same amount`() {
        assertEquals(0, CameraPreviewTransform.rotationDegrees(180, Surface.ROTATION_90))
        assertEquals(180, CameraPreviewTransform.rotationDegrees(180, Surface.ROTATION_270))
    }

    @Test
    fun `result stays within a single turn`() {
        assertEquals(180, CameraPreviewTransform.rotationDegrees(0, Surface.ROTATION_90))
    }
}
