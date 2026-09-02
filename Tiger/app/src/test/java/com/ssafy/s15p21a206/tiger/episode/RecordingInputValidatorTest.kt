package com.ssafy.s15p21a206.tiger.episode

import org.junit.Assert.assertEquals
import org.junit.Test

class RecordingInputValidatorTest {
    @Test
    fun `Korean UTF-8 input and supported camera configuration are valid`() {
        val result = RecordingInputValidator.validate(
            task = "컵 집기",
            objectName = "머그컵",
            resolution = RecordingResolution(1920, 1080),
            targetFps = 30
        )

        assertEquals(ValidationResult.Valid, result)
    }

    @Test
    fun `task rejects path separators and control characters`() {
        assertEquals(
            ValidationResult.Invalid(ValidationError.INVALID_TASK),
            RecordingInputValidator.validate("pick/cup", "cup", RecordingResolution(1280, 720), 30)
        )
        assertEquals(
            ValidationResult.Invalid(ValidationError.INVALID_TASK),
            RecordingInputValidator.validate("pick\n cup", "cup", RecordingResolution(1280, 720), 30)
        )
    }

    @Test
    fun `unsupported resolution or FPS is rejected`() {
        assertEquals(
            ValidationResult.Invalid(ValidationError.UNSUPPORTED_CAMERA_CONFIG),
            RecordingInputValidator.validate("pick_cup", "cup", RecordingResolution(640, 480), 30)
        )
    }
}
