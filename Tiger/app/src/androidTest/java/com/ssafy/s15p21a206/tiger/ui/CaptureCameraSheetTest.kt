package com.ssafy.s15p21a206.tiger.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.espresso.Espresso
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.string
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureCameraPanel
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureCameraSettingsButton
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureCameraSheet
import com.ssafy.s15p21a206.tiger.ui.capture.ManualCameraUiState
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

class CaptureCameraSheetTest {
    @get:Rule val composeRule = createComposeRule()

    private val fullHd = RecordingResolution(1920, 1080)
    private val hd = RecordingResolution(1280, 720)
    private var open by mutableStateOf(true)
    private var chosen: RecordingResolution? = null

    @Test
    fun theCloseButtonFoldsTheSheet() {
        setSheet()

        composeRule.onNodeWithContentDescription(string(R.string.capture_camera_close)).performClick()
        composeRule.waitForIdle()

        assertFalse(open)
    }

    /** 시스템 뒤로 가기는 작업 공간을 닫기 전에 시트부터 닫는다. */
    @Test
    fun backFoldsTheSheetBeforeAnythingElse() {
        setSheet()
        composeRule.onNodeWithText(string(R.string.capture_camera_title)).assertIsDisplayed()

        Espresso.pressBack()
        composeRule.waitForIdle()

        assertFalse(open)
    }

    @Test
    fun theResolutionIsChosenInsideTheSheet() {
        setSheet()

        composeRule.onNodeWithText(string(R.string.capture_resolution_option, hd.width, hd.height)).performClick()

        assertEquals(hd, chosen)
    }

    @Test
    fun theSettingsButtonRefusesWhileRecording() {
        composeRule.setContent {
            TigerTheme { CaptureCameraSettingsButton(enabled = false, onClick = {}) }
        }

        composeRule.onNodeWithContentDescription(string(R.string.capture_camera_title)).assertIsNotEnabled()
    }

    private fun setSheet() {
        open = true
        chosen = null
        composeRule.setContent {
            TigerTheme {
                if (open) {
                    CaptureCameraSheet(onDismiss = { open = false }) {
                        CaptureCameraPanel(
                            state = ManualCameraUiState(),
                            resolution = fullHd,
                            enabled = true,
                            onChange = {},
                            onResolutionChange = { chosen = it },
                            onFixWhiteBalance = {},
                            onClearWhiteBalance = {},
                            onClose = { open = false },
                        )
                    }
                }
            }
        }
    }
}
