package com.ssafy.s15p21a206.tiger.ui

import com.ssafy.s15p21a206.tiger.ui.capture.CaptureControlPolicy
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureExitAction
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureControlStateTest {
    @Test
    fun `five states expose only their permitted controls`() {
        // contracts/capture-state-machine.md의 상태 표. 순서는 재생·일시 정지·정지.
        val expected =
            mapOf(
                CaptureWorkspaceControlState.Idle to Triple(true, false, false),
                CaptureWorkspaceControlState.Initializing to Triple(false, false, true),
                CaptureWorkspaceControlState.Ready to Triple(true, false, true),
                CaptureWorkspaceControlState.EpisodeActive to Triple(false, true, true),
                CaptureWorkspaceControlState.Finalizing to Triple(false, false, false),
            )
        CaptureWorkspaceControlState.entries.forEach { state ->
            val policy = CaptureControlPolicy(state)
            assertEquals(state.name, expected.getValue(state), Triple(policy.canPlay, policy.canPause, policy.canStop))
        }
    }

    @Test
    fun `tracking initialization blocks episode start`() {
        assertFalse(CaptureControlPolicy(CaptureWorkspaceControlState.Initializing).canPlay)
    }

    @Test
    fun `unprepared preview and blank metadata block first play`() {
        assertFalse(CaptureControlPolicy(CaptureWorkspaceControlState.Idle, ready = false).canPlay)
    }

    @Test
    fun `episode start does not depend on the first play readiness gate`() {
        assertTrue(CaptureControlPolicy(CaptureWorkspaceControlState.Ready, ready = false).canPlay)
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
    fun `back and close leave idle workspace and require confirmation while collecting`() {
        assertEquals(CaptureExitAction.Leave, CaptureControlPolicy(CaptureWorkspaceControlState.Idle).exitAction)
        listOf(
            CaptureWorkspaceControlState.Initializing,
            CaptureWorkspaceControlState.Ready,
            CaptureWorkspaceControlState.EpisodeActive,
        ).forEach { state ->
            assertEquals(CaptureExitAction.Confirm, CaptureControlPolicy(state).exitAction)
        }
        assertEquals(CaptureExitAction.Ignore, CaptureControlPolicy(CaptureWorkspaceControlState.Finalizing).exitAction)
    }
}
