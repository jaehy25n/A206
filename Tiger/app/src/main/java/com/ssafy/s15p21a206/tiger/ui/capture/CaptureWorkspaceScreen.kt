package com.ssafy.s15p21a206.tiger.ui.capture

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R

enum class CaptureWorkspaceControlState {
    Ready,
    EpisodeActive,
    SessionActive,
}

@Composable
@Suppress("FunctionName")
fun CaptureWorkspaceControls(
    state: CaptureWorkspaceControlState,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
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
                )
            CaptureWorkspaceControlState.EpisodeActive -> {
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_pause,
                    contentDescriptionRes = R.string.capture_control_pause,
                    onClick = onPause,
                )
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_stop,
                    contentDescriptionRes = R.string.capture_control_stop,
                    onClick = onStop,
                )
            }
            CaptureWorkspaceControlState.SessionActive -> {
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_play,
                    contentDescriptionRes = R.string.capture_control_resume,
                    onClick = onPlay,
                )
                CaptureControlIcon(
                    iconRes = R.drawable.ic_capture_stop,
                    contentDescriptionRes = R.string.capture_control_stop,
                    onClick = onStop,
                )
            }
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun CaptureControlIcon(
    @DrawableRes iconRes: Int,
    @StringRes contentDescriptionRes: Int,
    onClick: () -> Unit,
) {
    IconButton(
        onClick = onClick,
        modifier = Modifier.size(56.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape),
    ) {
        Icon(
            painter = painterResource(iconRes),
            contentDescription = stringResource(contentDescriptionRes),
            tint = Color.White,
            modifier = Modifier.size(28.dp),
        )
    }
}
