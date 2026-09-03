package com.ssafy.s15p21a206.tiger.episode

import java.io.File

object SessionBundleValidator {
    private val requiredCsvHeaders = mapOf(
        SessionBundle.MAIN_FRAME_TIMESTAMPS_FILE to "frame_number,timestamp_ns,timestamp_source",
        SessionBundle.ACCELEROMETER_FILE to "timestamp_ns,x,y,z,accuracy",
        SessionBundle.GYROSCOPE_FILE to "timestamp_ns,x,y,z,accuracy",
        SessionBundle.ROTATION_VECTOR_FILE to "timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy",
        SessionBundle.ARCORE_POSES_FILE to "android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason",
        SessionBundle.EPISODES_FILE to "episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome"
    )

    fun validate(directory: File, includesUltraWide: Boolean = false): BundleValidationResult {
        if (!directory.isDirectory) return BundleValidationResult.Invalid("bundle directory is missing")
        if (!File(directory, SessionBundle.MAIN_VIDEO_FILE).hasContent()) return BundleValidationResult.Invalid("main video is missing")
        for ((fileName, header) in requiredCsvHeaders) if (!File(directory, fileName).hasHeader(header)) return BundleValidationResult.Invalid("invalid $fileName")
        if (includesUltraWide && (!File(directory, SessionBundle.ULTRAWIDE_VIDEO_FILE).hasContent() || !File(directory, SessionBundle.ULTRAWIDE_FRAME_TIMESTAMPS_FILE).hasHeader("frame_number,timestamp_ns,timestamp_source"))) return BundleValidationResult.Invalid("invalid ultra-wide stream")
        if (!File(directory, SessionBundle.METADATA_FILE).hasContent()) return BundleValidationResult.Invalid("metadata commit marker is missing")
        return BundleValidationResult.Valid
    }

    private fun File.hasContent() = isFile && length() > 0L
    private fun File.hasHeader(header: String) = hasContent() && bufferedReader().use { it.readLine() == header }
}

sealed interface BundleValidationResult {
    val isValid: Boolean
    data object Valid : BundleValidationResult { override val isValid = true }
    data class Invalid(val reason: String) : BundleValidationResult { override val isValid = false }
}
