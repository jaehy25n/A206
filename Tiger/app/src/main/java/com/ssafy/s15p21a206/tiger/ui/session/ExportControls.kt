package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.ExportState

@Suppress("FunctionName")
@Composable
internal fun ExportControls(
    state: ExportState,
    failureReason: String?,
    onSelectTree: () -> Unit,
) {
    // 아직 내보내지 않았다는 것은 바로 아래 버튼이 이미 말한다. 그 상태에서만 나오는 버튼이므로
    // 같은 말을 한 줄 더 적지 않는다. 진행·완료는 버튼이 사라지는 자리라 문구가 유일한 신호이고,
    // 실패는 버튼이 옮기지 못하는 이유를 담는다.
    val label =
        when (state) {
            ExportState.NOT_EXPORTED -> null
            ExportState.EXPORTING -> stringResource(R.string.export_exporting)
            ExportState.EXPORTED -> stringResource(R.string.export_exported)
            ExportState.EXPORT_FAILED -> stringResource(R.string.export_failed, failureReason.orEmpty())
        }
    if (label != null) Text(label)
    if (state != ExportState.EXPORTED && state != ExportState.EXPORTING) {
        Button(onClick = onSelectTree) {
            Text(
                stringResource(
                    if (state ==
                        ExportState.EXPORT_FAILED
                    ) {
                        R.string.export_retry
                    } else {
                        R.string.export_select_tree
                    },
                ),
            )
        }
    }
}
