package com.ssafy.s15p21a206.tiger.ui.upload

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeader
import com.ssafy.s15p21a206.tiger.ui.common.SupportingText

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
    var showCancellationConfirmation by remember { mutableStateOf(false) }
    val uploadInProgress = stringResource(R.string.upload_in_progress)
    val requestExit = {
        if (uploadExitAction(uploadState) == UploadExitAction.ConfirmCancellation) showCancellationConfirmation = true else onBack()
    }
    BackHandler(onBack = requestExit)
    Column(Modifier.fillMaxSize()) {
        NavigationHeader(title = stringResource(R.string.upload_status_title), onBack = requestExit)
        // 이 화면에는 상태 한 줄과 진행 표시뿐이다. 헤더 아래 남는 공간의 한가운데에 놓아야
        // 시선이 갈 곳이 하나로 정해진다. 위쪽에 붙여 두면 아래가 통째로 비어 보인다.
        Column(
            modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        ) {
            if (uploadState == UploadState.UPLOADING) {
                CircularProgressIndicator(
                    modifier = Modifier.semantics { contentDescription = uploadInProgress },
                )
            }
            // 목록 카드의 "업로드 완료"는 상태를 가리키는 딱지지만, 이 화면은 그 상태만 보여 주는
            // 자리다. 딱지를 그대로 옮기면 무엇을 말하려는 화면인지 읽히지 않아 문장으로 쓴다.
            Text(
                text =
                    stringResource(
                        when (uploadState) {
                            UploadState.UPLOADING -> R.string.upload_status_uploading
                            UploadState.UPLOADED -> R.string.upload_status_completed
                            UploadState.FAILED -> R.string.upload_status_failed
                            UploadState.LOCAL_ONLY, null -> R.string.upload_status_local_only
                        },
                    ),
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
            )
            if (uploadState == UploadState.UPLOADING) {
                SupportingText(
                    text = stringResource(R.string.upload_leave_warning),
                    textAlign = TextAlign.Center,
                )
            }
        }
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
