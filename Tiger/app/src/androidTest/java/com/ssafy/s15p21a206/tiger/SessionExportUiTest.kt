package com.ssafy.s15p21a206.tiger

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.assertIsDisplayed
import com.ssafy.s15p21a206.tiger.episode.ExportState
import org.junit.Rule
import org.junit.Test

class SessionExportUiTest {
    @get:Rule val composeRule = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun completedSessionExportControlIsVisible() {
        composeRule.setContent { CaptureScreen() }

        composeRule.onNodeWithText("Not exported").assertIsDisplayed()
        composeRule.onNodeWithText("Select export folder").assertIsDisplayed()
    }

    @Test
    fun cancelledPickerShowsFailureAndRetry() {
        composeRule.setContent { ExportControls(ExportState.EXPORT_FAILED, "Folder selection was cancelled") {} }

        composeRule.onNodeWithText("Export failed: Folder selection was cancelled").assertIsDisplayed()
        composeRule.onNodeWithText("Retry export").assertIsDisplayed()
    }
}
