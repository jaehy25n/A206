package com.ssafy.s15p21a206.tiger.ui.upload

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.UploadState

internal enum class UploadExitAction { ReturnToDetail, ConfirmCancellation }

internal fun uploadExitAction(state: UploadState?): UploadExitAction =
    if (state == UploadState.UPLOADING) UploadExitAction.ConfirmCancellation else UploadExitAction.ReturnToDetail

internal fun cancelUploadOnStop(isUploadStatusDestination: Boolean): Boolean = isUploadStatusDestination

@Composable
@Suppress("FunctionName")
internal fun UploadStatusScreen(
    uploadState: UploadState?,
    onBack: () -> Unit,
    onCancelUpload: () -> Unit,
) {
    var showCancellationConfirmation by mutableStateOf(false)
    val uploadInProgress = stringResource(R.string.upload_in_progress)
    val requestExit = {
        if (uploadExitAction(uploadState) == UploadExitAction.ConfirmCancellation) showCancellationConfirmation = true else onBack()
    }
    BackHandler(onBack = requestExit)
    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = requestExit) {
                Icon(
                    painter = painterResource(R.drawable.ic_navigation_back),
                    contentDescription = stringResource(R.string.navigation_back),
                )
            }
            Text(stringResource(R.string.upload_status_title))
        }
        if (uploadState ==
            UploadState.UPLOADING
        ) {
            CircularProgressIndicator(
                modifier = Modifier.semantics { contentDescription = uploadInProgress },
            )
        }
        Text(
            stringResource(
                when (uploadState) {
                    UploadState.UPLOADING -> R.string.upload_in_progress
                    UploadState.UPLOADED -> R.string.upload_completed
                    UploadState.FAILED -> R.string.upload_failed
                    UploadState.LOCAL_ONLY, null -> R.string.upload_local_only
                },
            ),
        )
        if (uploadState == UploadState.UPLOADING) Text(stringResource(R.string.upload_leave_warning))
    }
    if (showCancellationConfirmation) {
        AlertDialog(
            onDismissRequest = { showCancellationConfirmation = false },
            title = { Text(stringResource(R.string.upload_cancel_title)) },
            text = { Text(stringResource(R.string.upload_cancel_message)) },
            confirmButton = { TextButton(onClick = onCancelUpload) { Text(stringResource(R.string.upload_cancel_confirm)) } },
            dismissButton = {
                TextButton(
                    onClick = { showCancellationConfirmation = false },
                ) { Text(stringResource(R.string.action_cancel)) }
            },
        )
    }
}
