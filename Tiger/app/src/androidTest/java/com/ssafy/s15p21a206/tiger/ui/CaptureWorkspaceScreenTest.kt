package com.ssafy.s15p21a206.tiger.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.string
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControls
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class CaptureWorkspaceScreenTest {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun idle_workspace_exposes_only_session_start_control() {
        setControls(CaptureWorkspaceControlState.Idle)

        composeRule.onNodeWithContentDescription(string(R.string.capture_control_start)).assertIsDisplayed().performClick()
        assertEquals("play", clicked)
    }

    @Test
    fun active_episode_exposes_pause_and_stop_controls() {
        setControls(CaptureWorkspaceControlState.EpisodeActive)

        composeRule.onNodeWithContentDescription(string(R.string.capture_control_pause)).assertIsDisplayed().performClick()
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_stop)).assertIsDisplayed()
        assertEquals("pause", clicked)
    }

    @Test
    fun ready_session_exposes_episode_start_and_stop_controls() {
        setControls(CaptureWorkspaceControlState.Ready)

        composeRule.onNodeWithContentDescription(string(R.string.capture_control_resume)).assertIsDisplayed().performClick()
        composeRule.onNodeWithContentDescription(string(R.string.capture_control_stop)).assertIsDisplayed()
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
