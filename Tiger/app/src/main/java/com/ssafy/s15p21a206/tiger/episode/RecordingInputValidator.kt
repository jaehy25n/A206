package com.ssafy.s15p21a206.tiger.episode

object RecordingInputValidator {
    private val controlCharacter = Regex("[\\u0000-\\u001F\\u007F]")
    private val pathSeparator = Regex("[/\\\\]")
    val supportedResolutions = setOf(RecordingResolution(1920, 1080), RecordingResolution(1280, 720))

    fun validate(task: String, objectName: String, resolution: RecordingResolution, targetFps: Int): ValidationResult {
        if (task.isBlank()) return ValidationResult.Invalid(ValidationError.EMPTY_TASK)
        if (objectName.isBlank()) return ValidationResult.Invalid(ValidationError.EMPTY_OBJECT)
        if (task.contains(pathSeparator) || task.contains(controlCharacter)) {
            return ValidationResult.Invalid(ValidationError.INVALID_TASK)
        }
        if (!supportedResolutions.contains(resolution) || targetFps != CameraConfig.TARGET_FPS) {
            return ValidationResult.Invalid(ValidationError.UNSUPPORTED_CAMERA_CONFIG)
        }
        return ValidationResult.Valid
    }
}

sealed interface ValidationResult {
    data object Valid : ValidationResult
    data class Invalid(val error: ValidationError) : ValidationResult
}

enum class ValidationError {
    EMPTY_TASK,
    EMPTY_OBJECT,
    INVALID_TASK,
    UNSUPPORTED_CAMERA_CONFIG
}
