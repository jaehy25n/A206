package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.ProbeResult
import com.ssafy.s15p21a206.tiger.episode.UltraWideProbeResult

class UltraWideProbe(
    private val maxDurationMinutes: Int = 30,
) {
    fun evaluate(
        mainStable: Boolean,
        ultraWideOpened: Boolean,
        trackingStable: Boolean,
        elapsedMinutes: Int,
    ): ProbeResult {
        require(elapsedMinutes in 10..maxDurationMinutes) { "Probe must be timeboxed to 10–30 minutes" }
        return if (mainStable && ultraWideOpened && trackingStable) {
            ProbeResult(UltraWideProbeResult.UW_SUPPORTED)
        } else {
            ProbeResult(UltraWideProbeResult.UW_UNSUPPORTED_FOR_MVP, "Continue with main-only MVP")
        }
    }
}
