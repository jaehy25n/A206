package com.ssafy.s15p21a206.tiger.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControls
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class CaptureWorkspaceScreenTest {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun ready_workspace_exposes_only_start_control() {
        setControls(CaptureWorkspaceControlState.Ready)

        composeRule.onNodeWithContentDescription("수집 시작").assertIsDisplayed().performClick()
        assertEquals("play", clicked)
    }

    @Test
    fun active_episode_exposes_pause_and_stop_controls() {
        setControls(CaptureWorkspaceControlState.EpisodeActive)

        composeRule.onNodeWithContentDescription("작업 구간 일시 정지").assertIsDisplayed().performClick()
        composeRule.onNodeWithContentDescription("수집 종료").assertIsDisplayed()
        assertEquals("pause", clicked)
    }

    @Test
    fun paused_episode_exposes_resume_and_stop_controls() {
        setControls(CaptureWorkspaceControlState.SessionActive)

        composeRule.onNodeWithContentDescription("작업 구간 시작").assertIsDisplayed().performClick()
        composeRule.onNodeWithContentDescription("수집 종료").assertIsDisplayed()
        assertEquals("play", clicked)
    }

    private fun setControls(state: CaptureWorkspaceControlState) {
        clicked = ""
        composeRule.setContent {
            TigerTheme {
                CaptureWorkspaceControls(
                    state = state,
                    onPlay = { clicked = "play" },
                    onPause = { clicked = "pause" },
                    onStop = { clicked = "stop" },
                )
            }
        }
    }

    private companion object {
        var clicked = ""
    }
}
