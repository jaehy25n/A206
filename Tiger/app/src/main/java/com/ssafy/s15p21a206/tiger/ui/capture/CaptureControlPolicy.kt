package com.ssafy.s15p21a206.tiger.ui.capture

/**
 * 수집 작업 공간이 표시하는 상태.
 *
 * 이름은 명세 및 수신 측 어휘를 따른다. [Ready]는 Session이 이미 수집 중이고 ARCore Tracking이
 * 안정화되어 Episode를 시작할 수 있는 상태를 뜻한다. Session을 아직 시작하지 않은 상태는 [Idle]이다.
 */
enum class CaptureWorkspaceControlState {
    Idle,
    Initializing,
    Ready,
    EpisodeActive,
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
    // Idle에서는 Session을, Ready에서는 Episode를 시작한다. Initializing은 Tracking이 안정화될 때까지 막는다.
    val canPlay: Boolean
        get() = !busy && ((state == CaptureWorkspaceControlState.Idle && ready) || state == CaptureWorkspaceControlState.Ready)
    val canPause: Boolean
        get() = !busy && state == CaptureWorkspaceControlState.EpisodeActive
    val canStop: Boolean
        get() =
            !busy &&
                state in
                listOf(
                    CaptureWorkspaceControlState.Initializing,
                    CaptureWorkspaceControlState.Ready,
                    CaptureWorkspaceControlState.EpisodeActive,
                )
    val exitAction: CaptureExitAction
        get() =
            when {
                busy || state == CaptureWorkspaceControlState.Finalizing -> CaptureExitAction.Ignore
                state == CaptureWorkspaceControlState.Idle -> CaptureExitAction.Leave
                else -> CaptureExitAction.Confirm
            }
}
