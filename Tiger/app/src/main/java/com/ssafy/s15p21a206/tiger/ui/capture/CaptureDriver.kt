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
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
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
import com.ssafy.s15p21a206.tiger.ui.common.findActivity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 수집 작업 공간이 사용자 조작에 대해 실제로 하는 일들.
 *
 * 화면은 무엇을 그릴지만 알고, 카메라 세션을 열고 ARCore를 띄우고 Session을 마감하는 것은
 * 여기가 한다. [rememberCaptureDriver]가 만든다.
 */
internal class CaptureDriver(
    /** 작업 공간의 알림을 띄우는 자리. 문구는 상태의 `notice`에서 온다. */
    val snackbarHostState: SnackbarHostState,
    val onSurfaceAvailable: (Surface, SurfaceTexture) -> Unit,
    val onSurfaceDestroyed: () -> Unit,
    /** Idle이면 Session을, Ready면 Episode를 시작한다. */
    val play: () -> Unit,
    val pause: () -> Unit,
    /** 상태에 따라 무시하거나, 확인을 묻거나, 그냥 닫는다. */
    val requestExit: () -> Unit,
    val confirmStop: () -> Unit,
    val confirmMetadata: () -> Unit,
    /** 작업 공간을 벗어날 때 유휴 프리뷰 Camera2 session을 놓는다. */
    val releaseIdlePreview: () -> Unit,
)

/**
 * 수집 파이프라인을 세우고 그 조작을 [CaptureDriver]로 돌려준다.
 *
 * 평범한 클래스로 두지 못하는 이유가 있다. 권한 `rememberLauncherForActivityResult`는 composition
 * 에서만 만들 수 있고, tracking 폴링과 `ON_STOP`·`ON_START` 처리도 composition의 effect다.
 * 대신 무거운 것들은 [remember]로 한 번만 만들고, 돌려주는 [CaptureDriver]는 매 composition
 * 새로 만든다 — 그래야 콜백이 최신 [state]를 본다.
 *
 * `previewSurface`·`previewTexture`가 여기 있는 것은 Camera2 session을 여는 쪽이 여기이기
 * 때문이다. 화면은 Surface가 생기고 사라졌다는 사실만 알린다.
 */
@Suppress("LongMethod", "CyclomaticComplexMethod")
@Composable
internal fun rememberCaptureDriver(
    state: CaptureUiState,
    onIntent: (CaptureIntent) -> Unit,
    repository: SessionRepository,
    resolutionStore: RecordingResolutionStore,
    onCompleted: (sessionId: String, startUpload: Boolean) -> Unit,
): CaptureDriver {
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
                            // 프리뷰용 Camera2 세션은 play에서 이미 닫혔으므로 버퍼 크기를 바꿔도 안전하다.
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
                            coordinator.start(
                                bundle.sessionId,
                                bundle.displayNumber,
                                bundle.directory.absolutePath,
                                state.task,
                                state.objectName,
                            )
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
                                    task = state.task,
                                    objectName = state.objectName,
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
                    state.task,
                    state.objectName,
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
                                    state.task,
                                    state.objectName,
                                )
                            repository.save(completedSession)
                            // 백그라운드에서 마감됐으면 전송을 걸지 않고 실패로 남긴다.
                            val startUpload = lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
                            if (!startUpload) repository.save(completedSession.copy(uploadState = UploadState.FAILED))
                            // 어디로 갈지는 부모가 정한다. 수집은 목적지를 모른다.
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

    // 매 composition 새로 만든다. 콜백이 remember에 갇히면 옛 state를 보게 된다.
    return CaptureDriver(
        snackbarHostState = snackbarHostState,
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
        play = play@{
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
        pause = pause@{
            if (!state.policy.canPause) return@pause
            // 기록은 coordinator의 onEpisodeClosed가 담당한다.
            runCatching { coordinator.endEpisode() }
                .onSuccess { onIntent(CaptureIntent.EpisodeEnded) }
                .onFailure { onIntent(CaptureIntent.Notify(operationFailureMessage)) }
        },
        requestExit = {
            when (state.policy.exitAction) {
                CaptureExitAction.Ignore -> Unit
                CaptureExitAction.Confirm -> onIntent(CaptureIntent.StopRequested)
                // 녹화 전에는 Session을 만들지 않고 작업 공간만 닫는다. 아래에 목록이 그대로 남아 있다.
                CaptureExitAction.Leave -> onIntent(CaptureIntent.Close)
            }
        },
        confirmStop = {
            onIntent(CaptureIntent.StopDismissed)
            finalizeCapture()
        },
        // 확정한 선택만 기억한다. 취소하고 나간 선택은 다음 수집의 기본값이 되지 않는다.
        confirmMetadata = {
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
        releaseIdlePreview = capturePreviewController::release,
    )
}

private fun Context.openArCoreStore() {
    val marketIntent = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.ar.core"))
    val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=com.google.ar.core"))
    startActivity(if (marketIntent.resolveActivity(packageManager) != null) marketIntent else webIntent)
}

// Tracking 판정 주기. 안정화(1초)와 유실(0.5초) 임계값보다 충분히 촘촘해야 마감 시점이 제때 발화한다.
private const val TRACKING_TICK_MS = 100L
