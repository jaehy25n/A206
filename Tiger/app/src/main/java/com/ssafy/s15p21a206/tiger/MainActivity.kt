package com.ssafy.s15p21a206.tiger

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.view.Surface
import android.view.TextureView
import android.view.View
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import androidx.room.Room
import com.google.ar.core.ArCoreApk
import com.google.ar.core.exceptions.UnavailableArcoreNotInstalledException
import com.ssafy.s15p21a206.tiger.capture.AndroidCaptureRuntime
import com.ssafy.s15p21a206.tiger.capture.CameraPreviewController
import com.ssafy.s15p21a206.tiger.capture.CameraPreviewTransform
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewController
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewPreflight
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewState
import com.ssafy.s15p21a206.tiger.capture.CaptureSessionCoordinator
import com.ssafy.s15p21a206.tiger.capture.MonotonicClock
import com.ssafy.s15p21a206.tiger.capture.PreviewRuntime
import com.ssafy.s15p21a206.tiger.capture.RecordingResolutionStore
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_2_3
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_3_4
import com.ssafy.s15p21a206.tiger.data.local.TigerDatabase
import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.episode.ExportState
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.RecordingInputValidator
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.SafDocumentTreeGateway
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleExporter
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.episode.TrackingState
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureControlPolicy
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureExitAction
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureFinalizingOverlay
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureStopConfirmation
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControls
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceExitControls
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceResolution
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceStatus
import com.ssafy.s15p21a206.tiger.ui.common.ListSectionHeader
import com.ssafy.s15p21a206.tiger.ui.common.MetaText
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeader
import com.ssafy.s15p21a206.tiger.ui.common.SupportingText
import com.ssafy.s15p21a206.tiger.ui.session.SessionDetailPresentation
import com.ssafy.s15p21a206.tiger.ui.session.SessionListScreen
import com.ssafy.s15p21a206.tiger.ui.session.TaskSessionListScreen
import com.ssafy.s15p21a206.tiger.ui.session.VideoResolutionState
import com.ssafy.s15p21a206.tiger.ui.session.rememberVideoResolution
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import com.ssafy.s15p21a206.tiger.ui.upload.cancelUploadOnStop
import com.ssafy.s15p21a206.tiger.ui.upload.labelRes
import com.ssafy.s15p21a206.tiger.upload.SessionUploadRequestFactory
import com.ssafy.s15p21a206.tiger.upload.SessionUploadService
import com.ssafy.s15p21a206.tiger.upload.SessionUploader
import com.ssafy.s15p21a206.tiger.upload.UploadResult
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import okhttp3.OkHttpClient
import java.io.File

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { TigerTheme { CaptureScreen() } }
    }
}

// 조회 흐름의 목적지다. 인자는 Navigation Compose의 type-safe route로 전달한다. Task 이름은
// 사용자가 자유롭게 입력하는 문자열이라 `/`나 공백이 들어올 수 있는데, route 문자열을 직접
// 조립하면 그 값이 경로를 깨뜨린다.
//
// 수집 작업 공간은 목적지가 아니다. 진입 경로가 하나뿐이고, 뒤로 가기가 "이전 화면으로"가 아니라
// "종료할까요?"이며, 안에 또 모달을 품는다. 백스택 pop이 아닌 해제 가드이므로 CaptureScreen의
// boolean 상태로 두고 NavHost 위에 모달로 얹는다.
@Serializable
private data object SessionListRoute

@Serializable
private data class TaskSessionsRoute(
    val taskName: String,
)

@Serializable
private data class SessionDetailRoute(
    val sessionId: String,
)

@Serializable
private data class SessionVideoRoute(
    val sessionId: String,
)

@OptIn(ExperimentalMaterial3Api::class)
@Suppress("FunctionName")
@Composable
fun CaptureScreen() {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val database =
        remember {
            Room
                .databaseBuilder(
                    context.applicationContext,
                    TigerDatabase::class.java,
                    "tiger.db",
                ).addMigrations(MIGRATION_2_3, MIGRATION_3_4)
                .build()
        }
    val repository =
        remember {
            SessionRepository(
                database.captureSessionDao(),
                database.episodeMarkerDao(),
                SessionBundleStore(context.applicationContext),
            )
        }
    val uploadService =
        remember {
            BuildConfig.UPLOAD_BASE_URL.takeIf(String::isNotBlank)?.let { baseUrl ->
                SessionUploadService(
                    repository,
                    SessionUploader(
                        OkHttpClient
                            .Builder()
                            .followRedirects(false)
                            .followSslRedirects(false)
                            .build(),
                        SessionUploadRequestFactory(baseUrl),
                    ),
                )
            }
        }
    val completedSessions by repository.observeCompleted().collectAsState(emptyList())
    val completedSummaries by repository.observeCompletedSummaries().collectAsState(emptyList())
    val scope = rememberCoroutineScope()
    val gateway = remember { SafDocumentTreeGateway(context.applicationContext) }
    val exporter = remember { SessionBundleExporter(gateway) }
    val captureRuntime = remember { AndroidCaptureRuntime(context.applicationContext, SessionBundleStore(context.applicationContext)) }
    var controlBusy by remember { mutableStateOf(false) }
    var finalizing by remember { mutableStateOf(false) }
    var finalizeFailure by remember { mutableStateOf<String?>(null) }
    var previewReady by remember { mutableStateOf(false) }
    var previewFailed by remember { mutableStateOf(false) }
    val snackbarHostState = remember { SnackbarHostState() }
    val previewFailureMessage = stringResource(R.string.capture_preview_failed)
    val operationFailureMessage = stringResource(R.string.capture_operation_failed)
    var collecting by remember { mutableStateOf(false) }
    var active by remember { mutableStateOf(false) }
    var task by remember { mutableStateOf("") }
    var objectName by remember { mutableStateOf("") }
    val resolutionStore = remember { RecordingResolutionStore(context.applicationContext) }

    /**
     * 유휴 프리뷰·수집 중 프리뷰·녹화가 함께 쓰는 해상도.
     *
     * 수집 전에는 사용자가 고른 값이고, 수집을 시작하면 ARCore가 실제로 고른 `textureSize`로
     * 갱신된다. 후보 config가 없어 기본값으로 물러난 경우에도 세 경로가 같은 크기를 유지한다.
     * 직전 선택은 여기가 아니라 [resolutionStore]가 들고 있으므로, 이 갱신이 다음 수집의
     * 기본값을 바꾸지는 않는다.
     */
    var recordingResolution by remember { mutableStateOf(resolutionStore.load()) }

    // 유휴 프리뷰 Camera2 session이 실제로 열려 있는 크기. Camera2는 session을 만들 때 stream
    // 크기를 정하므로, 이 값이 recordingResolution과 어긋나면 session을 다시 열어야 반영된다.
    var idlePreviewSize by remember { mutableStateOf(recordingResolution) }
    var message by remember { mutableStateOf("") }
    var previewSurface by remember { mutableStateOf<Surface?>(null) }
    // 수집 시작 시 ARCore가 고른 해상도로 버퍼를 다시 맞추려면 SurfaceTexture를 들고 있어야 한다.
    var previewTexture by remember { mutableStateOf<SurfaceTexture?>(null) }
    val previewController =
        remember {
            CameraPreviewController(context.applicationContext) { _ ->
                previewReady = false
                previewFailed = true
                message = previewFailureMessage
            }
        }
    val capturePreviewController =
        remember {
            CapturePreviewController(
                preflight =
                    CapturePreviewPreflight {
                        when {
                            androidx.core.content.ContextCompat.checkSelfPermission(
                                context,
                                Manifest.permission.CAMERA,
                            ) != android.content.pm.PackageManager.PERMISSION_GRANTED -> "Camera permission is required for preview"
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
    var exportState by remember { mutableStateOf(ExportState.NOT_EXPORTED) }
    var exportMessage by remember { mutableStateOf<String?>(null) }
    var pendingSessionId by remember { mutableStateOf<String?>(null) }
    var activeBundle by remember { mutableStateOf<com.ssafy.s15p21a206.tiger.episode.SessionBundle?>(null) }
    var recordingStartNs by remember { mutableLongStateOf(0L) }
    var activeEpisode by remember { mutableStateOf<EpisodeMarker?>(null) }
    var arCoreInstallRequested by remember { mutableStateOf(false) }
    val navController = rememberNavController()
    val currentEntry by navController.currentBackStackEntryAsState()

    /**
     * 수집 작업 공간을 띄우고 있는지 여부다.
     *
     * 프로세스가 재생성되면 복원하지 않는다. `ON_STOP`에서 진행 중인 Session을 `INTERRUPTED`로
     * 마감하므로, 되살려도 수집 상태가 없는 빈 작업 공간이 된다. 조회 흐름의 백스택은 NavHost가
     * 저장 상태로 복원한다. 화면 회전은 manifest의 `configChanges`가 받으므로 이 상태도 유지된다.
     */
    var capturing by remember { mutableStateOf(false) }
    var uploadJob by remember { mutableStateOf<Job?>(null) }
    var uploadFailureReason by remember { mutableStateOf<String?>(null) }
    var showStopConfirmation by remember { mutableStateOf(false) }
    var showCaptureMetadataDialog by remember { mutableStateOf(false) }
    var trackingReady by remember { mutableStateOf(false) }
    val episodeInvalidatedMessage = stringResource(R.string.capture_episode_invalid_tracking)
    val coordinator =
        remember {
            CaptureSessionCoordinator(
                clock = MonotonicClock(SystemClock::elapsedRealtimeNanos),
                writers = emptyList(),
                onEpisodeClosed = { marker ->
                    // 사용자 종료와 Tracking 유실 자동 마감이 같은 경로로 기록된다.
                    if (marker.outcome == EpisodeState.INVALID_TRACKING) message = episodeInvalidatedMessage
                    scope.launch {
                        runCatching {
                            repository.save(marker)
                            captureRuntime.appendEpisode(marker)
                        }.onFailure { message = operationFailureMessage }
                    }
                },
            )
        }

    fun controlPolicy() =
        CaptureControlPolicy(
            state =
                when {
                    finalizing -> CaptureWorkspaceControlState.Finalizing
                    !collecting -> CaptureWorkspaceControlState.Idle
                    active -> CaptureWorkspaceControlState.EpisodeActive
                    // ARCore Tracking이 안정화되기 전에는 Episode를 시작할 수 없다.
                    trackingReady -> CaptureWorkspaceControlState.Ready
                    else -> CaptureWorkspaceControlState.Initializing
                },
            ready = previewReady && !previewFailed && task.isNotBlank() && objectName.isNotBlank() && !showCaptureMetadataDialog,
            busy = controlBusy,
        )

    fun requestCaptureExit() {
        when (controlPolicy().exitAction) {
            CaptureExitAction.Ignore -> Unit
            CaptureExitAction.Confirm -> showStopConfirmation = true
            // 녹화 전에는 Session을 만들지 않고 작업 공간만 닫는다. 아래에 목록이 그대로 남아 있다.
            CaptureExitAction.Leave -> {
                showCaptureMetadataDialog = false
                capturing = false
            }
        }
    }
    val pickerCancelled = stringResource(R.string.export_picker_cancelled)
    val exportGrantFailed = stringResource(R.string.export_grant_failed)
    val exportFailedUnexpected = stringResource(R.string.export_failed_unexpected)
    val recordingCameraUnavailable = stringResource(R.string.recording_camera_unavailable)
    val activeEpisodeEndRequired = stringResource(R.string.active_episode_end_required)
    val trackingNotReadyMessage = stringResource(R.string.capture_tracking_not_ready)
    val captureFinalizeFailed = stringResource(R.string.capture_finalize_failed)
    val arCoreUnavailable = stringResource(R.string.arcore_unavailable)
    val arCoreInstallMessage = stringResource(R.string.arcore_install_requested)
    val arCoreSessionStartFailed = stringResource(R.string.arcore_session_start_failed)
    val uploadEndpointMissing = stringResource(R.string.upload_endpoint_missing)
    LaunchedEffect(repository) {
        repository.recoverInterruptedStaging()
        repository.failInterruptedUploads()
        repository.normalizeDisplayNumbers()
    }
    val treePicker =
        rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            if (uri == null) {
                exportState = ExportState.EXPORT_FAILED
                exportMessage = pickerCancelled
            } else {
                val sessionId = pendingSessionId ?: return@rememberLauncherForActivityResult
                val grantFailure =
                    runCatching {
                        gateway.persistGrant(
                            uri,
                            android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                        )
                    }.exceptionOrNull()
                if (grantFailure != null) {
                    exportState = ExportState.EXPORT_FAILED
                    exportMessage = grantFailure.message ?: exportGrantFailed
                    return@rememberLauncherForActivityResult
                }
                scope.launch {
                    exportState = ExportState.EXPORTING
                    when (
                        val result =
                            runCatching { exporter.exportCompleted(repository, sessionId, uri.toString()) }
                                .getOrElse { SessionBundleExporter.ExportAttemptResult.Failed(it.message ?: exportFailedUnexpected, "") }
                    ) {
                        is SessionBundleExporter.ExportAttemptResult.Exported -> {
                            exportState = ExportState.EXPORTED
                            exportMessage = null
                        }
                        is SessionBundleExporter.ExportAttemptResult.Failed -> {
                            exportState = ExportState.EXPORT_FAILED
                            exportMessage =
                                result.reason
                        }
                    }
                }
            }
        }

    // ARCore가 카메라를 놓은 뒤 유휴 Camera2 프리뷰를 되살린다.
    // prepare()는 Ready 상태에서 즉시 반환하므로 먼저 Idle로 되돌려야 실제로 다시 연다.
    fun restoreIdlePreview() {
        if (previewSurface == null) return
        capturePreviewController.release()
        if (capturePreviewController.prepare() is CapturePreviewState.Failed) {
            previewFailed = true
            message = previewFailureMessage
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
                        message = arCoreUnavailable
                        controlBusy = false
                        return@rememberLauncherForActivityResult
                    }
                if (installStatus == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                    arCoreInstallRequested = true
                    message = arCoreInstallMessage
                    controlBusy = false
                    return@rememberLauncherForActivityResult
                }
                scope.launch {
                    try {
                        val displayNumber = repository.nextDisplayNumber()
                        runCatching {
                            // ARCore가 고른 해상도로 버퍼를 맞춰 프리뷰 화각을 저장 영상과 일치시킨다.
                            // 이 람다는 Main dispatcher에서 실행되므로 Compose 상태를 직접 갱신해도 된다.
                            // 프리뷰용 Camera2 세션은 onPlay에서 이미 닫혔으므로 버퍼 크기를 바꿔도 안전하다.
                            captureRuntime.start(displayNumber, recordingResolution) { width, height ->
                                // ARCore가 실제로 고른 크기다. 후보 config가 없어 기본값으로 물러났으면
                                // 고른 값과 다를 수 있으므로, 표시와 프리뷰를 여기에 맞춘다.
                                val actual = RecordingResolution(width, height)
                                recordingResolution = actual
                                idlePreviewSize = actual
                                previewTexture?.setDefaultBufferSize(width, height)
                                previewSurface
                            }
                        }.onSuccess { bundle ->
                            activeBundle = bundle
                            recordingStartNs = SystemClock.elapsedRealtimeNanos()
                            // Session 시작은 Episode를 만들지 않는다. Tracking 안정화 뒤 사용자가 따로 시작한다.
                            coordinator.start(bundle.sessionId, bundle.displayNumber, bundle.directory.absolutePath)
                            activeEpisode = null
                            collecting = true
                            active = false
                            repository.save(
                                CaptureSession(
                                    bundle.sessionId,
                                    bundle.displayNumber,
                                    RecordingState.INITIALIZING,
                                    UploadState.LOCAL_ONLY,
                                    recordingStartNs,
                                    bundlePath = bundle.directory.absolutePath,
                                    recordingStartEpochMs = System.currentTimeMillis(),
                                ),
                            )
                        }.onFailure { error ->
                            // ARCore가 카메라를 잡지 못했으므로 유휴 프리뷰를 되살린다.
                            restoreIdlePreview()
                            message = "$arCoreSessionStartFailed: ${error.message.orEmpty()}"
                            if (error is UnavailableArcoreNotInstalledException) {
                                context.openArCoreStore()
                            }
                        }
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (_: Exception) {
                        message = operationFailureMessage
                    } finally {
                        controlBusy = false
                    }
                }
            } else {
                message = recordingCameraUnavailable
                controlBusy = false
            }
        }
    val previewPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted && previewSurface != null) {
                previewFailed = false
                capturePreviewController.release()
                if (capturePreviewController.prepare() is CapturePreviewState.Failed) {
                    previewFailed = true
                    message = previewFailureMessage
                }
            } else if (!granted) {
                previewFailed = true
                message = previewFailureMessage
            }
        }
    LaunchedEffect(capturing) {
        if (capturing) {
            previewPermission.launch(Manifest.permission.CAMERA)
        }
    }
    // onTracking은 호출 시점 기준으로 경과 시간을 판정하므로, 값이 변하지 않아도 계속 호출되어야
    // 안정화(1초)와 유실(0.5초) 마감이 발화한다. 값 변화 구독만으로는 유실 마감이 오지 않는다.
    LaunchedEffect(collecting) {
        if (!collecting) {
            trackingReady = false
            return@LaunchedEffect
        }
        while (true) {
            val sample = captureRuntime.tracking.value
            coordinator.onTracking(sample.isTracking, sample.observedAtNs.takeIf { it > 0L })
            trackingReady = coordinator.trackingState == TrackingState.READY
            // Tracking 유실 자동 마감은 사용자 조작 없이 일어나므로 화면 상태를 여기서 맞춘다.
            activeEpisode = coordinator.activeEpisode
            active = activeEpisode != null
            delay(TRACKING_TICK_MS)
        }
    }
    LaunchedEffect(message, capturing) {
        if (capturing && message.isNotBlank()) {
            val notice = message
            message = ""
            scope.launch { snackbarHostState.showSnackbar(notice) }
        }
    }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
        // 백그라운드 업로드는 하지 않는다. 판정 기준이 "업로드 화면에 있는가"였으나 그 화면을 없애
        // 전송이 진행 중인지로 바꾼다. 어느 화면에 있든 전송 중이면 끊고 FAILED로 남긴다.
        if (cancelUploadOnStop(uploadInFlight = uploadJob?.isActive == true)) {
            uploadJob?.cancel()
        }
        if (finalizing) return@LifecycleEventEffect
        val interruptedBundle = activeBundle ?: return@LifecycleEventEffect
        captureRuntime.interrupt()
        scope.launch {
            repository.save(
                CaptureSession(
                    interruptedBundle.sessionId,
                    interruptedBundle.displayNumber,
                    RecordingState.INTERRUPTED,
                    UploadState.LOCAL_ONLY,
                    recordingStartNs,
                    SystemClock.elapsedRealtimeNanos(),
                    interruptedBundle.directory.absolutePath,
                    System.currentTimeMillis(),
                ),
            )
        }
        activeBundle = null
        activeEpisode = null
        active = false
        collecting = false
        coordinator.release()
        trackingReady = false
    }
    // 백그라운드 전환으로 카메라를 놓고 돌아온 경우 TextureView는 살아 있지만 프레임이 끊긴 상태다.
    LifecycleEventEffect(Lifecycle.Event.ON_START) {
        if (capturing && !collecting) restoreIdlePreview()
    }

    /**
     * 수집 정보 입력부터 시작한다.
     *
     * [initialTask]는 이미 알고 있는 Task 이름이다. Task의 세션 목록에서 시작하면 그 이름이
     * 채워진 채로 열려 같은 이름을 다시 입력하지 않는다. 채워진 뒤에도 고칠 수 있게 두므로,
     * 잘못 들어왔더라도 나갔다 올 필요는 없다.
     */
    fun startCapture(initialTask: String) {
        previewReady = false
        previewFailed = false
        showStopConfirmation = false
        task = initialTask
        objectName = ""
        recordingResolution = resolutionStore.load()
        // 새 TextureView가 이 크기로 버퍼를 잡는다. 직전 Session이 남긴 크기를 물려받지 않는다.
        idlePreviewSize = recordingResolution
        message = ""
        showCaptureMetadataDialog = true
        capturing = true
    }

    /**
     * 전송을 걸고 실패 사유를 받아 둔다.
     *
     * 사유는 화면에만 쓰고 저장하지 않는다. 업로드에는 내보내기의 `exportFailureReason`에 해당하는
     * 컬럼이 없고, 무엇이 막았는지는 실패한 자리에서 보면 되는 값이다.
     */
    fun launchUpload(
        service: SessionUploadService,
        sessionId: String,
    ) {
        uploadFailureReason = null
        uploadJob =
            scope.launch {
                val result = runCatching { service.upload(sessionId) }.getOrNull()
                uploadFailureReason = (result as? UploadResult.Failed)?.reason
            }
    }

    /**
     * 전송을 걸고 그 세션의 상세를 띄운다.
     *
     * 마감이 끝나면 세션은 저장되어 존재한다. 존재하는 것에 무슨 일이 일어나는지는 그것의 화면에서
     * 보여 주면 되므로 전송만을 위한 목적지를 따로 두지 않는다. 전송은 네트워크에 매여 길어질 수
     * 있어 사용자를 붙잡아 둘 수도 없다.
     */
    fun startUpload(sessionId: String) {
        val service = uploadService
        if (service == null) {
            message = uploadEndpointMissing
            return
        }
        // 상세로 넘어가므로 작업 공간을 닫는다. 남겨 두면 NavHost를 계속 덮는다.
        capturing = false
        if (currentEntry?.destination?.hasRoute<SessionDetailRoute>() != true) {
            navController.navigate(SessionDetailRoute(sessionId))
        }
        launchUpload(service, sessionId)
    }

    /** 이미 그 세션의 상세에 있으므로 목적지를 다시 쌓지 않고 전송만 새로 건다. */
    fun retryUpload(sessionId: String) {
        val service = uploadService
        if (service == null) {
            message = uploadEndpointMissing
            return
        }
        launchUpload(service, sessionId)
    }
    val sharedVideoPlayer = rememberSharedVideoPlayer()
    // 재생 화면을 벗어나면 decoder를 계속 물고 있지 않도록 재생기를 놓는다.
    LaunchedEffect(currentEntry) {
        val onPlaybackRoute =
            currentEntry?.destination?.let { it.hasRoute<SessionDetailRoute>() || it.hasRoute<SessionVideoRoute>() } == true
        if (!onPlaybackRoute) sharedVideoPlayer.release()
    }

    fun finalizeCapture() {
        if (!controlPolicy().canStop) return
        // 진행 중인 Episode가 있으면 Session을 마감하지 않고 먼저 종료하도록 안내한다.
        if (coordinator.activeEpisode != null) {
            message = activeEpisodeEndRequired
            return
        }
        finalizing = true
        scope.launch {
            try {
                activeEpisode = null
                active = false
                when (
                    val result =
                        runCatching { withContext(Dispatchers.IO) { captureRuntime.stop() } }
                            .getOrElse { FinalizeResult.Failed(it.message.orEmpty()) }
                ) {
                    is FinalizeResult.Completed -> {
                        activeBundle?.let { bundle ->
                            val completedSession =
                                CaptureSession(
                                    bundle.sessionId,
                                    bundle.displayNumber,
                                    RecordingState.COMPLETED,
                                    UploadState.LOCAL_ONLY,
                                    recordingStartNs,
                                    SystemClock.elapsedRealtimeNanos(),
                                    result.directory.absolutePath,
                                    System.currentTimeMillis(),
                                )
                            repository.save(completedSession)
                            if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
                                startUpload(bundle.sessionId)
                            } else {
                                repository.save(completedSession.copy(uploadState = UploadState.FAILED))
                                capturing = false
                                navController.navigate(SessionDetailRoute(bundle.sessionId))
                            }
                        }
                    }
                    // 마감 실패는 지나가는 알림이 아니다. 저장된 세션이 없으므로 넘어갈 곳도 없다.
                    // 작업 공간을 덮은 판에 세워 두고, 확인을 받은 뒤에야 다시 찍을 수 있게 한다.
                    is FinalizeResult.Failed -> finalizeFailure = "$captureFinalizeFailed: ${result.reason}"
                }
                activeBundle = null
                collecting = false
                // 다음 Session을 시작할 수 있도록 Coordinator의 Session·Tracking 상태를 닫는다.
                coordinator.release()
                trackingReady = false
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                finalizeFailure = captureFinalizeFailed
            } finally {
                finalizing = false
                // 마감에 성공하면 업로드·상세 화면으로 이동해 TextureView가 사라지므로 되살릴 필요가 없다.
                // 수집 화면에 그대로 남는 실패 경로에서만 유휴 프리뷰를 다시 연다.
                if (capturing) restoreIdlePreview()
            }
        }
    }

    // 조회 흐름은 NavHost가, 수집 작업 공간은 그 위의 모달이 담당한다. 작업 공간이 NavHost
    // 바깥에 있으므로 수집 상태가 백스택 조작과 무관하게 남고, ARCore·프리뷰 Surface·업로드 Job의
    // 수명주기를 건드리지 않는다.
    Box(modifier = Modifier.fillMaxSize()) {
        NavHost(
            navController = navController,
            startDestination = SessionListRoute,
            modifier = Modifier.fillMaxSize(),
            // NavHost의 기본 전환은 좌우 슬라이드다. 이관 전에는 화면이 즉시 바뀌었고, 이 앱에는
            // 전환 애니메이션을 도입할 이유가 없다. 수집 마감 경로는 Detail과 업로드 상태를 한
            // 프레임에 연달아 쌓으므로 애니메이션이 있으면 슬라이드가 두 번 겹쳐 보인다.
            enterTransition = { EnterTransition.None },
            exitTransition = { ExitTransition.None },
            popEnterTransition = { EnterTransition.None },
            popExitTransition = { ExitTransition.None },
        ) {
            composable<SessionListRoute> {
                DestinationSurface {
                    SessionListScreen(
                        sessions = completedSummaries,
                        onStartCapture = { startCapture("") },
                        onOpenTask = { taskName -> navController.navigate(TaskSessionsRoute(taskName)) },
                    )
                }
            }
            composable<TaskSessionsRoute> { entry ->
                val route = entry.toRoute<TaskSessionsRoute>()
                DestinationSurface {
                    TaskSessionListScreen(
                        taskName = route.taskName,
                        sessions = completedSummaries.filter { it.taskName.trim() == route.taskName },
                        onBack = navController::popBackStack,
                        onOpenSession = { sessionId -> navController.navigate(SessionDetailRoute(sessionId)) },
                        // 이름 없는 Task 묶음은 이름이 빈 세션들이라 채울 것이 없다. 빈 채로 연다.
                        onStartCapture = { startCapture(route.taskName) },
                    )
                }
            }
            composable<SessionDetailRoute> { entry ->
                val route = entry.toRoute<SessionDetailRoute>()
                DestinationSurface {
                    SessionDetailScreen(
                        summary = completedSummaries.firstOrNull { it.sessionId == route.sessionId },
                        onBack = navController::popBackStack,
                        onUpload = { startUpload(route.sessionId) },
                        exportState = exportState,
                        exportMessage = exportMessage,
                        onExport = {
                            pendingSessionId = route.sessionId
                            treePicker.launch(null)
                        },
                        sharedPlayer = sharedVideoPlayer,
                        onOpenFullscreenVideo = { navController.navigate(SessionVideoRoute(route.sessionId)) },
                        uploadFailureReason = uploadFailureReason,
                    )
                }
            }
            composable<SessionVideoRoute> { entry ->
                val route = entry.toRoute<SessionVideoRoute>()
                // 전체화면은 스스로 검은 배경을 꽉 채우므로 판을 따로 깔지 않는다.
                FullScreenVideoScreen(
                    bundlePath = completedSummaries.firstOrNull { it.sessionId == route.sessionId }?.bundlePath,
                    sharedPlayer = sharedVideoPlayer,
                    onBack = navController::popBackStack,
                )
            }
        }
        if (capturing) {
            // 작업 공간을 벗어나면 유휴 프리뷰 Camera2 session을 놓는다. 조회 화면이 카메라를
            // 붙잡고 있을 이유가 없고, 다음 수집은 새 Surface로 다시 연다.
            DisposableEffect(capturePreviewController) {
                onDispose(capturePreviewController::release)
            }
            // 수집 화면은 가로로 고정한다. Camera 센서가 90도 눕혀 장착돼 있어 세로 화면에서는
            // 프리뷰가 옆으로 누운 채 비율까지 어긋나 보인다. 저장되는 영상도 가로다.
            LockLandscapeWhileVisible()
            Box(Modifier.fillMaxSize().background(Color.Black)) {
                AndroidView(
                    factory = { viewContext ->
                        TextureView(viewContext).apply {
                            surfaceTextureListener =
                                object : TextureView.SurfaceTextureListener {
                                    override fun onSurfaceTextureAvailable(
                                        surfaceTexture: SurfaceTexture,
                                        width: Int,
                                        height: Int,
                                    ) {
                                        surfaceTexture.setDefaultBufferSize(idlePreviewSize.width, idlePreviewSize.height)
                                        previewTexture = surfaceTexture
                                        previewSurface = Surface(surfaceTexture)
                                        applyIdlePreviewTransform(this@apply, width, height, idlePreviewSize.width, idlePreviewSize.height)
                                        when (val state = capturePreviewController.prepare()) {
                                            is CapturePreviewState.Failed -> {
                                                previewFailed = true
                                                message = previewFailureMessage
                                            }
                                            else -> Unit
                                        }
                                    }

                                    override fun onSurfaceTextureSizeChanged(
                                        surfaceTexture: SurfaceTexture,
                                        width: Int,
                                        height: Int,
                                    ) = applyIdlePreviewTransform(this@apply, width, height, idlePreviewSize.width, idlePreviewSize.height)

                                    override fun onSurfaceTextureDestroyed(surfaceTexture: SurfaceTexture): Boolean {
                                        capturePreviewController.release()
                                        previewSurface?.release()
                                        previewSurface = null
                                        previewTexture = null
                                        previewReady = false
                                        return true
                                    }

                                    override fun onSurfaceTextureUpdated(surfaceTexture: SurfaceTexture) {
                                        if (!previewFailed) previewReady = true
                                    }
                                }
                        }
                    },
                    // 변환은 유휴 프리뷰에만 건다. 수집이 시작되면 ARCore가 같은 Surface에 표시 기하를
                    // 반영해 직접 그리므로, TextureView 변환이 남아 있으면 그 위에 한 번 더 돌아간다.
                    update = { view ->
                        if (collecting) {
                            view.setTransform(Matrix())
                        } else {
                            applyIdlePreviewTransform(view, view.width, view.height, idlePreviewSize.width, idlePreviewSize.height)
                        }
                    },
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
                val workspaceChromeVisible = !finalizing && finalizeFailure == null
                if (workspaceChromeVisible) {
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
                            CaptureWorkspaceStatus(state = controlPolicy().state)
                            // 어느 해상도로 찍는지 촬영 직전에 보여 준다. Session마다 달라질 수 있다.
                            CaptureWorkspaceResolution(resolution = recordingResolution)
                        }
                        CaptureWorkspaceExitControls(
                            policy = controlPolicy(),
                            onExit = ::requestCaptureExit,
                        )
                    }
                }
                SnackbarHost(snackbarHostState, Modifier.align(Alignment.TopCenter).padding(top = 80.dp))
                if (!showCaptureMetadataDialog && workspaceChromeVisible) {
                    CaptureWorkspaceControls(
                        state = controlPolicy().state,
                        ready = controlPolicy().ready,
                        busy = controlBusy,
                        onPlay = play@{
                            if (!controlPolicy().canPlay) return@play
                            if (!collecting) {
                                controlBusy = true
                                previewReady = false
                                capturePreviewController.release()
                                cameraPermission.launch(Manifest.permission.CAMERA)
                            } else {
                                // Episode 시작은 Coordinator가 Tracking 안정화 여부를 확인한 뒤에만 허용한다.
                                runCatching { coordinator.startEpisode(task, objectName) }
                                    .onSuccess {
                                        activeEpisode = it
                                        active = true
                                    }.onFailure { message = trackingNotReadyMessage }
                            }
                        },
                        onPause = pause@{
                            if (!controlPolicy().canPause) return@pause
                            controlBusy = true
                            // 기록은 coordinator의 onEpisodeClosed가 담당한다.
                            runCatching { coordinator.endEpisode() }
                                .onSuccess {
                                    activeEpisode = null
                                    active = false
                                }.onFailure { message = operationFailureMessage }
                            controlBusy = false
                        },
                        onStop = { if (controlPolicy().canStop) requestCaptureExit() },
                        modifier = Modifier.align(Alignment.BottomCenter),
                    )
                }
            }
            if (showCaptureMetadataDialog) {
                val focusManager = LocalFocusManager.current
                val objectFieldFocus = remember { FocusRequester() }
                val captureMetadataReady = task.isNotBlank() && objectName.isNotBlank()
                val cancelCaptureMetadata = {
                    showCaptureMetadataDialog = false
                    capturing = false
                }
                // 확정한 선택만 기억한다. 취소하고 나간 선택은 다음 수집의 기본값이 되지 않는다.
                val confirmCaptureMetadata = {
                    resolutionStore.save(recordingResolution)
                    showCaptureMetadataDialog = false
                    // 유휴 프리뷰도 고른 해상도로 다시 연다. Camera2는 session을 만들 때 stream 크기를
                    // 정하므로, 버퍼 크기만 바꾸면 이미 열린 session에는 반영되지 않는다.
                    if (idlePreviewSize != recordingResolution) {
                        idlePreviewSize = recordingResolution
                        previewTexture?.setDefaultBufferSize(recordingResolution.width, recordingResolution.height)
                        restoreIdlePreview()
                    }
                }
                // 키보드 입력이 필요한 다이얼로그는 Material 가이드라인상 전체화면으로 띄우고 확인·취소를
                // 상단 앱바에 둔다. 가운데 띄우는 다이얼로그는 가로 화면에서 키보드가 올라오면 아래쪽 버튼이
                // 가려져 닿을 방법이 없다. 앱바는 키보드와 겹치지 않으므로 방향과 무관하게 항상 누를 수 있다.
                Dialog(
                    onDismissRequest = cancelCaptureMetadata,
                    properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
                ) {
                    Surface(modifier = Modifier.fillMaxSize()) {
                        Column(modifier = Modifier.fillMaxSize().safeDrawingPadding()) {
                            TopAppBar(
                                title = { Text(stringResource(R.string.capture_metadata_title)) },
                                navigationIcon = {
                                    IconButton(onClick = cancelCaptureMetadata) {
                                        Icon(
                                            painter = painterResource(R.drawable.ic_navigation_back),
                                            contentDescription = stringResource(R.string.action_cancel),
                                        )
                                    }
                                },
                                actions = {
                                    TextButton(
                                        enabled = captureMetadataReady,
                                        onClick = confirmCaptureMetadata,
                                    ) { Text(stringResource(R.string.capture_metadata_confirm)) }
                                },
                            )
                            Column(
                                modifier =
                                    Modifier
                                        .fillMaxSize()
                                        .verticalScroll(rememberScrollState())
                                        .imePadding()
                                        .padding(horizontal = 24.dp, vertical = 16.dp),
                                verticalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                // Task가 채워진 채로 열렸으면 손댈 곳은 다음 칸이다. 이미 적혀 있는
                                // 칸에 커서를 두면 지우고 다시 쓰라는 신호로 읽힌다.
                                LaunchedEffect(Unit) {
                                    if (task.isNotBlank()) objectFieldFocus.requestFocus()
                                }
                                OutlinedTextField(
                                    value = task,
                                    onValueChange = { task = it },
                                    label = { Text(stringResource(R.string.capture_metadata_task)) },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                                    keyboardActions = KeyboardActions(onNext = { objectFieldFocus.requestFocus() }),
                                )
                                OutlinedTextField(
                                    value = objectName,
                                    onValueChange = { objectName = it },
                                    label = { Text(stringResource(R.string.capture_metadata_object)) },
                                    modifier = Modifier.focusRequester(objectFieldFocus),
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                                    keyboardActions =
                                        KeyboardActions(
                                            onDone = {
                                                if (captureMetadataReady) {
                                                    focusManager.clearFocus()
                                                    confirmCaptureMetadata()
                                                }
                                            },
                                        ),
                                )
                                RecordingResolutionPicker(
                                    selected = recordingResolution,
                                    onSelect = { recordingResolution = it },
                                )
                            }
                        }
                    }
                }
            }
            // 마감 중이거나 마감이 실패한 동안은 작업 공간을 덮는다. 제어가 이미 전부 막혀 있는
            // 구간이라 덮는 편이 상태를 정직하게 말한다.
            if (finalizing || finalizeFailure != null) {
                CaptureFinalizingOverlay(
                    failure = finalizeFailure,
                    onDismissFailure = { finalizeFailure = null },
                )
            }
            if (showStopConfirmation) {
                CaptureStopConfirmation(
                    onConfirm = {
                        showStopConfirmation = false
                        finalizeCapture()
                    },
                    onDismiss = { showStopConfirmation = false },
                )
            }
        }
    }
}

/**
 * 목적지 내용을 불투명한 판 위에 올린다.
 *
 * `NavHost`는 `AnimatedContent`로 목적지를 교체한다. 전환 애니메이션을 껐더라도 나가는 목적지가
 * 한 프레임 더 composition에 남으므로, 배경을 그리지 않으면 그 프레임에 두 화면의 내용이 같은
 * 창 배경 위에 겹쳐 그려져 이전 화면이 비쳐 보인다. `TigerTheme`에는 `Surface`가 없고 각 화면도
 * 배경을 그리지 않아, 판은 목적지마다 깔아야 한다.
 */
@Suppress("FunctionName")
@Composable
private fun DestinationSurface(content: @Composable () -> Unit) {
    // targetSdk 35부터 창이 시스템 바 아래까지 늘어난다. 목적지마다 막지 않으면 헤더가 상태 표시줄에,
    // 목록 끝이 제스처 바에 물린다. 판이 한 번 막으면 안에 놓이는 화면은 인셋을 몰라도 된다.
    Surface(modifier = Modifier.fillMaxSize().safeDrawingPadding(), content = content)
}

/**
 * 이번 Session으로 녹화할 해상도를 고른다.
 *
 * Session마다 다르게 갈 수 있으므로 Task·Object와 함께 매번 고른다. 후보는 실기기에서 확인한
 * ARCore Camera config의 `textureSize`이며, 순서는 [RecordingInputValidator.supportedResolutions]를 따른다.
 */
@Suppress("FunctionName")
@Composable
private fun RecordingResolutionPicker(
    selected: RecordingResolution,
    onSelect: (RecordingResolution) -> Unit,
) {
    Column(modifier = Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = stringResource(R.string.capture_metadata_resolution),
            style = MaterialTheme.typography.labelLarge,
        )
        RecordingInputValidator.supportedResolutions.forEach { option ->
            Row(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .selectable(
                            selected = option == selected,
                            role = Role.RadioButton,
                            onClick = { onSelect(option) },
                        ).padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 선택은 Row가 받는다. RadioButton에 onClick을 주면 터치 영역이 둘로 갈린다.
                RadioButton(selected = option == selected, onClick = null)
                Text(
                    text = stringResource(R.string.capture_resolution_option, option.width, option.height),
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }
    }
}

@Suppress("FunctionName")
@Composable
private fun SessionDetailScreen(
    summary: com.ssafy.s15p21a206.tiger.episode.SessionSummary?,
    onBack: () -> Unit,
    onUpload: () -> Unit,
    exportState: ExportState,
    exportMessage: String?,
    onExport: () -> Unit,
    uploadFailureReason: String?,
    sharedPlayer: SharedVideoPlayer,
    onOpenFullscreenVideo: () -> Unit,
) {
    var showSessionInfo by remember { mutableStateOf(false) }
    // 재생 영역 높이와 전송·내보내기 상태에 따라 내용이 화면을 넘는다. 스크롤이 없으면 잘린다.
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
    ) {
        NavigationHeader(
            // 어느 세션인지는 본문의 이름표가 말한다. 헤더에는 뒤로 가기와 정보만 남긴다.
            title = "",
            onBack = onBack,
        ) {
            // 사진 앱이 크기·형식·촬영 설정을 ⓘ 뒤 시트로 미뤄 두는 자리다. 뒤로 가기와 같은 급으로
            // 보이지 않도록 글리프를 작게, 색은 옅게 둔다.
            if (summary != null) {
                IconButton(onClick = { showSessionInfo = true }) {
                    Icon(
                        painter = painterResource(R.drawable.ic_session_info),
                        contentDescription = stringResource(R.string.session_info_title),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(SESSION_INFO_ICON_SIZE),
                    )
                }
            }
        }
        if (summary == null) {
            Text(
                text = stringResource(R.string.session_detail_unavailable),
                modifier = Modifier.padding(horizontal = DETAIL_CONTENT_PADDING),
            )
        } else {
            val presentation = SessionDetailPresentation.from(summary)
            // 영상은 좌우 여백 없이 화면 폭을 다 쓴다. 16:9 안에 컨트롤이 오버레이로 놓이므로
            // 여백을 주면 재생 영역만 줄고 얻는 것이 없다.
            SessionVideoPreview(summary.bundlePath, sharedPlayer, onOpenFullscreenVideo)
            Column(
                modifier =
                    Modifier.padding(
                        start = DETAIL_CONTENT_PADDING,
                        end = DETAIL_CONTENT_PADDING,
                        top = DETAIL_VIDEO_GAP,
                        bottom = DETAIL_CONTENT_PADDING,
                    ),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // 목록 화면의 이름표와 같은 짜임이다. 이 화면의 이름은 언제 찍은 것인지이고,
                // ID는 그것을 특정해 주지 않으므로 딸린 줄로 내린다.
                ListSectionHeader(
                    title =
                        java.text.DateFormat
                            .getDateTimeInstance()
                            .format(java.util.Date(summary.recordingStartEpochMs)),
                    supporting = stringResource(R.string.session_list_short_id, summary.sessionId.take(8)),
                )
                // 전송 상태는 이름에 딸린 정보가 아니라 지금 무엇을 할 수 있는지를 말하므로,
                // 아래 버튼과 한 묶음이 되도록 이름표에서 떼어 놓고 옅게 두지 않는다.
                //
                // 아직 올리지 않았다는 것은 업로드 버튼이 이미 말한다. 그 상태에서만 나오는
                // 버튼이므로 같은 말을 한 줄 더 적지 않는다. 나머지 셋은 각자 할 말이 있다.
                if (summary.uploadState != UploadState.LOCAL_ONLY) {
                    Text(
                        text = stringResource(summary.uploadState.labelRes),
                        style = MaterialTheme.typography.bodyLarge,
                    )
                }
                // 무엇이 막았는지 알아야 다시 걸어 볼지 판단할 수 있다. 앱을 다시 켜면 남지 않는다.
                // 전송 실패는 기록하는 컬럼이 없다.
                if (summary.uploadState == UploadState.FAILED && uploadFailureReason != null) {
                    SupportingText(uploadFailureReason)
                }
                if (presentation.uploadAction != null) {
                    Button(onClick = onUpload) {
                        Text(
                            stringResource(
                                if (presentation.uploadAction ==
                                    SessionDetailPresentation.UploadAction.Retry
                                ) {
                                    R.string.upload_retry
                                } else {
                                    R.string.upload_session
                                },
                            ),
                        )
                    }
                }
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    ExportControls(exportState, exportMessage, onExport)
                }
            }
        }
    }
    if (showSessionInfo && summary != null) {
        SessionInfoSheet(
            summary = summary,
            durationSeconds = SessionDetailPresentation.from(summary).durationSeconds,
            onDismiss = { showSessionInfo = false },
        )
    }
}

/**
 * 세션을 특정해 주지 않는 값들을 담는 시트다.
 *
 * Episode 수·길이·해상도·전체 ID는 세션을 고를 때가 아니라 확인하러 들어왔을 때만 필요하다.
 * 사진 앱이 ⓘ 뒤에 두는 것과 같은 성격이라 상세 본문에서 빼고 여기로 옮겼다.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
@Suppress("FunctionName")
private fun SessionInfoSheet(
    summary: com.ssafy.s15p21a206.tiger.episode.SessionSummary,
    durationSeconds: Long,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier.padding(start = 24.dp, end = 24.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = stringResource(R.string.session_info_title),
                style = MaterialTheme.typography.titleMedium,
            )
            SessionInfoRow(stringResource(R.string.session_info_id), summary.sessionId)
            SessionInfoRow(
                label = stringResource(R.string.session_info_captured_at),
                value =
                    java.text.DateFormat
                        .getDateTimeInstance()
                        .format(java.util.Date(summary.recordingStartEpochMs)),
            )
            SessionInfoRow(
                label = stringResource(R.string.session_info_episodes),
                value = stringResource(R.string.session_info_episode_count, summary.completedEpisodeCount),
            )
            SessionInfoRow(
                label = stringResource(R.string.session_info_duration),
                value = stringResource(R.string.session_detail_duration, durationSeconds),
            )
            SessionInfoRow(
                label = stringResource(R.string.session_info_resolution),
                value =
                    when (val resolution = rememberVideoResolution(summary.bundlePath)) {
                        is VideoResolutionState.Available ->
                            stringResource(R.string.session_detail_resolution, resolution.width, resolution.height)
                        VideoResolutionState.Loading -> stringResource(R.string.session_detail_resolution_loading)
                        VideoResolutionState.Unavailable -> stringResource(R.string.session_detail_resolution_unavailable)
                    },
            )
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun SessionInfoRow(
    label: String,
    value: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        MetaText(label)
        Text(text = value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
@Suppress("FunctionName")
private fun SessionVideoPreview(
    bundlePath: String,
    sharedPlayer: SharedVideoPlayer,
    onOpenFullscreenVideo: () -> Unit,
) {
    val videoFile = remember(bundlePath) { File(bundlePath, SessionBundle.MAIN_VIDEO_FILE) }
    val videoDescription = stringResource(R.string.session_detail_video_content_description)
    if (!videoFile.isFile || videoFile.length() == 0L) {
        // 영상은 화면 폭을 다 쓰지만 이 문구는 본문이다. 여백 없이 두면 화면 왼쪽 끝에 붙는다.
        Text(
            text = stringResource(R.string.session_detail_video_unavailable),
            modifier = Modifier.padding(horizontal = DETAIL_CONTENT_PADDING),
        )
        return
    }
    val player = sharedPlayer.playerFor(videoFile)
    VideoPlayer(
        player = player,
        fullscreen = false,
        onFullscreenClick = onOpenFullscreenVideo,
        modifier =
            Modifier
                .fillMaxWidth()
                .aspectRatio(rememberVideoAspectRatio(player))
                .semantics { contentDescription = videoDescription },
    )
}

@Composable
@Suppress("FunctionName")
private fun FullScreenVideoScreen(
    bundlePath: String?,
    sharedPlayer: SharedVideoPlayer,
    onBack: () -> Unit,
) {
    val videoFile = bundlePath?.let { File(it, SessionBundle.MAIN_VIDEO_FILE) }
    val playable = videoFile?.isFile == true && videoFile.length() > 0L
    var landscapeLocked by remember { mutableStateOf(false) }
    // 재생할 영상이 없으면 컨트롤이 뜨지 않으므로, 뒤로 가기가 사라지지 않게 처음부터 보이게 둔다.
    var controlsVisible by remember { mutableStateOf(true) }
    LockLandscapeWhilePlaying(landscapeLocked)
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (playable) {
            VideoPlayer(
                player = sharedPlayer.playerFor(videoFile),
                fullscreen = true,
                onFullscreenClick = onBack,
                modifier = Modifier.fillMaxSize(),
                onControlsVisibilityChanged = { controlsVisible = it },
            )
        } else {
            Text(
                text = stringResource(R.string.session_detail_video_unavailable),
                color = Color.White,
                modifier = Modifier.align(Alignment.Center),
            )
        }
        if (controlsVisible) {
            // 검은 배경은 화면 끝까지 채우되 컨트롤만 시스템 바를 피한다. 가로로 눕히면 컷아웃이
            // 좌우로 오므로 상단 여백만으로는 모자란다.
            IconButton(
                onClick = onBack,
                modifier = Modifier.align(Alignment.TopStart).safeDrawingPadding(),
            ) {
                Icon(
                    painter = painterResource(R.drawable.ic_navigation_back),
                    contentDescription = stringResource(R.string.navigation_back),
                    tint = Color.White,
                )
            }
            if (playable) {
                LandscapeLockButton(
                    landscapeLocked = landscapeLocked,
                    onToggle = { landscapeLocked = !landscapeLocked },
                    modifier = Modifier.align(Alignment.TopEnd).safeDrawingPadding(),
                )
            }
        }
    }
}

/**
 * 가로 고정을 켜고 끄는 플레이어 컨트롤이다. Media3는 회전 버튼을 제공하지 않아 직접 만든다.
 */
@Composable
@Suppress("FunctionName")
private fun LandscapeLockButton(
    landscapeLocked: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier,
) {
    IconButton(
        onClick = onToggle,
        modifier =
            modifier.background(
                color = if (landscapeLocked) Color.White.copy(alpha = 0.24f) else Color.Transparent,
                shape = CircleShape,
            ),
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_screen_rotation),
            contentDescription =
                stringResource(
                    if (landscapeLocked) {
                        R.string.session_video_unlock_landscape
                    } else {
                        R.string.session_video_lock_landscape
                    },
                ),
            tint = Color.White,
        )
    }
}

/**
 * 수집 화면이 보이는 동안 한쪽 가로로 고정하고, 벗어나면 원래 설정으로 되돌린다.
 *
 * Camera 파이프라인이 가로 기준이고 ARCore에 알리는 표시 회전도 고정값이라, 수집 중에 방향이
 * 바뀌면 프리뷰가 돌아간다.
 */
@Composable
@Suppress("FunctionName")
private fun LockLandscapeWhileVisible() {
    val activity = LocalContext.current.findActivity() ?: return
    DisposableEffect(activity) {
        val previous = activity.requestedOrientation
        activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        onDispose { activity.requestedOrientation = previous }
    }
}

/**
 * 전체화면 재생의 방향 정책을 반영한다.
 *
 * 앱은 manifest에서 세로로 묶여 있으므로 기기를 눕혀도 화면이 돌지 않는다. 사용자가 회전 버튼으로
 * 가로 고정을 켤 때만 가로로 묶고, 끄면 진입 시점 설정으로 돌아간다. 화면을 벗어날 때도 같다.
 */
@Composable
@Suppress("FunctionName")
private fun LockLandscapeWhilePlaying(landscapeLocked: Boolean) {
    val activity = LocalContext.current.findActivity() ?: return
    val entryOrientation = remember(activity) { activity.requestedOrientation }
    DisposableEffect(activity, entryOrientation) {
        onDispose { activity.requestedOrientation = entryOrientation }
    }
    LaunchedEffect(activity, landscapeLocked, entryOrientation) {
        activity.requestedOrientation =
            if (landscapeLocked) {
                ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            } else {
                entryOrientation
            }
    }
}

// PlayerView는 Media3의 unstable API다. 앱이 직접 쓰는 유일한 지점이라 여기서만 opt-in한다.
@androidx.annotation.OptIn(UnstableApi::class)
@Composable
@Suppress("FunctionName")
private fun VideoPlayer(
    player: ExoPlayer,
    fullscreen: Boolean,
    onFullscreenClick: () -> Unit,
    modifier: Modifier,
    onControlsVisibilityChanged: (Boolean) -> Unit = {},
) {
    // listener를 factory에서 한 번만 걸기 때문에, 콜백은 최신 값을 따라가게 감싼다.
    val currentFullscreenClick by rememberUpdatedState(onFullscreenClick)
    val currentControlsVisibilityChanged by rememberUpdatedState(onControlsVisibilityChanged)
    AndroidView(
        factory = { viewContext ->
            PlayerView(viewContext).apply {
                // 버튼 상태를 먼저 맞추고 listener를 건다. `setFullscreenButtonState`는 상태만
                // 바꾸지 않고 listener까지 호출하므로, 순서를 바꾸면 전체화면에 들어가자마자
                // 콜백이 불려 곧바로 상세 화면으로 되돌아간다.
                setFullscreenButtonState(fullscreen)
                // 전체화면 버튼과 콜백만 Media3가 주고, 화면 전환은 앱이 한다.
                setFullscreenButtonClickListener { currentFullscreenClick() }
                setControllerVisibilityListener(
                    PlayerView.ControllerVisibilityListener { visibility ->
                        currentControlsVisibilityChanged(visibility == View.VISIBLE)
                    },
                )
            }
        },
        update = { view -> view.player = player },
        onRelease = { view -> view.player = null },
        modifier = modifier,
    )
}

/**
 * 영상의 가로세로 비율을 따라간다. 회전 metadata가 적용된 크기를 쓰므로, `video_rotation_degrees`가
 * 90인 기존 수집분은 세로 비율로 나온다.
 */
@Composable
private fun rememberVideoAspectRatio(player: ExoPlayer): Float {
    var aspectRatio by remember(player) { mutableFloatStateOf(DEFAULT_VIDEO_ASPECT_RATIO) }
    DisposableEffect(player) {
        fun apply(videoSize: VideoSize) {
            if (videoSize.width > 0 && videoSize.height > 0) {
                aspectRatio = videoSize.width * videoSize.pixelWidthHeightRatio / videoSize.height
            }
        }
        apply(player.videoSize)
        val listener =
            object : Player.Listener {
                override fun onVideoSizeChanged(videoSize: VideoSize) = apply(videoSize)
            }
        player.addListener(listener)
        onDispose { player.removeListener(listener) }
    }
    return aspectRatio
}

/** 영상 크기를 아직 모를 때 쓰는 비율. 크기를 알게 되면 즉시 교체된다. */
private const val DEFAULT_VIDEO_ASPECT_RATIO = 16f / 9f

/**
 * 상세 화면과 전체화면이 같은 ExoPlayer를 쓰게 한다.
 *
 * 두 화면은 서로 다른 destination이라 Composable이 새로 만들어지지만, 재생기는 이 객체가 들고
 * 있으므로 화면을 오갈 때도 재생 위치가 유지된다.
 */
private class SharedVideoPlayer(
    private val context: Context,
) {
    private var player: ExoPlayer? = null
    private var preparedPath: String? = null

    /** 같은 파일이면 쓰던 재생기를 그대로 준다. 다른 파일이면 그 파일로 다시 적재한다. */
    fun playerFor(videoFile: File): ExoPlayer {
        val current = player ?: ExoPlayer.Builder(context).build().also { player = it }
        val path = videoFile.absolutePath
        if (preparedPath != path) {
            current.setMediaItem(MediaItem.fromUri(Uri.fromFile(videoFile)))
            current.prepare()
            preparedPath = path
        }
        return current
    }

    fun release() {
        player?.release()
        player = null
        preparedPath = null
    }
}

@Composable
private fun rememberSharedVideoPlayer(): SharedVideoPlayer {
    val context = LocalContext.current.applicationContext
    val sharedPlayer = remember(context) { SharedVideoPlayer(context) }
    DisposableEffect(sharedPlayer) { onDispose(sharedPlayer::release) }
    return sharedPlayer
}

/**
 * 유휴 프리뷰의 회전을 맞춘다.
 *
 * Camera2는 SurfaceTexture에 센서 방향 그대로 프레임을 넣고 TextureView는 회전을 반영하지 않는다.
 * 수집 중 프리뷰는 ARCore가 처리하지만 이 경로는 앱이 직접 걸어야 한다.
 */
private fun applyIdlePreviewTransform(
    view: TextureView,
    viewWidth: Int,
    viewHeight: Int,
    bufferWidth: Int,
    bufferHeight: Int,
) {
    val activity = view.context.findActivity() ?: return
    val manager = view.context.getSystemService(CameraManager::class.java) ?: return
    val rotation =
        runCatching {
            val cameraId =
                manager.cameraIdList.first {
                    manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) ==
                        CameraCharacteristics.LENS_FACING_BACK
                }
            val sensorOrientation =
                manager.getCameraCharacteristics(cameraId).get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0

            @Suppress("DEPRECATION")
            val displayRotation = activity.windowManager.defaultDisplay.rotation
            CameraPreviewTransform.rotationDegrees(sensorOrientation, displayRotation)
        }.getOrNull() ?: return
    view.setTransform(
        CameraPreviewTransform.matrix(viewWidth, viewHeight, bufferWidth, bufferHeight, rotation),
    )
}

private fun Context.findActivity(): Activity? =
    when (this) {
        is Activity -> this
        is ContextWrapper -> baseContext.findActivity()
        else -> null
    }

private fun Context.openArCoreStore() {
    val marketIntent = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.ar.core"))
    val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=com.google.ar.core"))
    startActivity(if (marketIntent.resolveActivity(packageManager) != null) marketIntent else webIntent)
}

@Suppress("FunctionName")
@Composable
internal fun ExportControls(
    state: ExportState,
    failureReason: String?,
    onSelectTree: () -> Unit,
) {
    // 아직 내보내지 않았다는 것은 바로 아래 버튼이 이미 말한다. 그 상태에서만 나오는 버튼이므로
    // 같은 말을 한 줄 더 적지 않는다. 진행·완료는 버튼이 사라지는 자리라 문구가 유일한 신호이고,
    // 실패는 버튼이 옮기지 못하는 이유를 담는다.
    val label =
        when (state) {
            ExportState.NOT_EXPORTED -> null
            ExportState.EXPORTING -> stringResource(R.string.export_exporting)
            ExportState.EXPORTED -> stringResource(R.string.export_exported)
            ExportState.EXPORT_FAILED -> stringResource(R.string.export_failed, failureReason.orEmpty())
        }
    if (label != null) Text(label)
    if (state != ExportState.EXPORTED && state != ExportState.EXPORTING) {
        Button(onClick = onSelectTree) {
            Text(
                stringResource(
                    if (state ==
                        ExportState.EXPORT_FAILED
                    ) {
                        R.string.export_retry
                    } else {
                        R.string.export_select_tree
                    },
                ),
            )
        }
    }
}

@Suppress("FunctionName")
@Composable
internal fun UploadControls(
    state: UploadState,
    onUpload: () -> Unit,
) {
    val label =
        when (state) {
            UploadState.LOCAL_ONLY -> stringResource(R.string.upload_local_only)
            UploadState.UPLOADING -> stringResource(R.string.upload_in_progress)
            UploadState.UPLOADED -> stringResource(R.string.upload_completed)
            UploadState.FAILED -> stringResource(R.string.upload_failed)
        }
    Text(label)
    if (state == UploadState.LOCAL_ONLY || state == UploadState.FAILED) {
        Button(onClick = onUpload) {
            Text(stringResource(if (state == UploadState.FAILED) R.string.upload_retry else R.string.upload_session))
        }
    }
}

// Tracking 판정 주기. 안정화(1초)와 유실(0.5초) 임계값보다 충분히 촘촘해야 마감 시점이 제때 발화한다.
private const val TRACKING_TICK_MS = 100L

/** 프리뷰와 영상의 가로세로 비. 두 녹화 해상도 모두 16:9라 선택과 무관하게 같다. */
private const val PREVIEW_ASPECT_RATIO = 16f / 9f

/** 세션 상세 본문의 여백. 영상은 화면 폭을 다 쓰므로 이 여백은 그 아래 내용에만 적용된다. */
private val DETAIL_CONTENT_PADDING = 16.dp

/** 영상과 본문 사이 간격. 좌우 여백보다 넓어야 영상이 끝나고 설명이 시작되는 것으로 읽힌다. */
private val DETAIL_VIDEO_GAP = 24.dp

/**
 * 세션 정보 버튼의 글리프 크기.
 *
 * 헤더에서 뒤로 가기와 나란히 서지만 같은 급의 동작은 아니다. 기본 24dp보다 작게 두어 있는 줄만
 * 알면 되는 단추로 남긴다. 터치 영역은 `IconButton`의 48dp를 그대로 둔다.
 */
private val SESSION_INFO_ICON_SIZE = 20.dp
