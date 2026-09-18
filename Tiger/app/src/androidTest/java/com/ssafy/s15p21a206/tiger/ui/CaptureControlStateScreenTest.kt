package com.ssafy.s15p21a206.tiger.ui

import androidx.activity.OnBackPressedDispatcher
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.string
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureControlPolicy
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureFinalizingOverlay
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureStopConfirmation
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControls
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceExitControls
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceStatus
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class CaptureControlStateScreenTest {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun system_back_and_close_share_exit_callback_and_finalizing_blocks_both() {
        val state = mutableStateOf(CaptureWorkspaceControlState.EpisodeActive)
        lateinit var dispatcher: OnBackPressedDispatcher
        var exits = 0
        composeRule.setContent {
            dispatcher = LocalOnBackPressedDispatcherOwner.current!!.onBackPressedDispatcher
            TigerTheme {
                CaptureWorkspaceExitControls(CaptureControlPolicy(state.value), { exits++ })
            }
        }
        composeRule.onNodeWithContentDescription(string(R.string.capture_close_content_description)).performClick()
        composeRule.runOnIdle { dispatcher.onBackPressed() }
        assertEquals(2, exits)
        composeRule.runOnIdle { state.value = CaptureWorkspaceControlState.Finalizing }
        composeRule
            .onNodeWithContentDescription(string(R.string.capture_close_content_description))
            .assertIsNotEnabled()
            .performClick()
        composeRule.runOnIdle { dispatcher.onBackPressed() }
        assertEquals(2, exits)
    }

    // 마감 중에는 어떤 제어도 받지 않으며, 그 사실을 화면을 덮는 판이 알린다. 진행 표시는 제어와
    // 같은 줄이 아니라 그 판에 있으므로 판을 함께 띄워야 상태 전체를 검사한 것이 된다.
    @Test
    fun finalizing_disables_controls_and_exposes_progress() {
        var calls = 0
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Finalizing, { calls++ }, { calls++ }, { calls++ })
                CaptureFinalizingOverlay(failure = null, onDismissFailure = {})
            }
        }
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_resume)).assertIsNotEnabled()
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_stop)).assertIsNotEnabled()
        composeRule.onNodeWithContentDescription(string(R.string.capture_finalizing)).assertIsDisplayed()
        assertEquals(0, calls)
    }

    @Test
    fun unprepared_preview_disables_start() {
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Idle, {}, {}, {}, ready = false)
            }
        }
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_start)).assertIsNotEnabled()
    }

    // Tracking이 안정화되기 전에는 Episode를 시작할 수 없고, 그 사실이 화면에 보여야 한다.
    @Test
    fun initializing_blocks_episode_start_and_shows_its_state() {
        var calls = 0
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Initializing, { calls++ }, { calls++ }, { calls++ })
                CaptureWorkspaceStatus(CaptureWorkspaceControlState.Initializing)
            }
        }
        composeRule
            .onNodeWithContentDescription(string(R.string.capture_control_resume))
            .assertIsNotEnabled()
            .performClick()
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_stop)).assertIsEnabled()
        composeRule.onNodeWithContentDescription(string(R.string.capture_status_initializing)).assertIsDisplayed()
        assertEquals(0, calls)
    }

    @Test
    fun ready_state_enables_episode_start() {
        var plays = 0
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Ready, { plays++ }, {}, {})
                CaptureWorkspaceStatus(CaptureWorkspaceControlState.Ready)
            }
        }
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_resume)).assertIsEnabled().performClick()
        composeRule.onNodeWithContentDescription(string(R.string.capture_status_ready)).assertIsDisplayed()
        assertEquals(1, plays)
    }

    @Test
    fun long_press_shows_accessible_control_tooltip() {
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Idle, {}, {}, {})
            }
        }
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_start)).performTouchInput { longClick() }
        composeRule.onNodeWithText(string(R.string.capture_control_start)).assertIsDisplayed()
    }

    @Test
    fun stop_confirmation_explains_upload_and_separates_cancel_from_confirm() {
        var confirmed = 0
        var cancelled = 0
        composeRule.setContent {
            TigerTheme { CaptureStopConfirmation(onConfirm = { confirmed++ }, onDismiss = { cancelled++ }) }
        }
        composeRule.onNodeWithText(string(R.string.capture_stop_message)).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.action_cancel)).performClick()
        assertEquals(0, confirmed)
        assertEquals(1, cancelled)
        composeRule.onNodeWithText(string(R.string.capture_stop_confirm)).performClick()
        assertEquals(1, confirmed)
    }
}
