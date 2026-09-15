package com.ssafy.s15p21a206.tiger

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.graphics.SurfaceTexture
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.view.Surface
import android.view.TextureView
import android.widget.MediaController
import android.widget.VideoView
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.room.Room
import com.google.ar.core.ArCoreApk
import com.google.ar.core.exceptions.UnavailableArcoreNotInstalledException
import com.ssafy.s15p21a206.tiger.capture.AndroidCaptureRuntime
import com.ssafy.s15p21a206.tiger.capture.CameraPreviewController
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewController
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewPreflight
import com.ssafy.s15p21a206.tiger.capture.CapturePreviewState
import com.ssafy.s15p21a206.tiger.capture.CaptureSessionCoordinator
import com.ssafy.s15p21a206.tiger.capture.MonotonicClock
import com.ssafy.s15p21a206.tiger.capture.PreviewRuntime
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_2_3
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_3_4
import com.ssafy.s15p21a206.tiger.data.local.TigerDatabase
import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.episode.ExportState
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
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
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureStopConfirmation
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControlState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceControls
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceExitControls
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspaceStatus
import com.ssafy.s15p21a206.tiger.ui.session.SessionDetailPresentation
import com.ssafy.s15p21a206.tiger.ui.session.SessionListScreen
import com.ssafy.s15p21a206.tiger.ui.session.TaskSessionListScreen
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import com.ssafy.s15p21a206.tiger.ui.upload.UploadStatusScreen
import com.ssafy.s15p21a206.tiger.ui.upload.cancelUploadOnStop
import com.ssafy.s15p21a206.tiger.upload.SessionUploadRequestFactory
import com.ssafy.s15p21a206.tiger.upload.SessionUploadService
import com.ssafy.s15p21a206.tiger.upload.SessionUploader
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import java.io.File

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { TigerTheme { CaptureScreen() } }
    }
}

private sealed interface AppDestination {
    data object SessionList : AppDestination

    data object CaptureWorkspace : AppDestination

    data class TaskSessions(
        val taskName: String,
    ) : AppDestination

    data class SessionDetail(
        val sessionId: String,
    ) : AppDestination

    data class SessionVideo(
        val sessionId: String,
    ) : AppDestination

    data class UploadStatus(
        val sessionId: String,
    ) : AppDestination
}

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
    var previewReady by remember { mutableStateOf(false) }
    var previewFailed by remember { mutableStateOf(false) }
    val snackbarHostState = remember { SnackbarHostState() }
    val previewFailureMessage = stringResource(R.string.capture_preview_failed)
    val operationFailureMessage = stringResource(R.string.capture_operation_failed)
    var collecting by remember { mutableStateOf(false) }
    var active by remember { mutableStateOf(false) }
    var task by remember { mutableStateOf("") }
    var objectName by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var previewSurface by remember { mutableStateOf<Surface?>(null) }
    // 수집 시작 시 ARCore가 고른 해상도로 버퍼를 다시 맞추려면 SurfaceTexture를 들고 있어야 한다.
    var previewTexture by remember { mutableStateOf<SurfaceTexture?>(null) }
    var previewBufferSize by remember { mutableStateOf(DEFAULT_PREVIEW_SIZE) }
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
    var destination by remember { mutableStateOf<AppDestination>(AppDestination.SessionList) }
    var uploadJob by remember { mutableStateOf<Job?>(null) }
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
            CaptureExitAction.Leave -> {
                showCaptureMetadataDialog = false
                destination = AppDestination.SessionList
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
                            captureRuntime.start(displayNumber) { width, height ->
                                previewBufferSize = width to height
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
    LaunchedEffect(destination) {
        if (destination == AppDestination.CaptureWorkspace) {
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
    LaunchedEffect(message, destination) {
        if (destination == AppDestination.CaptureWorkspace && message.isNotBlank()) {
            val notice = message
            message = ""
            scope.launch { snackbarHostState.showSnackbar(notice) }
        }
    }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
        if (cancelUploadOnStop(destination is AppDestination.UploadStatus)) {
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
        if (destination == AppDestination.CaptureWorkspace && !collecting) restoreIdlePreview()
    }

    fun startUpload(sessionId: String) {
        val service = uploadService
        if (service == null) {
            message = uploadEndpointMissing
            return
        }
        destination = AppDestination.UploadStatus(sessionId)
        uploadJob = scope.launch { service.upload(sessionId) }
    }
    when (val currentDestination = destination) {
        AppDestination.SessionList -> {
            SessionListScreen(
                sessions = completedSummaries,
                onStartCapture = {
                    previewReady = false
                    previewFailed = false
                    showStopConfirmation = false
                    task = ""
                    objectName = ""
                    message = ""
                    showCaptureMetadataDialog = true
                    destination = AppDestination.CaptureWorkspace
                },
                onOpenTask = { taskName -> destination = AppDestination.TaskSessions(taskName) },
            )
            return
        }
        is AppDestination.TaskSessions -> {
            TaskSessionListScreen(
                taskName = currentDestination.taskName,
                sessions = completedSummaries.filter { it.taskName.trim() == currentDestination.taskName },
                onBack = { destination = AppDestination.SessionList },
                onOpenSession = { sessionId -> destination = AppDestination.SessionDetail(sessionId) },
            )
            return
        }
        is AppDestination.SessionDetail -> {
            val summary = completedSummaries.firstOrNull { it.sessionId == currentDestination.sessionId }
            SessionDetailScreen(
                summary = summary,
                onBack = { destination = AppDestination.TaskSessions(summary?.taskName.orEmpty()) },
                onUpload = { startUpload(currentDestination.sessionId) },
                exportState = exportState,
                exportMessage = exportMessage,
                onExport = {
                    pendingSessionId = currentDestination.sessionId
                    treePicker.launch(null)
                },
                onOpenFullscreenVideo = { destination = AppDestination.SessionVideo(currentDestination.sessionId) },
            )
            return
        }
        is AppDestination.SessionVideo -> {
            val summary = completedSummaries.firstOrNull { it.sessionId == currentDestination.sessionId }
            FullScreenVideoScreen(
                bundlePath = summary?.bundlePath,
                onBack = { destination = AppDestination.SessionDetail(currentDestination.sessionId) },
            )
            return
        }
        is AppDestination.UploadStatus -> {
            val state = completedSessions.firstOrNull { it.sessionId == currentDestination.sessionId }?.uploadState
            UploadStatusScreen(
                uploadState = state,
                onBack = {
                    destination = AppDestination.SessionDetail(currentDestination.sessionId)
                },
                onCancelUpload = {
                    uploadJob?.cancel()
                    destination = AppDestination.SessionDetail(currentDestination.sessionId)
                },
            )
            return
        }
        AppDestination.CaptureWorkspace -> Unit
    }

    DisposableEffect(capturePreviewController) {
        onDispose(capturePreviewController::release)
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
                                destination = AppDestination.SessionDetail(bundle.sessionId)
                            }
                        }
                    }
                    is FinalizeResult.Failed -> message = "$captureFinalizeFailed: ${result.reason}"
                }
                activeBundle = null
                collecting = false
                // 다음 Session을 시작할 수 있도록 Coordinator의 Session·Tracking 상태를 닫는다.
                coordinator.release()
                trackingReady = false
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                message = captureFinalizeFailed
            } finally {
                finalizing = false
                // 마감에 성공하면 업로드·상세 화면으로 이동해 TextureView가 사라지므로 되살릴 필요가 없다.
                // 수집 화면에 그대로 남는 실패 경로에서만 유휴 프리뷰를 다시 연다.
                if (destination == AppDestination.CaptureWorkspace) restoreIdlePreview()
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
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
                                surfaceTexture.setDefaultBufferSize(previewBufferSize.first, previewBufferSize.second)
                                previewTexture = surfaceTexture
                                previewSurface = Surface(surfaceTexture)
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
                            ) = Unit

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
            modifier = Modifier.fillMaxSize(),
        )
        CaptureWorkspaceExitControls(
            policy = controlPolicy(),
            onExit = ::requestCaptureExit,
            modifier = Modifier.align(Alignment.TopEnd).padding(top = 20.dp, end = 20.dp),
        )
        CaptureWorkspaceStatus(
            state = controlPolicy().state,
            modifier = Modifier.align(Alignment.TopStart).padding(top = 20.dp, start = 20.dp),
        )
        SnackbarHost(snackbarHostState, Modifier.align(Alignment.TopCenter).padding(top = 80.dp))
        if (!showCaptureMetadataDialog) {
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
        AlertDialog(
            onDismissRequest = {
                showCaptureMetadataDialog = false
                destination = AppDestination.SessionList
            },
            title = { Text(stringResource(R.string.capture_metadata_title)) },
            text = {
                Column {
                    OutlinedTextField(
                        value = task,
                        onValueChange = { task = it },
                        label = { Text(stringResource(R.string.capture_metadata_task)) },
                    )
                    OutlinedTextField(
                        value = objectName,
                        onValueChange = { objectName = it },
                        label = { Text(stringResource(R.string.capture_metadata_object)) },
                    )
                }
            },
            confirmButton = {
                Button(
                    enabled = task.isNotBlank() && objectName.isNotBlank(),
                    onClick = { showCaptureMetadataDialog = false },
                ) { Text(stringResource(R.string.capture_metadata_confirm)) }
            },
            dismissButton = {
                Button(
                    onClick = {
                        showCaptureMetadataDialog = false
                        destination = AppDestination.SessionList
                    },
                ) { Text(stringResource(R.string.action_cancel)) }
            },
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

@Suppress("FunctionName")
@Composable
private fun SessionDetailScreen(
    summary: com.ssafy.s15p21a206.tiger.episode.SessionSummary?,
    onBack: () -> Unit,
    onUpload: () -> Unit,
    exportState: ExportState,
    exportMessage: String?,
    onExport: () -> Unit,
    onOpenFullscreenVideo: () -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        NavigationHeader(
            title = stringResource(R.string.session_detail_title),
            onBack = onBack,
        )
        if (summary == null) {
            Text(stringResource(R.string.session_detail_unavailable))
        } else {
            val presentation = SessionDetailPresentation.from(summary)
            SessionVideoPreview(summary.bundlePath, onOpenFullscreenVideo)
            Text(
                stringResource(
                    R.string.session_list_capture_time,
                    java.text.DateFormat
                        .getDateTimeInstance()
                        .format(java.util.Date(summary.recordingStartEpochMs)),
                ),
            )
            Text(stringResource(R.string.session_list_short_id, summary.sessionId.take(8)))
            Text(stringResource(R.string.session_list_episode_count, summary.completedEpisodeCount))
            Text(stringResource(R.string.session_detail_duration, presentation.durationSeconds))
            Text(
                stringResource(
                    when (summary.uploadState) {
                        UploadState.LOCAL_ONLY -> R.string.upload_local_only
                        UploadState.UPLOADING -> R.string.upload_in_progress
                        UploadState.UPLOADED -> R.string.upload_completed
                        UploadState.FAILED -> R.string.upload_failed
                    },
                ),
            )
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
            ExportControls(exportState, exportMessage, onExport)
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun SessionVideoPreview(
    bundlePath: String,
    onOpenFullscreenVideo: () -> Unit,
) {
    val videoFile = remember(bundlePath) { File(bundlePath, SessionBundle.MAIN_VIDEO_FILE) }
    val videoDescription = stringResource(R.string.session_detail_video_content_description)
    if (!videoFile.isFile || videoFile.length() == 0L) {
        Text(stringResource(R.string.session_detail_video_unavailable))
        return
    }
    Box(
        modifier =
            Modifier
                .fillMaxWidth()
                .aspectRatio(16f / 9f),
    ) {
        VideoPlayer(videoFile, Modifier.fillMaxSize().semantics { contentDescription = videoDescription })
        IconButton(
            onClick = onOpenFullscreenVideo,
            modifier = Modifier.align(Alignment.TopEnd),
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_fullscreen),
                contentDescription = stringResource(R.string.session_detail_open_fullscreen),
            )
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun FullScreenVideoScreen(
    bundlePath: String?,
    onBack: () -> Unit,
) {
    val videoFile = bundlePath?.let { File(it, SessionBundle.MAIN_VIDEO_FILE) }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (videoFile?.isFile == true && videoFile.length() > 0L) {
            VideoPlayer(videoFile, Modifier.fillMaxSize())
        } else {
            Text(
                text = stringResource(R.string.session_detail_video_unavailable),
                color = Color.White,
                modifier = Modifier.align(Alignment.Center),
            )
        }
        IconButton(
            onClick = onBack,
            modifier = Modifier.align(Alignment.TopStart),
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_navigation_back),
                contentDescription = stringResource(R.string.navigation_back),
                tint = Color.White,
            )
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun VideoPlayer(
    videoFile: File,
    modifier: Modifier,
) {
    AndroidView(
        factory = { viewContext ->
            VideoView(viewContext).apply {
                setMediaController(MediaController(viewContext).also { it.setAnchorView(this) })
                setVideoURI(Uri.fromFile(videoFile))
                setOnPreparedListener { seekTo(1) }
            }
        },
        modifier = modifier,
    )
}

@Composable
@Suppress("FunctionName")
private fun NavigationHeader(
    title: String,
    onBack: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(
                painter = painterResource(R.drawable.ic_navigation_back),
                contentDescription = stringResource(R.string.navigation_back),
            )
        }
        Text(title)
    }
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
    val label =
        when (state) {
            ExportState.NOT_EXPORTED -> stringResource(R.string.export_not_exported)
            ExportState.EXPORTING -> stringResource(R.string.export_exporting)
            ExportState.EXPORTED -> stringResource(R.string.export_exported)
            ExportState.EXPORT_FAILED -> stringResource(R.string.export_failed, failureReason.orEmpty())
        }
    Text(label)
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

// 수집 시작 전 프리뷰 버퍼 크기. 저장 영상과 화각을 맞추기 위해 ARCore 카메라 구성과 같은 4:3을 쓴다.
// 수집이 시작되면 ARCore가 실제로 고른 해상도로 교체된다.
private val DEFAULT_PREVIEW_SIZE = 640 to 480
