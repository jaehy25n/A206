package com.ssafy.s15p21a206.tiger.ui.capture

enum class CaptureWorkspaceControlState {
    Ready,
    EpisodeActive,
    SessionActive,
    Finalizing,
}

enum class CaptureExitAction {
    Leave,
    Confirm,
    Ignore,
}

data class CaptureControlPolicy(
    val state: CaptureWorkspaceControlState,
    val ready: Boolean = true,
    val busy: Boolean = false,
) {
    val canPlay: Boolean
        get() = !busy && ((state == CaptureWorkspaceControlState.Ready && ready) || state == CaptureWorkspaceControlState.SessionActive)
    val canPause: Boolean
        get() = !busy && state == CaptureWorkspaceControlState.EpisodeActive
    val canStop: Boolean
        get() = !busy && state in listOf(CaptureWorkspaceControlState.EpisodeActive, CaptureWorkspaceControlState.SessionActive)
    val exitAction: CaptureExitAction
        get() =
            when {
                busy || state == CaptureWorkspaceControlState.Finalizing -> CaptureExitAction.Ignore
                state == CaptureWorkspaceControlState.Ready -> CaptureExitAction.Leave
                else -> CaptureExitAction.Confirm
            }
}
