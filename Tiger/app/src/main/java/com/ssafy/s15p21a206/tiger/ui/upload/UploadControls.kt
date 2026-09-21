package com.ssafy.s15p21a206.tiger.ui.upload

import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.UploadState

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
