package com.ssafy.s15p21a206.tiger.ui.capture

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.SurfaceTexture
import android.net.Uri
import android.os.SystemClock
import android.view.Surface
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.ar.core.ArCoreApk
import com.google.ar.core.exceptions.UnavailableArcoreNotInstalledException
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.capture.AndroidCaptureRuntime
import com.ssafy.s15p21a206.tiger.capture.CameraPreviewController
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewController
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewPreflight
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewState
import com.ssafy.s15p21a206.tiger.capture.CaptureSessionCoordinator
import com.ssafy.s15p21a206.tiger.capture.MonotonicClock
import com.ssafy.s15p21a206.tiger.capture.PreviewRuntime
import com.ssafy.s15p21a206.tiger.capture.RecordingResolutionStore
import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.episode.TrackingState
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.common.LockLandscapeWhileVisible
import com.ssafy.s15p21a206.tiger.ui.common.findActivity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 수집 작업 공간. 조회 흐름 위에 모달로 얹힌다.
 *
 * 목적지가 아닌 이유는 진입 경로가 하나뿐이고, 뒤로 가기가 "이전 화면으로"가 아니라 "종료할까요?"이며,
 * 안에 또 모달을 품기 때문이다. NavHost 바깥에 있어 수집 상태가 백스택 조작과 무관하게 남는다.
 *
 * **이 화면은 목적지를 모른다.** 마감이 끝나면 [onCompleted]로 sessionId를 올려 보내고, 어디로
 * 갈지와 전송을 걸지는 부모가 정한다. 이전에는 여기서 `navController`를 직접 밀었다.
 *
 * [state]는 부모가 소유한다. 부모가 [CaptureIntent.Open]으로 작업 공간을 열기 때문이다.
 *
 * `previewSurface`와 권한 launcher는 여기 남는다. 수명이 `TextureView`와 composition에 묶여 있어
 * 상태로 올리면 backing view가 사라진 뒤의 null·release를 직접 관리해야 한다.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Suppress("FunctionName", "LongMethod", "CyclomaticComplexMethod")
@Composable
internal fun CaptureWorkspace(
    state: CaptureUiState,
    onIntent: (CaptureIntent) -> Unit,
    repository: SessionRepository,
    resolutionStore: RecordingResolutionStore,
    /** 마감으로 세션이 저장됐다. `startUpload`는 앱이 전면에 있어 전송을 걸어도 되는지다. */
    onCompleted: (sessionId: String, startUpload: Boolean) -> Unit,
) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val scope = rememberCoroutineScope()
    val captureRuntime = remember { AndroidCaptureRuntime(context.applicationContext, SessionBundleStore(context.applicationContext)) }
    val snackbarHostState = remember { SnackbarHostState() }
    val previewFailureMessage = stringResource(R.string.capture_preview_failed)
    val operationFailureMessage = stringResource(R.string.capture_operation_failed)
    var previewSurface by remember { mutableStateOf<Surface?>(null) }
    // 수집 시작 시 ARCore가 고른 해상도로 버퍼를 다시 맞추려면 SurfaceTexture를 들고 있어야 한다.
    var previewTexture by remember { mutableStateOf<SurfaceTexture?>(null) }
    var arCoreInstallRequested by remember { mutableStateOf(false) }
    val previewController =
        remember {
            CameraPreviewController(context.applicationContext) { _ ->
                onIntent(CaptureIntent.PreviewFailed(previewFailureMessage))
            }
        }
    val capturePreviewController =
        remember {
            CapturePreviewController(
                preflight =
                    CapturePreviewPreflight {
                        when {
                            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) !=
                                PackageManager.PERMISSION_GRANTED -> "Camera permission is required for preview"
                            previewSurface == null -> "Camera preview surface is unavailable"
                            else -> null
                        }
                    },
                preview =
                    object : PreviewRuntime {
                        override fun startPreview() {
                            previewController.prepare(requireNotNull(previewSurface))
                        }

                        override fun releasePreview() = previewController.release()
                    },
            )
        }
    val episodeInvalidatedMessage = stringResource(R.string.capture_episode_invalid_tracking)
    val coordinator =
        remember {
            CaptureSessionCoordinator(
                clock = MonotonicClock(SystemClock::elapsedRealtimeNanos),
                writers = emptyList(),
                onEpisodeClosed = { marker ->
                    // 사용자 종료와 Tracking 유실 자동 마감이 같은 경로로 기록된다.
                    if (marker.outcome == EpisodeState.INVALID_TRACKING) onIntent(CaptureIntent.Notify(episodeInvalidatedMessage))
                    scope.launch {
                        runCatching {
                            repository.save(marker)
                            captureRuntime.appendEpisode(marker)
                        }.onFailure { onIntent(CaptureIntent.Notify(operationFailureMessage)) }
                    }
                },
            )
        }
    val recordingCameraUnavailable = stringResource(R.string.recording_camera_unavailable)
    val activeEpisodeEndRequired = stringResource(R.string.active_episode_end_required)
    val trackingNotReadyMessage = stringResource(R.string.capture_tracking_not_ready)
    val captureFinalizeFailed = stringResource(R.string.capture_finalize_failed)
    val arCoreUnavailable = stringResource(R.string.arcore_unavailable)
    val arCoreInstallMessage = stringResource(R.string.arcore_install_requested)
    val arCoreSessionStartFailed = stringResource(R.string.arcore_session_start_failed)

    fun requestCaptureExit() {
        when (state.policy.exitAction) {
            CaptureExitAction.Ignore -> Unit
            CaptureExitAction.Confirm -> onIntent(CaptureIntent.StopRequested)
            // 녹화 전에는 Session을 만들지 않고 작업 공간만 닫는다. 아래에 목록이 그대로 남아 있다.
            CaptureExitAction.Leave -> onIntent(CaptureIntent.Close)
        }
    }

    // ARCore가 카메라를 놓은 뒤 유휴 Camera2 프리뷰를 되살린다.
    // prepare()는 Ready 상태에서 즉시 반환하므로 먼저 Idle로 되돌려야 실제로 다시 연다.
    fun restoreIdlePreview() {
        if (previewSurface == null) return
        capturePreviewController.release()
        if (capturePreviewController.prepare() is CapturePreviewState.Failed) {
            onIntent(CaptureIntent.PreviewFailed(previewFailureMessage))
        }
    }
    val cameraPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                val activity = context.findActivity()
                val installStatus =
                    runCatching {
                        requireNotNull(activity) { "Activity is required to install ARCore." }
                        ArCoreApk.getInstance().requestInstall(activity, !arCoreInstallRequested)
                    }.getOrElse {
                        onIntent(CaptureIntent.Notify(arCoreUnavailable))
                        onIntent(CaptureIntent.BusyReleased)
                        return@rememberLauncherForActivityResult
                    }
                if (installStatus == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                    arCoreInstallRequested = true
                    onIntent(CaptureIntent.Notify(arCoreInstallMessage))
                    onIntent(CaptureIntent.BusyReleased)
                    return@rememberLauncherForActivityResult
                }
                scope.launch {
                    try {
                        val displayNumber = repository.nextDisplayNumber()
                        runCatching {
                            // ARCore가 고른 해상도로 버퍼를 맞춰 프리뷰 화각을 저장 영상과 일치시킨다.
                            // 이 람다는 Main dispatcher에서 실행되므로 Compose 상태를 직접 갱신해도 된다.
                            // 프리뷰용 Camera2 세션은 onPlay에서 이미 닫혔으므로 버퍼 크기를 바꿔도 안전하다.
                            captureRuntime.start(displayNumber, state.resolution) { width, height ->
                                // ARCore가 실제로 고른 크기다. 후보 config가 없어 기본값으로 물러났으면
                                // 고른 값과 다를 수 있으므로, 표시와 프리뷰를 여기에 맞춘다.
                                val actual = RecordingResolution(width, height)
                                onIntent(CaptureIntent.SelectResolution(actual))
                                onIntent(CaptureIntent.IdlePreviewResized(actual))
                                previewTexture?.setDefaultBufferSize(width, height)
                                previewSurface
                            }
                        }.onSuccess { bundle ->
                            val startedAtNs = SystemClock.elapsedRealtimeNanos()
                            // Session 시작은 Episode를 만들지 않는다. Tracking 안정화 뒤 사용자가 따로 시작한다.
                            coordinator.start(bundle.sessionId, bundle.displayNumber, bundle.directory.absolutePath)
                            onIntent(CaptureIntent.SessionStarted(bundle, startedAtNs, state.resolution))
                            repository.save(
                                CaptureSession(
                                    bundle.sessionId,
                                    bundle.displayNumber,
                                    RecordingState.INITIALIZING,
                                    UploadState.LOCAL_ONLY,
                                    startedAtNs,
                                    bundlePath = bundle.directory.absolutePath,
                                    recordingStartEpochMs = System.currentTimeMillis(),
                                ),
                            )
                        }.onFailure { error ->
                            // ARCore가 카메라를 잡지 못했으므로 유휴 프리뷰를 되살린다.
                            restoreIdlePreview()
                            onIntent(CaptureIntent.Notify("$arCoreSessionStartFailed: ${error.message.orEmpty()}"))
                            if (error is UnavailableArcoreNotInstalledException) {
                                context.openArCoreStore()
                            }
                        }
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (_: Exception) {
                        onIntent(CaptureIntent.Notify(operationFailureMessage))
                    } finally {
                        onIntent(CaptureIntent.BusyReleased)
                    }
                }
            } else {
                onIntent(CaptureIntent.Notify(recordingCameraUnavailable))
                onIntent(CaptureIntent.BusyReleased)
            }
        }
    val previewPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted && previewSurface != null) {
                capturePreviewController.release()
                if (capturePreviewController.prepare() is CapturePreviewState.Failed) {
                    onIntent(CaptureIntent.PreviewFailed(previewFailureMessage))
                }
            } else if (!granted) {
                onIntent(CaptureIntent.PreviewFailed(previewFailureMessage))
            }
        }
    LaunchedEffect(state.open) {
        if (state.open) {
            previewPermission.launch(Manifest.permission.CAMERA)
        }
    }
    // onTracking은 호출 시점 기준으로 경과 시간을 판정하므로, 값이 변하지 않아도 계속 호출되어야
    // 안정화(1초)와 유실(0.5초) 마감이 발화한다. 값 변화 구독만으로는 유실 마감이 오지 않는다.
    LaunchedEffect(state.phase != CaptureWorkspaceControlState.Idle) {
        if (state.phase == CaptureWorkspaceControlState.Idle) return@LaunchedEffect
        while (true) {
            val sample = captureRuntime.tracking.value
            coordinator.onTracking(sample.isTracking, sample.observedAtNs.takeIf { it > 0L })
            // Tracking 유실 자동 마감은 사용자 조작 없이 일어나므로 화면 상태를 여기서 맞춘다.
            onIntent(
                CaptureIntent.TrackingSampled(
                    ready = coordinator.trackingState == TrackingState.READY,
                    episodeActive = coordinator.activeEpisode != null,
                ),
            )
            delay(TRACKING_TICK_MS)
        }
    }
    LaunchedEffect(state.notice, state.open) {
        if (state.open && state.notice.isNotBlank()) {
            val notice = state.notice
            onIntent(CaptureIntent.NoticeShown)
            scope.launch { snackbarHostState.showSnackbar(notice) }
        }
    }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
        if (state.phase == CaptureWorkspaceControlState.Finalizing) return@LifecycleEventEffect
        val interruptedBundle = state.activeBundle ?: return@LifecycleEventEffect
        val startedAtNs = state.recordingStartNs
        captureRuntime.interrupt()
        scope.launch {
            repository.save(
                CaptureSession(
                    interruptedBundle.sessionId,
                    interruptedBundle.displayNumber,
                    RecordingState.INTERRUPTED,
                    UploadState.LOCAL_ONLY,
                    startedAtNs,
                    SystemClock.elapsedRealtimeNanos(),
                    interruptedBundle.directory.absolutePath,
                    System.currentTimeMillis(),
                ),
            )
        }
        onIntent(CaptureIntent.Interrupted)
        coordinator.release()
    }
    // 백그라운드 전환으로 카메라를 놓고 돌아온 경우 TextureView는 살아 있지만 프레임이 끊긴 상태다.
    LifecycleEventEffect(Lifecycle.Event.ON_START) {
        if (state.open && state.phase == CaptureWorkspaceControlState.Idle) restoreIdlePreview()
    }

    fun finalizeCapture() {
        if (!state.policy.canStop) return
        // 진행 중인 Episode가 있으면 Session을 마감하지 않고 먼저 종료하도록 안내한다.
        if (coordinator.activeEpisode != null) {
            onIntent(CaptureIntent.Notify(activeEpisodeEndRequired))
            return
        }
        val bundle = state.activeBundle
        val startedAtNs = state.recordingStartNs
        onIntent(CaptureIntent.FinalizeStarted)
        scope.launch {
            try {
                when (
                    val result =
                        runCatching { withContext(Dispatchers.IO) { captureRuntime.stop() } }
                            .getOrElse { FinalizeResult.Failed(it.message.orEmpty()) }
                ) {
                    is FinalizeResult.Completed -> {
                        bundle?.let {
                            val completedSession =
                                CaptureSession(
                                    bundle.sessionId,
                                    bundle.displayNumber,
                                    RecordingState.COMPLETED,
                                    UploadState.LOCAL_ONLY,
                                    startedAtNs,
                                    SystemClock.elapsedRealtimeNanos(),
                                    result.directory.absolutePath,
                                    System.currentTimeMillis(),
                                )
                            repository.save(completedSession)
                            // 백그라운드에서 마감됐으면 전송을 걸지 않고 실패로 남긴다.
                            val startUpload = lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
                            if (!startUpload) repository.save(completedSession.copy(uploadState = UploadState.FAILED))
                            // 어디로 갈지는 부모가 정한다. 이 화면은 목적지를 모른다.
                            onCompleted(bundle.sessionId, startUpload)
                        }
                    }
                    // 마감 실패는 지나가는 알림이 아니다. 저장된 세션이 없으므로 넘어갈 곳도 없다.
                    // 작업 공간을 덮은 판에 세워 두고, 확인을 받은 뒤에야 다시 찍을 수 있게 한다.
                    is FinalizeResult.Failed -> onIntent(CaptureIntent.FinalizeFailed("$captureFinalizeFailed: ${result.reason}"))
                }
                // 다음 Session을 시작할 수 있도록 Coordinator의 Session·Tracking 상태를 닫는다.
                coordinator.release()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                onIntent(CaptureIntent.FinalizeFailed(captureFinalizeFailed))
            } finally {
                // 예외로 빠져나가도 Finalizing에 머무르지 않게 여기서 닫는다.
                onIntent(CaptureIntent.Finalized)
                // 마감에 성공하면 업로드·상세 화면으로 이동해 TextureView가 사라지므로 되살릴 필요가 없다.
                // 수집 화면에 그대로 남는 실패 경로에서만 유휴 프리뷰를 다시 연다.
                if (state.open) restoreIdlePreview()
            }
        }
    }

    if (!state.open) return
    // 작업 공간을 벗어나면 유휴 프리뷰 Camera2 session을 놓는다. 조회 화면이 카메라를
    // 붙잡고 있을 이유가 없고, 다음 수집은 새 Surface로 다시 연다.
    DisposableEffect(capturePreviewController) {
        onDispose(capturePreviewController::release)
    }
    // 수집 화면은 가로로 고정한다. Camera 센서가 90도 눕혀 장착돼 있어 세로 화면에서는
    // 프리뷰가 옆으로 누운 채 비율까지 어긋나 보인다. 저장되는 영상도 가로다.
    LockLandscapeWhileVisible()
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        CapturePreviewSurface(
            bufferSize = state.idlePreviewSize,
            // 수집이 시작되면 ARCore가 직접 그리므로 변환을 걷는다.
            applyTransform = state.phase == CaptureWorkspaceControlState.Idle,
            onSurfaceAvailable = { surface, texture ->
                previewSurface = surface
                previewTexture = texture
                if (capturePreviewController.prepare() is CapturePreviewState.Failed) {
                    onIntent(CaptureIntent.PreviewFailed(previewFailureMessage))
                }
            },
            onSurfaceDestroyed = {
                capturePreviewController.release()
                previewSurface?.release()
                previewSurface = null
                previewTexture = null
                onIntent(CaptureIntent.PreviewReleased)
            },
            onFrame = { onIntent(CaptureIntent.PreviewFrameArrived) },
            // 프리뷰는 가로 16:9다. 화면이 세로면 위아래에 검은 영역이 남고, 가로면 꽉 찬다.
            // 늘이거나 잘라내지 않아야 저장되는 영상과 화각이 같다.
            modifier = Modifier.align(Alignment.Center).aspectRatio(PREVIEW_ASPECT_RATIO),
        )
        // 상태 배지와 닫기 버튼을 한 Row에 담아 어떤 화면 비율에서도 겹치지 않게 한다.
        // 서로 다른 align으로 두면 배지 폭이 길어질 때 닫기 버튼 아래로 파고든다.
        // 기준은 프리뷰가 아니라 화면이다. 하단 컨트롤과 좌표계를 맞추고, 레터박스가 생기는
        // 기기에서는 검은 띠 위에 얹혀 영상을 가리지 않는다.
        // 마감 중에는 프리뷰만 남기고 판 위의 것들을 걷는다. 상태 배지는 덮은 판이 같은 말을
        // 더 길게 하고 있고, 닫기와 제어는 그 구간에 아무것도 받지 않는다. 덮인 채로 남겨 두면
        // 누를 수 있는 것처럼 보이기만 한다.
        if (state.chromeVisible) {
            Row(
                modifier =
                    Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth()
                        .safeDrawingPadding()
                        .padding(top = 20.dp, start = 20.dp, end = 20.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(
                    // fill = false라야 배지가 제 너비만 쓰고, 길어져도 닫기 버튼 자리를 침범하지 않는다.
                    modifier = Modifier.weight(1f, fill = false),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    CaptureWorkspaceStatus(state = state.phase)
                    // 어느 해상도로 찍는지 촬영 직전에 보여 준다. Session마다 달라질 수 있다.
                    CaptureWorkspaceResolution(resolution = state.resolution)
                }
                CaptureWorkspaceExitControls(
                    policy = state.policy,
                    onExit = ::requestCaptureExit,
                )
            }
        }
        SnackbarHost(snackbarHostState, Modifier.align(Alignment.TopCenter).padding(top = 80.dp))
        if (!state.showMetadataDialog && state.chromeVisible) {
            CaptureWorkspaceControls(
                state = state.phase,
                ready = state.ready,
                busy = state.busy,
                onPlay = play@{
                    if (!state.policy.canPlay) return@play
                    if (state.phase == CaptureWorkspaceControlState.Idle) {
                        onIntent(CaptureIntent.SessionRequested)
                        capturePreviewController.release()
                        cameraPermission.launch(Manifest.permission.CAMERA)
                    } else {
                        // Episode 시작은 Coordinator가 Tracking 안정화 여부를 확인한 뒤에만 허용한다.
                        runCatching { coordinator.startEpisode(state.task, state.objectName) }
                            .onSuccess { onIntent(CaptureIntent.EpisodeStarted) }
                            .onFailure { onIntent(CaptureIntent.Notify(trackingNotReadyMessage)) }
                    }
                },
                onPause = pause@{
                    if (!state.policy.canPause) return@pause
                    // 기록은 coordinator의 onEpisodeClosed가 담당한다.
                    runCatching { coordinator.endEpisode() }
                        .onSuccess { onIntent(CaptureIntent.EpisodeEnded) }
                        .onFailure { onIntent(CaptureIntent.Notify(operationFailureMessage)) }
                },
                onStop = { if (state.policy.canStop) requestCaptureExit() },
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
    if (state.showMetadataDialog) {
        CaptureMetadataDialog(
            task = state.task,
            objectName = state.objectName,
            resolution = state.resolution,
            onTaskChange = { onIntent(CaptureIntent.EditTask(it)) },
            onObjectNameChange = { onIntent(CaptureIntent.EditObjectName(it)) },
            onResolutionChange = { onIntent(CaptureIntent.SelectResolution(it)) },
            onCancel = { onIntent(CaptureIntent.Close) },
            // 확정한 선택만 기억한다. 취소하고 나간 선택은 다음 수집의 기본값이 되지 않는다.
            onConfirm = {
                val chosen = state.resolution
                resolutionStore.save(chosen)
                onIntent(CaptureIntent.ConfirmMetadata)
                // 유휴 프리뷰도 고른 해상도로 다시 연다. Camera2는 session을 만들 때 stream 크기를
                // 정하므로, 버퍼 크기만 바꾸면 이미 열린 session에는 반영되지 않는다.
                if (state.idlePreviewSize != chosen) {
                    onIntent(CaptureIntent.IdlePreviewResized(chosen))
                    previewTexture?.setDefaultBufferSize(chosen.width, chosen.height)
                    restoreIdlePreview()
                }
            },
        )
    }
    if (!state.chromeVisible) {
        CaptureFinalizingOverlay(
            failure = state.finalizeFailure,
            onDismissFailure = { onIntent(CaptureIntent.FinalizeFailureDismissed) },
        )
    }
    if (state.showStopConfirmation) {
        CaptureStopConfirmation(
            onConfirm = {
                onIntent(CaptureIntent.StopDismissed)
                finalizeCapture()
            },
            onDismiss = { onIntent(CaptureIntent.StopDismissed) },
        )
    }
}

private fun Context.openArCoreStore() {
    val marketIntent = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.ar.core"))
    val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=com.google.ar.core"))
    startActivity(if (marketIntent.resolveActivity(packageManager) != null) marketIntent else webIntent)
}

// Tracking 판정 주기. 안정화(1초)와 유실(0.5초) 임계값보다 충분히 촘촘해야 마감 시점이 제때 발화한다.
private const val TRACKING_TICK_MS = 100L

/** 프리뷰와 영상의 가로세로 비. 두 녹화 해상도 모두 16:9라 선택과 무관하게 같다. */
private const val PREVIEW_ASPECT_RATIO = 16f / 9f
