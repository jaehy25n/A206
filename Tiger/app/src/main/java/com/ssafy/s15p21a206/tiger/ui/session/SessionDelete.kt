package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.UploadState

/**
 * 삭제를 확인받는 방식.
 *
 * 되돌릴 수 없는 동작이지만 잃는 것이 상태마다 다르다. 서버에 업로드된 데이터가 있으면 지우는 것은
 * 기기의 저장 공간뿐이고, 아직 올리지 않았으면 수집한 데이터 자체가 사라진다. 두 경우에 같은
 * 문구를 보이면 뒤쪽에서 사용자가 무엇을 잃는지 알 수 없다.
 *
 * 상세와 목록이 같은 판단을 해야 하므로 여기 한 곳에서만 정한다.
 */
internal enum class SessionDeleteAction {
    /** 서버에 사본이 있다. 기기에서만 사라진다. */
    DeleteLocalCopy,

    /** 기기의 것이 유일하다. 지우면 복구할 수 없다. */
    DeleteOnlyCopy,

    ;

    companion object {
        /** 업로드가 번들을 읽고 있는 동안은 지울 수 없으므로 `null`을 낸다. */
        fun from(uploadState: UploadState): SessionDeleteAction? =
            when (uploadState) {
                UploadState.UPLOADED -> DeleteLocalCopy
                UploadState.LOCAL_ONLY, UploadState.FAILED -> DeleteOnlyCopy
                UploadState.UPLOADING -> null
            }
    }
}

/**
 * 삭제를 확인받는 판이다.
 *
 * 되돌릴 수 없으므로 한 번 묻는다. 서버에 DELETE API가 없어 이미 업로드된 데이터는 어느 쪽이든
 * 서버에 남는다. 두 경우를 같은 문구로 덮으면 아직 올리지 않은 세션을 삭제할 때 사용자가 무엇을
 * 잃는지 모른 채 확인을 누른다.
 */
@Composable
@Suppress("FunctionName")
internal fun SessionDeleteConfirmation(
    action: SessionDeleteAction,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.session_delete_title)) },
        text = {
            Text(
                stringResource(
                    when (action) {
                        SessionDeleteAction.DeleteLocalCopy -> R.string.session_delete_message_local_copy
                        SessionDeleteAction.DeleteOnlyCopy -> R.string.session_delete_message_only_copy
                    },
                ),
            )
        },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                // 되돌릴 수 없는 쪽을 error 색으로 둬서 취소와 눈으로 구분되게 한다.
                Text(
                    text = stringResource(R.string.action_delete),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) }
        },
    )
}
