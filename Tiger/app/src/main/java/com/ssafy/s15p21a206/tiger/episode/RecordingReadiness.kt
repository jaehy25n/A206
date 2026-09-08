package com.ssafy.s15p21a206.tiger.episode

sealed interface RecordingReadiness {
    data object Ready : RecordingReadiness

    data object InsufficientStorage : RecordingReadiness

    data class PreflightFailed(
        val reason: String,
    ) : RecordingReadiness

    val canStart: Boolean get() = this is Ready
}
