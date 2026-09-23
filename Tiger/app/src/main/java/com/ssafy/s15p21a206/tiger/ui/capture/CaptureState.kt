package com.ssafy.s15p21a206.tiger.ui.capture

import com.ssafy.s15p21a206.tiger.capture.ManualCameraCapabilities
import com.ssafy.s15p21a206.tiger.capture.ManualCameraConfig
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.episode.SessionBundle

/**
 * 수동 촬영 설정 패널의 상태.
 *
 * [config] 하나가 프리뷰와 녹화가 함께 쓰는 값이다. 화면용 값과 카메라용 값을 따로 들지 않는 것이
 * 이 기능의 요점이므로, 여기에도 사본을 만들지 않는다.
 */
internal data class ManualCameraUiState(
    /** 기기가 무엇을 지원하는지. 아직 읽기 전이면 null이다. */
    val capabilities: ManualCameraCapabilities? = null,
    val config: ManualCameraConfig? = null,
    val panelOpen: Boolean = false,
) {
    /** 수동 설정을 쓸 수 없는 이유. 패널은 조작 대신 이 문구를 보여 준다. */
    val unsupportedReason: String? get() = capabilities?.unsupportedReason

    val supported: Boolean get() = capabilities != null && unsupportedReason == null

    /**
     * 녹화에 걸 값.
     *
     * 지원하지 않는 기기에서는 null이라 수집이 기존 자동 동작 그대로 돈다. 수동 설정 하나 때문에
     * 수집 자체를 막지 않는다.
     */
    val appliedConfig: ManualCameraConfig? get() = config.takeIf { supported }

    val whiteBalanceFixed: Boolean get() = config?.awbFixed == true
}

/**
 * 수집 작업 공간의 상태 전부.
 *
 * 이전에는 `collecting`·`active`·`trackingReady`·`finalizing` 네 불리언이 16가지 조합을 만들고
 * 그중 다섯만 합법이었다. 나머지 열하나는 타입이 아니라 호출 순서로만 막혀 있었다. 여기서는
 * [phase] 하나가 그 다섯을 든다.
 *
 * [previewSurface]·[previewTexture]에 해당하는 값은 여기 없다. 수명이 `TextureView`에 묶여 있어
 * 상태로 올리면 backing view가 사라진 뒤의 null·release를 직접 관리해야 한다. composition에
 * 남기고 intent의 인자로 넘긴다.
 */
internal data class CaptureUiState(
    /** 작업 공간을 띄우고 있는지. `false`면 나머지 값은 다음 [CaptureIntent.Open]이 새로 채운다. */
    val open: Boolean = false,
    val phase: CaptureWorkspaceControlState = CaptureWorkspaceControlState.Idle,
    val task: String = "",
    val objectName: String = "",
    /** 이번 Session으로 녹화할 크기. 수집이 시작되면 ARCore가 실제로 고른 값으로 갱신된다. */
    val resolution: RecordingResolution = DEFAULT_RESOLUTION,
    /** 유휴 프리뷰 Camera2 session이 열려 있는 크기. [resolution]과 어긋나면 session을 다시 연다. */
    val idlePreviewSize: RecordingResolution = DEFAULT_RESOLUTION,
    val previewReady: Boolean = false,
    val previewFailed: Boolean = false,
    /** 비동기 작업이 도는 동안 제어를 잠근다. */
    val busy: Boolean = false,
    val showMetadataDialog: Boolean = false,
    val showStopConfirmation: Boolean = false,
    /** 마감 실패는 지나가는 알림이 아니라 확인을 받아야 걷히는 판이다. */
    val finalizeFailure: String? = null,
    /** Snackbar로 한 번 보여 주고 비우는 문구. */
    val notice: String = "",
    val activeBundle: SessionBundle? = null,
    val recordingStartNs: Long = 0L,
    /** 이번 Session에 쓸 촬영 조건. Session이 시작되면 잠긴다. */
    val manualCamera: ManualCameraUiState = ManualCameraUiState(),
) {
    /** 수집을 시작하거나 Episode를 시작할 수 있는 상태인지. */
    val ready: Boolean
        get() = previewReady && !previewFailed && task.isNotBlank() && objectName.isNotBlank() && !showMetadataDialog

    val policy: CaptureControlPolicy
        get() = CaptureControlPolicy(state = phase, ready = ready, busy = busy)

    /** 마감 중이거나 마감이 실패한 동안은 판이 덮으므로 작업 공간의 것들을 걷는다. */
    val chromeVisible: Boolean
        get() = phase != CaptureWorkspaceControlState.Finalizing && finalizeFailure == null

    private companion object {
        val DEFAULT_RESOLUTION = RecordingResolution(1920, 1080)
    }
}

/**
 * 상태를 바꾸는 유일한 입구.
 *
 * 수집 상태는 tracking 폴링·권한 콜백·lifecycle 이벤트·ARCore 실패에서 동시에 밀려온다. 각자
 * 상태를 직접 쓰면 순서를 주석으로만 지키게 되므로 여기로 모은다.
 */
internal sealed interface CaptureIntent {
    /** 수집 정보 입력부터 시작한다. [task]는 Task 목록에서 들어왔을 때 미리 채워진 이름이다. */
    data class Open(
        val task: String,
        val resolution: RecordingResolution,
    ) : CaptureIntent

    data object Close : CaptureIntent

    data class EditTask(
        val value: String,
    ) : CaptureIntent

    data class EditObjectName(
        val value: String,
    ) : CaptureIntent

    data class SelectResolution(
        val value: RecordingResolution,
    ) : CaptureIntent

    /** 녹화 카메라의 능력과 불러온 설정을 받았다. 수집 화면을 열 때 한 번 온다. */
    data class ManualCameraProfiled(
        val capabilities: ManualCameraCapabilities,
        val config: ManualCameraConfig,
    ) : CaptureIntent

    /** 사용자가 초점·ISO·셔터·WB를 건드렸다. */
    data class EditManualCamera(
        val value: ManualCameraConfig,
    ) : CaptureIntent

    data class ToggleManualCameraPanel(
        val open: Boolean,
    ) : CaptureIntent

    data object ConfirmMetadata : CaptureIntent

    /** 유휴 프리뷰 Camera2 session을 고른 크기로 다시 연 뒤. */
    data class IdlePreviewResized(
        val value: RecordingResolution,
    ) : CaptureIntent

    data object PreviewFrameArrived : CaptureIntent

    data object PreviewReleased : CaptureIntent

    data class PreviewFailed(
        val notice: String,
    ) : CaptureIntent

    /** 권한 요청과 ARCore 시작을 걸기 직전. */
    data object SessionRequested : CaptureIntent

    data class SessionStarted(
        val bundle: SessionBundle,
        val startedAtNs: Long,
        val resolution: RecordingResolution,
    ) : CaptureIntent

    /** tracking 표본 하나. 값이 변하지 않아도 계속 들어와야 안정화와 유실 마감이 발화한다. */
    data class TrackingSampled(
        val ready: Boolean,
        val episodeActive: Boolean,
    ) : CaptureIntent

    data object EpisodeStarted : CaptureIntent

    data object EpisodeEnded : CaptureIntent

    data object StopRequested : CaptureIntent

    data object StopDismissed : CaptureIntent

    data object FinalizeStarted : CaptureIntent

    data class FinalizeFailed(
        val notice: String,
    ) : CaptureIntent

    data object FinalizeFailureDismissed : CaptureIntent

    data object Finalized : CaptureIntent

    /** `ON_STOP`에서 진행 중인 Session을 `INTERRUPTED`로 마감한 뒤. */
    data object Interrupted : CaptureIntent

    data object BusyReleased : CaptureIntent

    data class Notify(
        val notice: String,
    ) : CaptureIntent

    data object NoticeShown : CaptureIntent
}

/**
 * 상태 전이.
 *
 * 받을 수 없는 상태에서 온 intent는 상태를 그대로 돌려준다. 예를 들어 [CaptureIntent.EpisodeStarted]는
 * tracking이 안정화된 뒤에만 뜻이 있으므로 [CaptureWorkspaceControlState.Ready]에서만 받는다.
 * 무시하는 쪽이 맞는 것은, 이 값들이 사용자 조작이 아니라 비동기 경로에서도 밀려오기 때문이다.
 */
internal fun CaptureUiState.reduce(intent: CaptureIntent): CaptureUiState =
    when (intent) {
        // 직전 Session이 남긴 값을 물려받지 않도록 새로 만든다.
        is CaptureIntent.Open ->
            CaptureUiState(
                open = true,
                task = intent.task,
                resolution = intent.resolution,
                idlePreviewSize = intent.resolution,
                showMetadataDialog = true,
            )
        CaptureIntent.Close -> CaptureUiState()
        is CaptureIntent.EditTask -> copy(task = intent.value)
        is CaptureIntent.EditObjectName -> copy(objectName = intent.value)
        // 해상도도 초점·ISO와 같은 촬영 조건이다. Session이 시작되면 바뀌지 않는다. 시작 직전에
        // ARCore가 실제로 고른 값으로 맞추는 갱신은 아직 Idle일 때 오므로 여기에 걸리지 않는다.
        is CaptureIntent.SelectResolution ->
            if (phase == CaptureWorkspaceControlState.Idle) copy(resolution = intent.value) else this
        is CaptureIntent.ManualCameraProfiled ->
            copy(
                manualCamera =
                    manualCamera.copy(
                        capabilities = intent.capabilities,
                        config = intent.capabilities.coerce(intent.config),
                    ),
            )
        // Session이 시작된 뒤에는 값을 바꾸지 않는다. 화면에서도 막지만, 상태 전이로 한 번 더
        // 막는 것은 이 값이 촬영 도중 흔들리지 않는 것이 기능의 전부이기 때문이다.
        is CaptureIntent.EditManualCamera ->
            when {
                phase != CaptureWorkspaceControlState.Idle -> this
                manualCamera.capabilities == null -> this
                else -> copy(manualCamera = manualCamera.copy(config = manualCamera.capabilities.coerce(intent.value)))
            }
        // 촬영 중에는 설정을 열지 않는다. 시트는 모달이라 열려 있는 동안 정지를 누를 수 없고,
        // 값도 잠겨 있어 열어 봐야 할 일이 없다. 닫는 요청은 언제나 받는다.
        is CaptureIntent.ToggleManualCameraPanel ->
            if (intent.open && phase != CaptureWorkspaceControlState.Idle) {
                this
            } else {
                copy(manualCamera = manualCamera.copy(panelOpen = intent.open))
            }
        CaptureIntent.ConfirmMetadata -> copy(showMetadataDialog = false)
        is CaptureIntent.IdlePreviewResized -> copy(idlePreviewSize = intent.value)
        CaptureIntent.PreviewFrameArrived -> if (previewFailed) this else copy(previewReady = true)
        CaptureIntent.PreviewReleased -> copy(previewReady = false)
        is CaptureIntent.PreviewFailed -> copy(previewReady = false, previewFailed = true, notice = intent.notice)
        CaptureIntent.SessionRequested -> copy(busy = true, previewReady = false)
        is CaptureIntent.SessionStarted ->
            copy(
                phase = CaptureWorkspaceControlState.Initializing,
                // ARCore가 실제로 고른 크기다. 후보 config가 없어 기본값으로 물러났으면 고른 값과 다르다.
                resolution = intent.resolution,
                idlePreviewSize = intent.resolution,
                activeBundle = intent.bundle,
                recordingStartNs = intent.startedAtNs,
                busy = false,
                // 촬영이 시작되면 설정은 잠긴다. 열린 패널은 더 이상 아무것도 받지 않으므로 접는다.
                manualCamera = manualCamera.copy(panelOpen = false),
            )
        is CaptureIntent.TrackingSampled ->
            when (phase) {
                CaptureWorkspaceControlState.Initializing,
                CaptureWorkspaceControlState.Ready,
                CaptureWorkspaceControlState.EpisodeActive,
                ->
                    copy(
                        phase =
                            when {
                                intent.episodeActive -> CaptureWorkspaceControlState.EpisodeActive
                                intent.ready -> CaptureWorkspaceControlState.Ready
                                else -> CaptureWorkspaceControlState.Initializing
                            },
                    )
                // Idle에는 아직 Session이 없고 Finalizing은 이미 닫는 중이다.
                else -> this
            }
        CaptureIntent.EpisodeStarted ->
            if (phase == CaptureWorkspaceControlState.Ready) copy(phase = CaptureWorkspaceControlState.EpisodeActive) else this
        CaptureIntent.EpisodeEnded ->
            if (phase == CaptureWorkspaceControlState.EpisodeActive) copy(phase = CaptureWorkspaceControlState.Ready) else this
        CaptureIntent.StopRequested -> copy(showStopConfirmation = true)
        CaptureIntent.StopDismissed -> copy(showStopConfirmation = false)
        CaptureIntent.FinalizeStarted -> copy(phase = CaptureWorkspaceControlState.Finalizing, showStopConfirmation = false)
        is CaptureIntent.FinalizeFailed -> copy(finalizeFailure = intent.notice)
        // 실패를 확인받은 뒤에야 다시 찍을 수 있다. Session은 저장되지 않았으므로 Idle로 돌아간다.
        CaptureIntent.FinalizeFailureDismissed ->
            copy(finalizeFailure = null, phase = CaptureWorkspaceControlState.Idle, activeBundle = null, recordingStartNs = 0L)
        CaptureIntent.Finalized ->
            copy(phase = CaptureWorkspaceControlState.Idle, activeBundle = null, recordingStartNs = 0L, busy = false)
        CaptureIntent.Interrupted ->
            copy(phase = CaptureWorkspaceControlState.Idle, activeBundle = null, recordingStartNs = 0L, busy = false)
        CaptureIntent.BusyReleased -> copy(busy = false)
        is CaptureIntent.Notify -> copy(notice = intent.notice)
        CaptureIntent.NoticeShown -> copy(notice = "")
    }
