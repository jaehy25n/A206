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
            CaptureWorkspaceControlState.Ready ->
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
            CaptureWorkspaceControlState.SessionActive, CaptureWorkspaceControlState.Finalizing -> {
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
