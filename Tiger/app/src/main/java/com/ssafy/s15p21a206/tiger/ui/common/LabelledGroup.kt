package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText

/**
 * 이름표를 머리에 단 한 묶음이다.
 *
 * 성격이 다른 값들이 한 화면에 쌓일 때, 간격만으로 가르면 무엇이 왜 갈렸는지는 말해 주지 못한다.
 * 상세 화면에서 수집 일시·Task·Object·ID·전송 상태가 한 더미로 쌓여 있던 동안, 전송 상태가 이 수집이
 * 무엇인지 말하는 값들과 같은 종류로 읽혔다. 하나는 이 기록이 무엇인가이고 하나는 지금 어떤가다.
 *
 * Apple의 grouped list와 Material 3의 목록 소제목이 같은 일을 한다. 구획마다 머리를 달고, 그 머리는
 * 구획 안의 글보다 작고 옅다.
 *
 * 이름표와 내용 사이는 내용의 줄 사이보다 좁다. 붙어 있어야 그 이름표가 아래 묶음의 것으로 읽히고,
 * 묶음과 묶음 사이는 호출부가 벌린다.
 */
@Composable
@Suppress("FunctionName")
fun LabelledGroup(
    label: String,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(LABEL_GAP)) {
        androidx.compose.material3.Text(text = label, style = TigerText.groupLabel)
        Column(verticalArrangement = Arrangement.spacedBy(CONTENT_LINE_GAP), content = content)
    }
}

/** 이름표와 그 아래 묶음 사이. 묶음 안 줄 사이보다 좁아야 이름표가 묶음에 붙는다. */
private val LABEL_GAP = 4.dp

/** 묶음 안 줄 사이. */
private val CONTENT_LINE_GAP = 6.dp
