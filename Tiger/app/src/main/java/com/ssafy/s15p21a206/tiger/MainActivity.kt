package com.ssafy.s15p21a206.tiger

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.room.Room
import com.google.ar.core.ArCoreApk
import com.google.ar.core.exceptions.UnavailableArcoreNotInstalledException
import com.ssafy.s15p21a206.tiger.capture.AndroidCaptureRuntime
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
import com.ssafy.s15p21a206.tiger.episode.SessionBundleExporter
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import com.ssafy.s15p21a206.tiger.upload.SessionUploadRequestFactory
import com.ssafy.s15p21a206.tiger.upload.SessionUploadService
import com.ssafy.s15p21a206.tiger.upload.SessionUploader
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContent { TigerTheme { CaptureScreen() } }
    }
}

@Suppress("FunctionName")
@Composable
fun CaptureScreen() {
    val context = LocalContext.current
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
    val scope = rememberCoroutineScope()
    val gateway = remember { SafDocumentTreeGateway(context.applicationContext) }
    val exporter = remember { SessionBundleExporter(gateway) }
    val captureRuntime = remember { AndroidCaptureRuntime(context.applicationContext, SessionBundleStore(context.applicationContext)) }
    var collecting by remember { mutableStateOf(false) }
    var active by remember { mutableStateOf(false) }
    var task by remember { mutableStateOf("") }
    var objectName by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var exportState by remember { mutableStateOf(ExportState.NOT_EXPORTED) }
    var exportMessage by remember { mutableStateOf<String?>(null) }
    var pendingSessionId by remember { mutableStateOf<String?>(null) }
    var activeBundle by remember { mutableStateOf<com.ssafy.s15p21a206.tiger.episode.SessionBundle?>(null) }
    var recordingStartNs by remember { mutableLongStateOf(0L) }
    var activeEpisode by remember { mutableStateOf<EpisodeMarker?>(null) }
    var nextDisplayNumber by remember { mutableIntStateOf(1) }
    var arCoreInstallRequested by remember { mutableStateOf(false) }
    val pickerCancelled = stringResource(R.string.export_picker_cancelled)
    val exportGrantFailed = stringResource(R.string.export_grant_failed)
    val exportFailedUnexpected = stringResource(R.string.export_failed_unexpected)
    val recordingCameraUnavailable = stringResource(R.string.recording_camera_unavailable)
    val activeEpisodeEndRequired = stringResource(R.string.active_episode_end_required)
    val captureFinalizeFailed = stringResource(R.string.capture_finalize_failed)
    val arCoreUnavailable = stringResource(R.string.arcore_unavailable)
    val arCoreInstallMessage = stringResource(R.string.arcore_install_requested)
    val arCoreSessionStartFailed = stringResource(R.string.arcore_session_start_failed)
    val uploadEndpointMissing = stringResource(R.string.upload_endpoint_missing)
    LaunchedEffect(repository) {
        repository.recoverInterruptedStaging()
        repository.failInterruptedUploads()
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
                        return@rememberLauncherForActivityResult
                    }
                if (installStatus == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                    arCoreInstallRequested = true
                    message = arCoreInstallMessage
                    return@rememberLauncherForActivityResult
                }
                runCatching { captureRuntime.start(nextDisplayNumber) }
                    .onSuccess { bundle ->
                        activeBundle = bundle
                        recordingStartNs = SystemClock.elapsedRealtimeNanos()
                        collecting = true
                        scope.launch {
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
                        }
                        nextDisplayNumber++
                    }.onFailure { error ->
                        message = "$arCoreSessionStartFailed: ${error.message.orEmpty()}"
                        if (error is UnavailableArcoreNotInstalledException) {
                            context.openArCoreStore()
                        }
                    }
            } else {
                message = recordingCameraUnavailable
            }
        }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
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
    }
    Column(Modifier.fillMaxSize()) {
        Text("ARCore · Camera · IMU: ${if (collecting) "READY" else "IDLE"}")
        OutlinedTextField(task, { task = it }, label = { Text("Task") })
        OutlinedTextField(objectName, { objectName = it }, label = { Text("Object") })
        Button(onClick = {
            if (!collecting) {
                cameraPermission.launch(Manifest.permission.CAMERA)
            } else if (active) {
                message = activeEpisodeEndRequired
            } else {
                scope.launch {
                    when (val result = runCatching { captureRuntime.stop() }.getOrElse { FinalizeResult.Failed(it.message.orEmpty()) }) {
                        is FinalizeResult.Completed ->
                            activeBundle?.let { bundle ->
                                repository.save(
                                    CaptureSession(
                                        bundle.sessionId,
                                        bundle.displayNumber,
                                        RecordingState.COMPLETED,
                                        UploadState.LOCAL_ONLY,
                                        recordingStartNs,
                                        SystemClock.elapsedRealtimeNanos(),
                                        result.directory.absolutePath,
                                        System.currentTimeMillis(),
                                    ),
                                )
                            }
                        is FinalizeResult.Failed -> message = "$captureFinalizeFailed: ${result.reason}"
                    }
                    activeBundle = null
                    collecting = false
                }
            }
        }) { Text(if (collecting) "DATA COLLECTION END" else "DATA COLLECTION START") }
        Button(enabled = collecting && !active && task.isNotBlank() && objectName.isNotBlank(), onClick = {
            activeEpisode =
                activeBundle?.let { bundle ->
                    EpisodeMarker(
                        UUID.randomUUID().toString(),
                        bundle.sessionId,
                        SystemClock.elapsedRealtimeNanos(),
                        task = task,
                        objectName = objectName,
                        outcome = EpisodeState.ACTIVE,
                    )
                }
            active = activeEpisode != null
        }) { Text("EPISODE START") }
        Button(enabled = active, onClick = {
            activeEpisode?.copy(endTimestampNs = SystemClock.elapsedRealtimeNanos(), outcome = EpisodeState.COMPLETED)?.let { marker ->
                scope.launch {
                    repository.save(marker)
                    captureRuntime.appendEpisode(marker)
                }
            }
            activeEpisode = null
            active = false
        }) { Text("EPISODE END") }
        Text(message)
        completedSessions.forEach { session ->
            UploadControls(session.uploadState, onUpload = {
                val service = uploadService
                if (service == null) {
                    message = uploadEndpointMissing
                } else {
                    scope.launch { service.upload(session.sessionId) }
                }
            })
            ExportControls(exportState, exportMessage, onSelectTree = {
                pendingSessionId = session.sessionId
                treePicker.launch(null)
            })
        }
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
