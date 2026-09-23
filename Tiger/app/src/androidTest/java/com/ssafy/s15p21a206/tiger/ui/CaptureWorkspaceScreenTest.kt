package com.ssafy.s15p21a206.tiger.ui

import android.view.WindowManager
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.string
import com.ssafy.s15p21a206.tiger.ui.capture.CAPTURE_CENTER_GUIDE_TAG
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureCenterGuide
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControls
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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

    @Test
    fun controls_stack_vertically_so_a_mount_clamp_on_the_middle_does_not_cover_them() {
        setControls(CaptureWorkspaceControlState.EpisodeActive)

        val pause = composeRule.onNodeWithContentDescription(string(R.string.capture_control_pause)).getBoundsInRoot()
        val stop = composeRule.onNodeWithContentDescription(string(R.string.capture_control_stop)).getBoundsInRoot()
        assertEquals(pause.left, stop.left)
        assertTrue(stop.top >= pause.bottom)
    }

    @Test
    fun center_guide_sits_on_the_display_center_even_when_its_area_is_off_center() {
        // 카메라 구멍과 내비게이션 바가 창을 비대칭으로 자르는 기기를 흉내 낸다.
        composeRule.setContent {
            TigerTheme { CaptureCenterGuide(Modifier.padding(start = 120.dp)) }
        }

        val guide = composeRule.onNodeWithTag(CAPTURE_CENTER_GUIDE_TAG).fetchSemanticsNode()
        val guideCenter = guide.positionOnScreen.x + guide.size.width / 2f
        val displayWidth =
            InstrumentationRegistry
                .getInstrumentation()
                .targetContext
                .getSystemService(WindowManager::class.java)
                .maximumWindowMetrics
                .bounds
                .width()
        assertEquals(displayWidth / 2f, guideCenter, 1f)
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
