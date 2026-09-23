package com.ssafy.s15p21a206.tiger.episode

object RecordingInputValidator {
    private val controlCharacter = Regex("[\\u0000-\\u001F\\u007F]")
    private val pathSeparator = Regex("[/\\\\]")

    /** 수집 정보 입력 화면에 보여 주는 순서와 같다. 첫 항목이 기본값이다. */
    val supportedResolutions = listOf(RecordingResolution(1920, 1080), RecordingResolution(1280, 720))
    val DEFAULT_RESOLUTION = supportedResolutions.first()

    /**
     * 유일하게 지원하는 촬영 frame rate.
     *
     * 대상 기기의 상한이기도 하다. 후면 Camera가 알리는 AE target FPS 범위의 최댓값이 30이고,
     * ARCore가 내놓는 Camera config 후보도 모두 30이다.
     */
    const val TARGET_FPS = 30

    fun validate(
        task: String,
        objectName: String,
        resolution: RecordingResolution,
        targetFps: Int,
    ): ValidationResult {
        if (task.isBlank()) return ValidationResult.Invalid(ValidationError.EMPTY_TASK)
        if (objectName.isBlank()) return ValidationResult.Invalid(ValidationError.EMPTY_OBJECT)
        if (task.contains(pathSeparator) || task.contains(controlCharacter)) {
            return ValidationResult.Invalid(ValidationError.INVALID_TASK)
        }
        if (!supportedResolutions.contains(resolution) || targetFps != TARGET_FPS) {
            return ValidationResult.Invalid(ValidationError.UNSUPPORTED_CAMERA_CONFIG)
        }
        return ValidationResult.Valid
    }
}

sealed interface ValidationResult {
    data object Valid : ValidationResult

    data class Invalid(
        val error: ValidationError,
    ) : ValidationResult
}

enum class ValidationError {
    EMPTY_TASK,
    EMPTY_OBJECT,
    INVALID_TASK,
    UNSUPPORTED_CAMERA_CONFIG,
}
