package com.ssafy.s15p21a206.tiger.episode

import java.io.File

object EpisodeBundleValidator {
    private val expectedCsvHeaders = mapOf(
        EpisodeBundle.FRAME_TIMESTAMPS_FILE to "frame_number,timestamp_ns,timestamp_source",
        EpisodeBundle.ACCELEROMETER_FILE to "timestamp_ns,x,y,z,accuracy",
        EpisodeBundle.GYROSCOPE_FILE to "timestamp_ns,x,y,z,accuracy",
        EpisodeBundle.ROTATION_VECTOR_FILE to "timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy"
    )

    fun validate(directory: File): BundleValidationResult {
        if (!directory.isDirectory) return BundleValidationResult.Invalid("bundle directory is missing")
        val video = File(directory, EpisodeBundle.VIDEO_FILE)
        if (!video.isFile || video.length() == 0L) return BundleValidationResult.Invalid("video is missing")
        for ((fileName, header) in expectedCsvHeaders) {
            val file = File(directory, fileName)
            if (!file.isFile || file.length() == 0L || file.bufferedReader().use { it.readLine() } != header) {
                return BundleValidationResult.Invalid("invalid $fileName")
            }
        }
        val metadata = File(directory, EpisodeBundle.METADATA_FILE)
        if (!metadata.isFile || metadata.length() == 0L) return BundleValidationResult.Invalid("metadata commit marker is missing")
        return BundleValidationResult.Valid
    }
}

sealed interface BundleValidationResult {
    val isValid: Boolean

    data object Valid : BundleValidationResult {
        override val isValid = true
    }

    data class Invalid(val reason: String) : BundleValidationResult {
        override val isValid = false
    }
}
