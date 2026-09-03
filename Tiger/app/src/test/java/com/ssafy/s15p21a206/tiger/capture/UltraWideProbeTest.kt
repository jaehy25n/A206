package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.UltraWideProbeResult
import org.junit.Assert.assertEquals
import org.junit.Test

class UltraWideProbeTest {
    @Test fun `failed probe preserves main only fallback`() {
        assertEquals(UltraWideProbeResult.UW_UNSUPPORTED_FOR_MVP, UltraWideProbe().evaluate(true, false, true, 10).result)
    }
}
