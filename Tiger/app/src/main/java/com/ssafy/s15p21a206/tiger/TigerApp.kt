package com.ssafy.s15p21a206.tiger

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.ssafy.s15p21a206.tiger.capture.RecordingResolutionStore
import com.ssafy.s15p21a206.tiger.episode.ExportState
import com.ssafy.s15p21a206.tiger.episode.SafDocumentTreeGateway
import com.ssafy.s15p21a206.tiger.episode.SessionBundleExporter
import com.ssafy.s15p21a206.tiger.episode.SessionDeleteResult
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureIntent
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureUiState
import com.ssafy.s15p21a206.tiger.ui.capture.CaptureWorkspace
import com.ssafy.s15p21a206.tiger.ui.capture.reduce
import com.ssafy.s15p21a206.tiger.ui.session.SessionDetailScreen
import com.ssafy.s15p21a206.tiger.ui.session.SessionListScreen
import com.ssafy.s15p21a206.tiger.ui.session.TaskSessionListScreen
import com.ssafy.s15p21a206.tiger.ui.upload.cancelUploadOnStop
import com.ssafy.s15p21a206.tiger.ui.video.FullScreenVideoScreen
import com.ssafy.s15p21a206.tiger.ui.video.rememberSharedVideoPlayer
import com.ssafy.s15p21a206.tiger.upload.SessionUploadService
import com.ssafy.s15p21a206.tiger.upload.UploadResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable

// 조회 흐름의 목적지다. 인자는 Navigation Compose의 type-safe route로 전달한다. Task 이름은
// 사용자가 자유롭게 입력하는 문자열이라 `/`나 공백이 들어올 수 있는데, route 문자열을 직접
// 조립하면 그 값이 경로를 깨뜨린다.
//
// 수집 작업 공간은 목적지가 아니다. 진입 경로가 하나뿐이고, 뒤로 가기가 "이전 화면으로"가 아니라
// "종료할까요?"이며, 안에 또 모달을 품는다. 백스택 pop이 아닌 해제 가드이므로 상태의 boolean으로
// 두고 NavHost 위에 모달로 얹는다.
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

/**
 * 앱의 뿌리. 조회 흐름의 NavHost와 그 위에 얹히는 수집 작업 공간을 담는다.
 *
 * 여기가 목적지와 세션 운용(내보내기·전송·삭제)을 쥐고, 수집은 [CaptureWorkspace]가 가져간다.
 * 수집 상태는 이 화면이 소유하는데, 작업 공간을 여는 것이 조회 화면의 동작이기 때문이다.
 */
@Suppress("FunctionName", "LongMethod")
@Composable
fun TigerApp() {
    val context = LocalContext.current
    // 프로세스 수명을 갖는 것들은 TigerApplication이 소유한다. remember로 만들면 Activity가
    // 재생성될 때마다 인스턴스가 하나씩 더 생긴다.
    val application = context.tigerApplication
    val repository = application.repository
    val uploadService = application.uploadService
    val completedSummaries by repository.observeCompletedSummaries().collectAsState(emptyList())
    val scope = rememberCoroutineScope()
    val gateway = remember { SafDocumentTreeGateway(context.applicationContext) }
    val exporter = remember { SessionBundleExporter(gateway) }
    val resolutionStore = remember { RecordingResolutionStore(context.applicationContext) }
    var exportState by remember { mutableStateOf(ExportState.NOT_EXPORTED) }
    var exportMessage by remember { mutableStateOf<String?>(null) }
    var pendingSessionId by remember { mutableStateOf<String?>(null) }
    var uploadJob by remember { mutableStateOf<Job?>(null) }
    var uploadFailureReason by remember { mutableStateOf<String?>(null) }
    var deleteFailureReason by remember { mutableStateOf<String?>(null) }
    val navController = rememberNavController()
    val currentEntry by navController.currentBackStackEntryAsState()

    /**
     * 수집 작업 공간의 상태. 소유는 여기가 하고 [CaptureWorkspace]가 받아 쓴다.
     *
     * 프로세스가 재생성되면 복원하지 않는다. `ON_STOP`에서 진행 중인 Session을 `INTERRUPTED`로
     * 마감하므로, 되살려도 수집 상태가 없는 빈 작업 공간이 된다. 조회 흐름의 백스택은 NavHost가
     * 저장 상태로 복원한다. 화면 회전은 manifest의 `configChanges`가 받으므로 이 상태도 유지된다.
     */
    var capture by remember {
        val stored = resolutionStore.load()
        mutableStateOf(CaptureUiState(resolution = stored, idlePreviewSize = stored))
    }

    fun onCapture(intent: CaptureIntent) {
        capture = capture.reduce(intent)
    }
    val pickerCancelled = stringResource(R.string.export_picker_cancelled)
    val exportGrantFailed = stringResource(R.string.export_grant_failed)
    val exportFailedUnexpected = stringResource(R.string.export_failed_unexpected)
    val uploadEndpointMissing = stringResource(R.string.upload_endpoint_missing)
    val deleteUploadInProgressMessage = stringResource(R.string.session_delete_upload_in_progress)
    val deleteFailedMessage = stringResource(R.string.session_delete_failed)
    LaunchedEffect(repository) {
        repository.recoverInterruptedStaging()
        repository.failInterruptedUploads()
        repository.normalizeDisplayNumbers()
        // 구제가 끝난 뒤에 회수한다. 구제가 staging에서 옮겨 온 번들은 색인에 행이 있으므로
        // 고아가 아니지만, 순서를 뒤집으면 옮겨지기 전 상태를 보고 판단하게 된다.
        repository.purgeOrphanBundles()
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
                            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
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
                            exportMessage = result.reason
                        }
                    }
                }
            }
        }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
        // 백그라운드 업로드는 하지 않는다. 판정 기준이 "업로드 화면에 있는가"였으나 그 화면을 없애
        // 전송이 진행 중인지로 바꾼다. 어느 화면에 있든 전송 중이면 끊고 FAILED로 남긴다.
        if (cancelUploadOnStop(uploadInFlight = uploadJob?.isActive == true)) {
            uploadJob?.cancel()
        }
    }

    /**
     * 수집 정보 입력부터 시작한다.
     *
     * [initialTask]는 이미 알고 있는 Task 이름이다. Task의 세션 목록에서 시작하면 그 이름이
     * 채워진 채로 열려 같은 이름을 다시 입력하지 않는다. 채워진 뒤에도 고칠 수 있게 두므로,
     * 잘못 들어왔더라도 나갔다 올 필요는 없다.
     *
     * `Open`이 상태를 새로 만든다. 새 TextureView가 이 크기로 버퍼를 잡으므로 직전 Session이
     * 남긴 크기를 물려받지 않는다.
     */
    fun startCapture(initialTask: String) {
        onCapture(CaptureIntent.Open(initialTask, resolutionStore.load()))
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
            // 갈 곳이 없으므로 작업 공간을 닫지 않는다. 그 자리에서 이유를 보여 준다.
            onCapture(CaptureIntent.Notify(uploadEndpointMissing))
            return
        }
        // 상세로 넘어가므로 작업 공간을 닫는다. 남겨 두면 NavHost를 계속 덮는다.
        onCapture(CaptureIntent.Close)
        if (currentEntry?.destination?.hasRoute<SessionDetailRoute>() != true) {
            navController.navigate(SessionDetailRoute(sessionId))
        }
        launchUpload(service, sessionId)
    }

    /**
     * Session을 기기에서 지우고 목록으로 돌아간다.
     *
     * 지운 세션의 상세에 남아 있을 이유가 없다. 색인에서 사라지므로 화면은 "찾을 수 없음"이 된다.
     * 업로드가 진행 중이라 거절당하면 상세에 머무르고 이유만 본문에 남긴다.
     */
    fun deleteSession(sessionId: String) {
        scope.launch {
            val result =
                runCatching { withContext(Dispatchers.IO) { repository.delete(sessionId) } }
                    .getOrElse {
                        deleteFailureReason = deleteFailedMessage
                        return@launch
                    }
            when (result) {
                // 디렉터리가 남았더라도 목록과 색인에서는 사라졌다. 남은 것은 다음 실행이 회수한다.
                SessionDeleteResult.DELETED, SessionDeleteResult.BUNDLE_RETAINED -> {
                    deleteFailureReason = null
                    // 상세에서 지웠으면 그 화면은 이제 "찾을 수 없음"이 되므로 나간다. 목록에서
                    // 지웠으면 목록에 머무른다. 카드는 Flow가 갱신하면서 스스로 사라진다.
                    if (currentEntry?.destination?.hasRoute<SessionDetailRoute>() == true) {
                        navController.popBackStack()
                    }
                }
                SessionDeleteResult.UPLOAD_IN_PROGRESS -> deleteFailureReason = deleteUploadInProgressMessage
            }
        }
    }
    val sharedVideoPlayer = rememberSharedVideoPlayer()
    // 재생 화면을 벗어나면 decoder를 계속 물고 있지 않도록 재생기를 놓는다.
    LaunchedEffect(currentEntry) {
        val onPlaybackRoute =
            currentEntry?.destination?.let { it.hasRoute<SessionDetailRoute>() || it.hasRoute<SessionVideoRoute>() } == true
        if (!onPlaybackRoute) sharedVideoPlayer.release()
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
                        onDeleteSession = ::deleteSession,
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
                        onDelete = { deleteSession(route.sessionId) },
                        deleteFailureReason = deleteFailureReason,
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
        CaptureWorkspace(
            state = capture,
            onIntent = ::onCapture,
            repository = repository,
            resolutionStore = resolutionStore,
            // 마감된 세션이 어디로 가는지는 여기가 정한다. 작업 공간은 목적지를 모른다.
            onCompleted = { sessionId, uploadable ->
                if (uploadable) {
                    startUpload(sessionId)
                } else {
                    onCapture(CaptureIntent.Close)
                    navController.navigate(SessionDetailRoute(sessionId))
                }
            },
        )
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
