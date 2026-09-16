package com.ssafy.s15p21a206.tiger.ui.capture

import androidx.activity.compose.BackHandler
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
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
        horizontalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        when (state) {
            CaptureWorkspaceControlState.Idle ->
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_play,
                    contentDescriptionRes = R.string.capture_control_start,
                    onClick = onPlay,
                    enabled = policy.canPlay,
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
                )
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_stop,
                    contentDescriptionRes = R.string.capture_control_stop,
                    onClick = onStop,
                    enabled = policy.canStop,
                )
            }
        }
        if (state == CaptureWorkspaceControlState.Finalizing) {
            val description = stringResource(R.string.capture_finalizing)
            CircularProgressIndicator(modifier = Modifier.size(48.dp).semantics { contentDescription = description }, color = Color.White)
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
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        modifier =
            modifier
                .background(Color.Black.copy(alpha = 0.45f), CircleShape)
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
) {
    CaptureTooltip(contentDescriptionRes) {
        IconButton(
            onClick = onClick,
            enabled = enabled,
            modifier = Modifier.size(56.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape),
        ) {
            Icon(
                painter = painterResource(iconRes),
                contentDescription = stringResource(contentDescriptionRes),
                tint = Color.White.copy(alpha = if (enabled) 1f else 0.38f),
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
        confirmButton = { Button(onClick = onConfirm) { Text(stringResource(R.string.capture_stop_confirm)) } },
        dismissButton = { Button(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) } },
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
            modifier = Modifier.size(48.dp).semantics { contentDescription = description },
        ) {
            Text(
                text = stringResource(R.string.control_close),
                color = Color.White.copy(alpha = if (enabled) 1f else 0.38f),
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
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        modifier =
            modifier
                .background(Color.Black.copy(alpha = 0.45f), CircleShape)
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .semantics { contentDescription = description },
    )
}
