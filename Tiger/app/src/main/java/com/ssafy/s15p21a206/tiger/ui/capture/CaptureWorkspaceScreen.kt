package com.ssafy.s15p21a206.tiger.ui.capture

import androidx.activity.compose.BackHandler
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureControlDisabled
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureDestructive
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureOverlayScrim
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureStart

@Composable
@Suppress("FunctionName")
fun CaptureWorkspaceControls(
    state: CaptureWorkspaceControlState,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
    ready: Boolean = true,
    busy: Boolean = false,
) {
    val policy = CaptureControlPolicy(state, ready, busy)
    Row(
        modifier = modifier.navigationBarsPadding().padding(bottom = 36.dp),
        horizontalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        when (state) {
            CaptureWorkspaceControlState.Idle ->
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_play,
                    contentDescriptionRes = R.string.capture_control_start,
                    onClick = onPlay,
                    enabled = policy.canPlay,
                    tint = CaptureStart,
                )
            CaptureWorkspaceControlState.EpisodeActive -> {
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_pause,
                    contentDescriptionRes = R.string.capture_control_pause,
                    onClick = onPause,
                    enabled = policy.canPause,
                )
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_stop,
                    contentDescriptionRes = R.string.capture_control_stop,
                    onClick = onStop,
                    enabled = policy.canStop,
                    tint = CaptureDestructive,
                )
            }
            CaptureWorkspaceControlState.Initializing,
            CaptureWorkspaceControlState.Ready,
            CaptureWorkspaceControlState.Finalizing,
            -> {
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_play,
                    contentDescriptionRes = R.string.capture_control_resume,
                    onClick = onPlay,
                    enabled = policy.canPlay,
                    tint = CaptureStart,
                )
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_stop,
                    contentDescriptionRes = R.string.capture_control_stop,
                    onClick = onStop,
                    enabled = policy.canStop,
                    tint = CaptureDestructive,
                )
            }
        }
    }
}

/**
 * 마감과 그 실패를 알리는 판이다.
 *
 * 마감 중에는 어떤 제어도 받지 않는다([CaptureControlPolicy]가 `canPlay`·`canStop`을 모두 막고
 * 이탈도 무시한다). 그런데 진행 표시를 제어 아이콘과 같은 줄, 같은 크기로 두면 누를 수 있는 것처럼
 * 보인다. 화면을 덮어 아무것도 받지 않는 상태임을 그대로 드러낸다.
 *
 * 진행률은 쓰지 않는다. 오래 걸리는 구간이 둘인데 `MediaRecorder.stop()`은 진행을 알려 주지 않아,
 * 막대를 쓰면 한참 0%에 멈춰 있다가 뛴다. 멈춘 막대는 "잴 수 없다"가 아니라 "멈췄다"로 읽힌다.
 *
 * [failure]가 있으면 실패를 알리고 [onDismissFailure]까지 남는다. 마감에 실패하면 저장된 세션이
 * 없으므로 넘어갈 곳이 없다. 작업 공간에 머물러야 프리뷰가 살아 있는 채로 다시 찍을 수 있다.
 */
@Composable
@Suppress("FunctionName")
fun CaptureFinalizingOverlay(
    failure: String?,
    onDismissFailure: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val finalizing = stringResource(R.string.capture_finalizing)
    Column(
        modifier =
            modifier
                .fillMaxSize()
                .background(CaptureOverlayScrim)
                // 덮은 아래의 제어가 눌리지 않게 입력을 여기서 삼킨다.
                .clickable(enabled = false, onClick = {})
                .safeDrawingPadding()
                .padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
    ) {
        if (failure == null) {
            CircularProgressIndicator(
                modifier = Modifier.size(48.dp).semantics { contentDescription = finalizing },
                color = Color.White,
            )
            Text(text = finalizing, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Medium)
            Text(
                text = stringResource(R.string.capture_finalizing_warning),
                color = CaptureControlDisabled,
                fontSize = 14.sp,
            )
        } else {
            Text(text = failure, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Medium)
            Button(onClick = onDismissFailure) { Text(stringResource(R.string.action_confirm)) }
        }
    }
}

/** 현재 수집 상태를 프리뷰 위에 표시한다. Tracking 안정화 여부를 사용자가 바로 알 수 있어야 한다. */
@Composable
@Suppress("FunctionName")
fun CaptureWorkspaceStatus(
    state: CaptureWorkspaceControlState,
    modifier: Modifier = Modifier,
) {
    val labelRes =
        when (state) {
            CaptureWorkspaceControlState.Idle -> R.string.capture_status_idle
            CaptureWorkspaceControlState.Initializing -> R.string.capture_status_initializing
            CaptureWorkspaceControlState.Ready -> R.string.capture_status_ready
            CaptureWorkspaceControlState.EpisodeActive -> R.string.capture_status_episode_active
            CaptureWorkspaceControlState.Finalizing -> R.string.capture_status_finalizing
        }
    val label = stringResource(labelRes)
    Text(
        text = label,
        color = Color.White,
        fontWeight = FontWeight.Medium,
        fontSize = 13.sp,
        modifier =
            modifier
                .background(CaptureOverlayScrim, CircleShape)
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .semantics { contentDescription = label },
    )
}

@Composable
@Suppress("FunctionName")
private fun CaptureControlIcon(
    @DrawableRes iconRes: Int,
    @StringRes contentDescriptionRes: Int,
    onClick: () -> Unit,
    enabled: Boolean,
    tint: Color = Color.White,
) {
    CaptureTooltip(contentDescriptionRes) {
        IconButton(
            onClick = onClick,
            enabled = enabled,
            modifier = Modifier.size(56.dp).background(CaptureOverlayScrim, CircleShape),
        ) {
            Icon(
                painter = painterResource(iconRes),
                contentDescription = stringResource(contentDescriptionRes),
                tint = if (enabled) tint else CaptureControlDisabled,
                modifier = Modifier.size(28.dp),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
@Suppress("FunctionName")
fun CaptureTooltip(
    @StringRes label: Int,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    TooltipBox(
        positionProvider = TooltipDefaults.rememberTooltipPositionProvider(TooltipAnchorPosition.Above),
        tooltip = { PlainTooltip { Text(stringResource(label)) } },
        state = rememberTooltipState(),
        modifier = modifier,
        content = content,
    )
}

@Composable
@Suppress("FunctionName")
fun CaptureStopConfirmation(
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.capture_stop_title)) },
        text = { Text(stringResource(R.string.capture_stop_message)) },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors =
                    ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                        contentColor = MaterialTheme.colorScheme.onError,
                    ),
            ) { Text(stringResource(R.string.capture_stop_confirm)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) } },
    )
}

@Composable
@Suppress("FunctionName")
fun CaptureWorkspaceExitControls(
    policy: CaptureControlPolicy,
    onExit: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BackHandler { if (policy.exitAction != CaptureExitAction.Ignore) onExit() }
    val description = stringResource(R.string.capture_close_content_description)
    val enabled = policy.exitAction != CaptureExitAction.Ignore
    CaptureTooltip(R.string.capture_close_content_description, modifier) {
        IconButton(
            onClick = onExit,
            enabled = enabled,
            // 배경 없는 글리프는 영상과 레터박스 경계에 걸쳐 떠 보인다. 다른 오버레이와 같은 판에 올린다.
            modifier =
                Modifier
                    .size(48.dp)
                    .background(CaptureOverlayScrim, CircleShape)
                    .semantics { contentDescription = description },
        ) {
            Text(
                text = stringResource(R.string.control_close),
                color = if (enabled) Color.White else CaptureControlDisabled,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

/**
 * 이번 Session이 녹화할 해상도를 프리뷰 위에 표시한다.
 *
 * Session마다 다르게 고를 수 있으므로, 촬영을 시작하기 전에 무엇으로 찍는지 확인할 수 있어야 한다.
 */
@Composable
@Suppress("FunctionName")
fun CaptureWorkspaceResolution(
    resolution: RecordingResolution,
    modifier: Modifier = Modifier,
) {
    val label = stringResource(R.string.capture_resolution_option, resolution.width, resolution.height)
    val description = stringResource(R.string.capture_resolution_content_description, resolution.width, resolution.height)
    Text(
        text = label,
        color = Color.White,
        fontWeight = FontWeight.Medium,
        fontSize = 13.sp,
        modifier =
            modifier
                .background(CaptureOverlayScrim, CircleShape)
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .semantics { contentDescription = description },
    )
}
