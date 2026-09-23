package com.ssafy.s15p21a206.tiger.ui.capture

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
import androidx.compose.material3.SnackbarHost
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.capture.RecordingResolutionStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.ui.common.LockLandscapeWhileVisible

/**
 * 수집 작업 공간. 조회 흐름 위에 모달로 얹힌다.
 *
 * 목적지가 아닌 이유는 진입 경로가 하나뿐이고, 뒤로 가기가 "이전 화면으로"가 아니라 "종료할까요?"이며,
 * 안에 또 모달을 품기 때문이다. NavHost 바깥에 있어 수집 상태가 백스택 조작과 무관하게 남는다.
 *
 * **여기는 그리기만 한다.** 카메라 세션·ARCore·마감은 [rememberCaptureDriver]가 맡고, 어디로 갈지는
 * [onCompleted]로 부모가 정한다. 이 화면은 목적지도 카메라도 모른다.
 *
 * [state]는 부모가 소유한다. 부모가 [CaptureIntent.Open]으로 작업 공간을 열기 때문이다.
 */
@Suppress("FunctionName")
@Composable
internal fun CaptureWorkspace(
    state: CaptureUiState,
    onIntent: (CaptureIntent) -> Unit,
    repository: SessionRepository,
    resolutionStore: RecordingResolutionStore,
    /** 마감으로 세션이 저장됐다. `startUpload`는 앱이 전면에 있어 전송을 걸어도 되는지다. */
    onCompleted: (sessionId: String, startUpload: Boolean) -> Unit,
) {
    val driver =
        rememberCaptureDriver(
            state = state,
            onIntent = onIntent,
            repository = repository,
            resolutionStore = resolutionStore,
            onCompleted = onCompleted,
        )

    if (!state.open) return
    // 작업 공간을 벗어나면 유휴 프리뷰 Camera2 session을 놓는다. 조회 화면이 카메라를
    // 붙잡고 있을 이유가 없고, 다음 수집은 새 Surface로 다시 연다.
    DisposableEffect(Unit) {
        onDispose(driver.releaseIdlePreview)
    }
    // 수집 화면은 가로로 고정한다. Camera 센서가 90도 눕혀 장착돼 있어 세로 화면에서는
    // 프리뷰가 옆으로 누운 채 비율까지 어긋나 보인다. 저장되는 영상도 가로다.
    LockLandscapeWhileVisible()
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        CapturePreviewSurface(
            bufferSize = state.idlePreviewSize,
            // 수집이 시작되면 ARCore가 직접 그리므로 변환을 걷는다.
            applyTransform = state.phase == CaptureWorkspaceControlState.Idle,
            onSurfaceAvailable = driver.onSurfaceAvailable,
            onSurfaceDestroyed = driver.onSurfaceDestroyed,
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
                    // 촬영 조건은 Session 시작 전에만 만질 수 있다. 시작한 뒤에도 패널은 열리며,
                    // 무엇으로 찍고 있는지 읽을 수 있게 값만 보여 준다.
                    CaptureCameraPanelButton(
                        enabled = !state.manualCamera.panelOpen,
                        onClick = { onIntent(CaptureIntent.ToggleManualCameraPanel(true)) },
                    )
                }
                CaptureWorkspaceExitControls(policy = state.policy, onExit = driver.requestExit)
            }
        }
        if (state.manualCamera.panelOpen && state.chromeVisible) {
            CaptureCameraPanel(
                state = state.manualCamera,
                // Session이 시작되면 값을 잠근다. 촬영 도중 조건이 바뀌면 그 Session의 데이터는
                // 한 조건으로 찍혔다고 말할 수 없게 된다.
                enabled = state.phase == CaptureWorkspaceControlState.Idle,
                onChange = driver.editManualCamera,
                onFixWhiteBalance = driver.fixWhiteBalance,
                onClearWhiteBalance = driver.releaseWhiteBalance,
                onClose = { onIntent(CaptureIntent.ToggleManualCameraPanel(false)) },
                modifier =
                    Modifier
                        .align(Alignment.TopEnd)
                        .safeDrawingPadding()
                        // 닫기 버튼 아래에서 시작한다. 겹쳐 두면 세션을 벗어날 길이 가려진다.
                        .padding(top = 92.dp, end = 20.dp, bottom = 20.dp),
            )
        }
        SnackbarHost(driver.snackbarHostState, Modifier.align(Alignment.TopCenter).padding(top = 80.dp))
        if (!state.showMetadataDialog && state.chromeVisible) {
            CaptureWorkspaceControls(
                state = state.phase,
                ready = state.ready,
                busy = state.busy,
                onPlay = driver.play,
                onPause = driver.pause,
                onStop = driver.requestExit,
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
            onConfirm = driver.confirmMetadata,
            onCancel = { onIntent(CaptureIntent.Close) },
        )
    }
    // 마감 중이거나 마감이 실패한 동안은 작업 공간을 덮는다. 제어가 이미 전부 막혀 있는
    // 구간이라 덮는 편이 상태를 정직하게 말한다.
    if (!state.chromeVisible) {
        CaptureFinalizingOverlay(
            failure = state.finalizeFailure,
            onDismissFailure = { onIntent(CaptureIntent.FinalizeFailureDismissed) },
        )
    }
    if (state.showStopConfirmation) {
        CaptureStopConfirmation(
            onConfirm = driver.confirmStop,
            onDismiss = { onIntent(CaptureIntent.StopDismissed) },
        )
    }
}

/** 프리뷰와 영상의 가로세로 비. 두 녹화 해상도 모두 16:9라 선택과 무관하게 같다. */
private const val PREVIEW_ASPECT_RATIO = 16f / 9f
