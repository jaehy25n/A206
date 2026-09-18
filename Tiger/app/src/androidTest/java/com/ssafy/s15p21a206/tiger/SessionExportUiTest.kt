package com.ssafy.s15p21a206.tiger

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ssafy.s15p21a206.tiger.episode.ExportState
import org.junit.Rule
import org.junit.Test

class SessionExportUiTest {
    @get:Rule val composeRule = createAndroidComposeRule<ComponentActivity>()

    /** 아직 내보내지 않았다는 것은 버튼이 말한다. 같은 말을 하는 문구를 따로 두지 않는다. */
    @Test
    fun completedSessionShowsExportActionWithoutRestatingItsState() {
        composeRule.setContent { ExportControls(ExportState.NOT_EXPORTED, null) {} }

        composeRule.onNodeWithText("Select export folder").assertIsDisplayed()
        composeRule.onNodeWithText("Not exported").assertDoesNotExist()
    }

    @Test
    fun cancelledPickerShowsFailureAndRetry() {
        composeRule.setContent { ExportControls(ExportState.EXPORT_FAILED, "Folder selection was cancelled") {} }

        composeRule.onNodeWithText("Export failed: Folder selection was cancelled").assertIsDisplayed()
        composeRule.onNodeWithText("Retry export").assertIsDisplayed()
    }
}
