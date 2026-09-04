package com.ssafy.s15p21a206.tiger

import android.os.Bundle
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalContext
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.Manifest
import androidx.room.Room
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import kotlinx.coroutines.launch
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_2_3
import com.ssafy.s15p21a206.tiger.data.local.TigerDatabase
import com.ssafy.s15p21a206.tiger.episode.ExportState
import com.ssafy.s15p21a206.tiger.episode.SafDocumentTreeGateway
import com.ssafy.s15p21a206.tiger.episode.SessionBundleExporter
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.episode.SessionFinalizer
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import com.ssafy.s15p21a206.tiger.capture.AndroidCaptureRuntime
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import java.util.UUID

class MainActivity : ComponentActivity() { override fun onCreate(state: Bundle?) { super.onCreate(state); setContent { TigerTheme { CaptureScreen() } } } }

@Composable fun CaptureScreen() {
    val context = LocalContext.current
    val database = remember { Room.databaseBuilder(context.applicationContext, TigerDatabase::class.java, "tiger.db").addMigrations(MIGRATION_2_3).build() }
    val repository = remember { SessionRepository(database.captureSessionDao(), database.episodeMarkerDao(), SessionBundleStore(context.applicationContext)) }
    val completedSessions by repository.observeCompleted().collectAsState(emptyList())
    val scope = rememberCoroutineScope()
    val gateway = remember { SafDocumentTreeGateway(context.applicationContext) }
    val exporter = remember { SessionBundleExporter(gateway) }
    val captureRuntime = remember { AndroidCaptureRuntime(context.applicationContext, SessionBundleStore(context.applicationContext)) }
    var collecting by remember { mutableStateOf(false) }; var active by remember { mutableStateOf(false) }
    var task by remember { mutableStateOf("") }; var objectName by remember { mutableStateOf("") }; var message by remember { mutableStateOf("") }
    var exportState by remember { mutableStateOf(ExportState.NOT_EXPORTED) }
    var exportMessage by remember { mutableStateOf<String?>(null) }
    var pendingSessionId by remember { mutableStateOf<String?>(null) }
    var activeBundle by remember { mutableStateOf<com.ssafy.s15p21a206.tiger.episode.SessionBundle?>(null) }
    var recordingStartNs by remember { mutableLongStateOf(0L) }
    var activeEpisode by remember { mutableStateOf<EpisodeMarker?>(null) }
    var nextDisplayNumber by remember { mutableIntStateOf(1) }
    val pickerCancelled = stringResource(R.string.export_picker_cancelled)
    val treePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri == null) {
            exportState = ExportState.EXPORT_FAILED
            exportMessage = pickerCancelled
        } else {
            val sessionId = pendingSessionId ?: return@rememberLauncherForActivityResult
            runCatching { gateway.persistGrant(uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION) }
            scope.launch {
                exportState = ExportState.EXPORTING
                when (val result = exporter.exportCompleted(repository, sessionId, uri.toString())) {
                    is SessionBundleExporter.ExportAttemptResult.Exported -> { exportState = ExportState.EXPORTED; exportMessage = null }
                    is SessionBundleExporter.ExportAttemptResult.Failed -> { exportState = ExportState.EXPORT_FAILED; exportMessage = result.reason }
                }
            }
        }
    }
    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            runCatching { captureRuntime.start(nextDisplayNumber) }.onSuccess { bundle ->
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
                            bundlePath = bundle.directory.absolutePath
                        )
                    )
                }
                nextDisplayNumber++
            }
                .onFailure { message = it.message.orEmpty() }
        } else message = context.getString(R.string.recording_camera_unavailable)
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
                    interruptedBundle.directory.absolutePath
                )
            )
        }
        activeBundle = null
        activeEpisode = null
        active = false
        collecting = false
    }
    Column(Modifier.fillMaxSize()) {
        Text("ARCore · Camera · IMU: ${if (collecting) "READY" else "IDLE"}")
        OutlinedTextField(task, { task = it }, label = { Text("Task") }); OutlinedTextField(objectName, { objectName = it }, label = { Text("Object") })
        Button(onClick = {
            if (!collecting) cameraPermission.launch(Manifest.permission.CAMERA)
            else if (active) message = context.getString(R.string.active_episode_end_required)
            else scope.launch {
                when (val result = runCatching { captureRuntime.stop() }.getOrElse { FinalizeResult.Failed(it.message.orEmpty()) }) {
                    is FinalizeResult.Completed -> activeBundle?.let { bundle ->
                        repository.save(CaptureSession(bundle.sessionId, bundle.displayNumber, RecordingState.COMPLETED, UploadState.LOCAL_ONLY, recordingStartNs, SystemClock.elapsedRealtimeNanos(), result.directory.absolutePath))
                    }
                    is FinalizeResult.Failed -> message = context.getString(R.string.capture_finalize_failed, result.reason)
                }
                activeBundle = null; collecting = false
            }
        }) { Text(if (collecting) "DATA COLLECTION END" else "DATA COLLECTION START") }
        Button(enabled = collecting && !active && task.isNotBlank() && objectName.isNotBlank(), onClick = {
            activeEpisode = activeBundle?.let { bundle -> EpisodeMarker(UUID.randomUUID().toString(), bundle.sessionId, SystemClock.elapsedRealtimeNanos(), task = task, objectName = objectName, outcome = EpisodeState.ACTIVE) }
            active = activeEpisode != null
        }) { Text("EPISODE START") }
        Button(enabled = active, onClick = {
            activeEpisode?.copy(endTimestampNs = SystemClock.elapsedRealtimeNanos(), outcome = EpisodeState.COMPLETED)?.let { marker ->
                scope.launch { repository.save(marker); captureRuntime.appendEpisode(marker) }
            }
            activeEpisode = null; active = false
        }) { Text("EPISODE END") }
        Button(enabled = active, onClick = {
            activeEpisode?.copy(endTimestampNs = SystemClock.elapsedRealtimeNanos(), outcome = EpisodeState.CANCELLED)?.let { marker ->
                scope.launch { repository.save(marker); captureRuntime.appendEpisode(marker) }
            }
            activeEpisode = null; active = false
        }) { Text("EPISODE CANCEL") }; Text(message)
        completedSessions.forEach { session ->
            ExportControls(exportState, exportMessage, onSelectTree = { pendingSessionId = session.sessionId; treePicker.launch(null) })
        }
    }
}

@Composable
internal fun ExportControls(state: ExportState, failureReason: String?, onSelectTree: () -> Unit) {
    val label = when (state) {
        ExportState.NOT_EXPORTED -> stringResource(R.string.export_not_exported)
        ExportState.EXPORTING -> stringResource(R.string.export_exporting)
        ExportState.EXPORTED -> stringResource(R.string.export_exported)
        ExportState.EXPORT_FAILED -> stringResource(R.string.export_failed, failureReason.orEmpty())
    }
    Text(label)
    if (state != ExportState.EXPORTED && state != ExportState.EXPORTING) {
        Button(onClick = onSelectTree) { Text(stringResource(if (state == ExportState.EXPORT_FAILED) R.string.export_retry else R.string.export_select_tree)) }
    }
}
