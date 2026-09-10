package com.ssafy.s15p21a206.tiger.capture

/**
 * Owns the preview-only preparation boundary.  Creating a session is deliberately
 * left to the play action so entering the workspace never creates a recording.
 */
class CapturePreviewController(
    private val preflight: CapturePreviewPreflight,
    private val preview: PreviewRuntime,
) {
    var state: CapturePreviewState = CapturePreviewState.Idle
        private set

    fun prepare(): CapturePreviewState {
        if (state is CapturePreviewState.Ready) return state
        state = CapturePreviewState.Preparing
        val failure = preflight.failure()
        if (failure != null) {
            state = CapturePreviewState.Failed(failure)
            return state
        }
        return runCatching { preview.startPreview() }
            .fold(
                onSuccess = {
                    CapturePreviewState.Ready.also { state = it }
                },
                onFailure = { error ->
                    CapturePreviewState
                        .Failed(error.message ?: "Camera preview could not be prepared")
                        .also { state = it }
                },
            )
    }

    fun release() {
        preview.releasePreview()
        state = CapturePreviewState.Idle
    }
}

fun interface CapturePreviewPreflight {
    /** Returns a user-actionable reason when preparation cannot proceed. */
    fun failure(): String?
}

interface PreviewRuntime {
    fun startPreview()

    fun releasePreview()
}

sealed interface CapturePreviewState {
    data object Idle : CapturePreviewState

    data object Preparing : CapturePreviewState

    data object Ready : CapturePreviewState

    data class Failed(
        val reason: String,
    ) : CapturePreviewState
}
