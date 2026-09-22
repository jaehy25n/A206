package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
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
        Text(text = label, style = TigerText.groupLabel)
        Column(verticalArrangement = Arrangement.spacedBy(CONTENT_LINE_GAP), content = content)
    }
}

/**
 * 이름표와 값이 한 행에 놓인 한 줄이다. `Task 문도`가 아니라 `Task`와 `문도`다.
 *
 * 둘을 한 문자열로 이어 붙이면 평문 한 줄이 된다. 그런데 이것은 문장이 아니라 이름표와 그것이
 * 가리키는 값이고, 그 둘은 종류가 다르다. 붙여 쓰면 `Task`가 값의 일부처럼 읽히고, 줄을 여럿
 * 쌓으면 어느 낱말이 이름표이고 어느 낱말이 값인지 매번 다시 가려내야 한다.
 *
 * 이름표는 폭을 고정한다. 값이 한 기둥에 정렬되어야 훑을 때 눈이 값만 따라 내려갈 수 있다. 이름표가
 * 제 글자 폭만 차지하면 값의 시작점이 줄마다 달라져 왼쪽 가장자리가 톱니처럼 된다.
 *
 * 이름표는 값보다 옅다. 크기는 같게 둔다. 크기까지 내리면 이름표가 묶음 이름표와 같은 층이 되어
 * 어느 것이 무엇의 표지인지 흐려진다.
 */
@Composable
@Suppress("FunctionName")
fun LabelledValue(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Row(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(LABEL_VALUE_GAP)) {
        Text(
            text = label,
            style = TigerText.bodyMuted,
            modifier = Modifier.width(LABEL_COLUMN_WIDTH),
        )
        Text(text = value, style = TigerText.body)
    }
}

/** 이름표와 그 아래 묶음 사이. 묶음 안 줄 사이보다 좁아야 이름표가 묶음에 붙는다. */
private val LABEL_GAP = 4.dp

/** 묶음 안 줄 사이. */
private val CONTENT_LINE_GAP = 6.dp

/**
 * 이름표 기둥의 폭.
 *
 * 지금 쓰는 이름표 중 가장 긴 `Object`가 들어가고 값과 붙지 않을 만큼이다. 값이 아니라 이름표가
 * 폭을 정하므로, 이름표가 길어지면 이 값을 늘린다. 값의 길이는 여기에 영향을 주지 않는다.
 */
private val LABEL_COLUMN_WIDTH = 72.dp

/** 이름표 기둥과 값 사이. */
private val LABEL_VALUE_GAP = 8.dp
