package com.ssafy.s15p21a206.tiger.ui

import com.ssafy.s15p21a206.tiger.ui.upload.cancelUploadOnStop
import org.junit.Assert.assertEquals
import org.junit.Test

class UploadLifecycleTest {
    @Test
    fun `lifecycle stop cancels an upload that is still in flight`() {
        assertEquals(true, cancelUploadOnStop(uploadInFlight = true))
    }

    @Test
    fun `lifecycle stop leaves a finished upload alone`() {
        assertEquals(false, cancelUploadOnStop(uploadInFlight = false))
    }
}
