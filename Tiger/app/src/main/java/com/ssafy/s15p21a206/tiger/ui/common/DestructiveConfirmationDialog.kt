package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ssafy.s15p21a206.tiger.R

/**
 * 되돌릴 수 없는 동작을 확인받는 판이다.
 *
 * 세션 종료와 세션 삭제가 각자 판을 들고 있었고, 한쪽은 채워진 빨간 버튼, 다른 쪽은 빨간 글씨라
 * 같은 무게의 결정이 다르게 생겨 보였다. 한 곳에 두어야 다음에 또 갈라지지 않는다.
 *
 * 확정 쪽을 채워진 error 버튼으로 둔다. 되돌릴 수 없는 선택은 취소와 눈에 띄게 달라야 하고,
 * 글씨 색만으로는 두 선택이 같은 무게로 보인다.
 */
@Composable
@Suppress("FunctionName")
fun DestructiveConfirmationDialog(
    title: String,
    message: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(message) },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors =
                    ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                        contentColor = MaterialTheme.colorScheme.onError,
                    ),
            ) { Text(confirmLabel) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_cancel)) } },
    )
}
