package com.ssafy.s15p21a206.tiger.ui

import com.ssafy.s15p21a206.tiger.ui.capture.CaptureControlPolicy
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureExitAction
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class CaptureControlStateTest {
    @Test
    fun `four states expose only their permitted controls`() {
        val expected = listOf(Triple(true, false, false), Triple(false, true, true), Triple(true, false, true), Triple(false, false, false))
        CaptureWorkspaceControlState.entries.forEachIndexed { index, state ->
            val policy = CaptureControlPolicy(state)
            assertEquals(expected[index], Triple(policy.canPlay, policy.canPause, policy.canStop))
        }
    }

    @Test
    fun `unprepared preview and blank metadata block first play`() {
        assertFalse(CaptureControlPolicy(CaptureWorkspaceControlState.Ready, ready = false).canPlay)
    }

    @Test
    fun `pending operation blocks duplicate controls and exit`() {
        CaptureWorkspaceControlState.entries.forEach { state ->
            val policy = CaptureControlPolicy(state, busy = true)
            assertFalse(policy.canPlay)
            assertFalse(policy.canPause)
            assertFalse(policy.canStop)
            assertEquals(CaptureExitAction.Ignore, policy.exitAction)
        }
    }

    @Test
    fun `back and close leave ready workspace and require confirmation while recording`() {
        assertEquals(CaptureExitAction.Leave, CaptureControlPolicy(CaptureWorkspaceControlState.Ready).exitAction)
        listOf(CaptureWorkspaceControlState.EpisodeActive, CaptureWorkspaceControlState.SessionActive).forEach { state ->
            assertEquals(CaptureExitAction.Confirm, CaptureControlPolicy(state).exitAction)
        }
        assertEquals(CaptureExitAction.Ignore, CaptureControlPolicy(CaptureWorkspaceControlState.Finalizing).exitAction)
    }
}
