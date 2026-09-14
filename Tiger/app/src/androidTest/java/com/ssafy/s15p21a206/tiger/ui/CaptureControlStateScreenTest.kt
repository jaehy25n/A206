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
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureControlPolicy
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
        composeRule.onNodeWithContentDescription("수집 작업 공간 닫기").performClick()
        composeRule.runOnIdle { dispatcher.onBackPressed() }
        assertEquals(2, exits)
        composeRule.runOnIdle { state.value = CaptureWorkspaceControlState.Finalizing }
        composeRule.onNodeWithContentDescription("수집 작업 공간 닫기").assertIsNotEnabled().performClick()
        composeRule.runOnIdle { dispatcher.onBackPressed() }
        assertEquals(2, exits)
    }

    @Test
    fun finalizing_disables_controls_and_exposes_progress() {
        var calls = 0
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Finalizing, { calls++ }, { calls++ }, { calls++ })
            }
        }
        composeRule.onNodeWithContentDescription("작업 구간 시작").assertIsNotEnabled().performClick()
        composeRule.onNodeWithContentDescription("수집 종료").assertIsNotEnabled().performClick()
        composeRule.onNodeWithContentDescription("수집을 완료하고 있습니다").assertIsDisplayed()
        assertEquals(0, calls)
    }

    @Test
    fun unprepared_preview_disables_start() {
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Idle, {}, {}, {}, ready = false)
            }
        }
        composeRule.onNodeWithContentDescription("수집 시작").assertIsNotEnabled()
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
        composeRule.onNodeWithContentDescription("작업 구간 시작").assertIsNotEnabled().performClick()
        composeRule.onNodeWithContentDescription("수집 종료").assertIsEnabled()
        composeRule.onNodeWithContentDescription("INITIALIZING · ARCore Tracking 준비 중").assertIsDisplayed()
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
        composeRule.onNodeWithContentDescription("작업 구간 시작").assertIsEnabled().performClick()
        composeRule.onNodeWithContentDescription("READY").assertIsDisplayed()
        assertEquals(1, plays)
    }

    @Test
    fun long_press_shows_accessible_control_tooltip() {
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(CaptureWorkspaceControlState.Idle, {}, {}, {})
            }
        }
        composeRule.onNodeWithContentDescription("수집 시작").performTouchInput { longClick() }
        composeRule.onNodeWithText("수집 시작").assertIsDisplayed()
    }

    @Test
    fun stop_confirmation_explains_upload_and_separates_cancel_from_confirm() {
        var confirmed = 0
        var cancelled = 0
        composeRule.setContent {
            TigerTheme { CaptureStopConfirmation(onConfirm = { confirmed++ }, onDismiss = { cancelled++ }) }
        }
        composeRule.onNodeWithText("현재 녹화를 종료하고 Session을 완료한 뒤 전송을 시작합니다.").assertIsDisplayed()
        composeRule.onNodeWithText("취소").performClick()
        assertEquals(0, confirmed)
        assertEquals(1, cancelled)
        composeRule.onNodeWithText("종료").performClick()
        assertEquals(1, confirmed)
    }
}
