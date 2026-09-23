package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText

/**
 * 작은 이름표를 머리에 달고 내용을 카드에 담은 한 묶음이다. Apple의 grouped list가 하는 그것이다.
 *
 * 성격이 다른 값들이 한 화면에 쌓일 때, 간격만으로 가르면 무엇이 왜 갈렸는지는 말해 주지 못한다.
 * 상세 화면에서 수집 일시·Task·Object·ID·전송 상태가 한 더미로 쌓여 있던 동안, 전송 상태가 이 수집이
 * 무엇인지 말하는 값들과 같은 종류로 읽혔다. 하나는 이 기록이 무엇인가이고 하나는 지금 어떤가다.
 *
 * ## 왜 카드가 필요한가
 *
 * 처음에는 카드 없이 이름표만 달았다. 그러자 이름표의 크기가 어느 쪽으로도 맞지 않았다. 제목이라면
 * 아래 글보다 크고 굵어야 하는데 작았고, 이름표라면 이름표답게 보여야 하는데 그냥 작은 한 줄이었다.
 *
 * 원인은 크기가 아니라 그릇이 없다는 것이었다. Apple의 grouped list에서 구획 머리가 작아도 되는 것은
 * 묶는 일을 머리가 아니라 카드가 하기 때문이다. 머리는 회색 바닥 위에 떠서 아래 카드를 가리키기만
 * 한다. 그릇 없이 머리만 달면 그 작은 글자가 묶는 일까지 혼자 해야 하고, 그래서 어느 쪽으로도
 * 읽히지 않았다.
 *
 * 그릇을 주면 이름표가 작아도 된다. 이 앱은 목록에서 이미 회색 바닥과 흰 카드를 쓰므로, 상세도 같은
 * 말을 하게 된다. 크기를 키워 제목으로 만드는 길도 있었으나, 그러면 한 화면에 제목이 둘이 되고
 * 수집 일시가 화면의 이름이라는 것이 흐려진다.
 *
 * 이름표는 카드의 왼쪽 끝에 맞춘다. 카드 안 글자에 맞추면 한 칸 들여쓴 꼴이 되어 화면 제목과
 * 어긋난다. 카드의 안쪽 여백은 카드의 것이지 바깥에 선 글자가 따라갈 선이 아니다. 화면 제목과
 * 이름표와 카드의 왼쪽 끝이 한 줄에 서야 왼쪽 가장자리가 하나로 읽힌다.
 *
 * 이름표와 카드 사이는 카드 안 줄 사이보다 좁다. 붙어 있어야 그 이름표가 아래 카드의 것으로 읽히고,
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
        TigerCard(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(CARD_PADDING),
                verticalArrangement = Arrangement.spacedBy(CONTENT_LINE_GAP),
                content = content,
            )
        }
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

/** 이름표와 그 아래 카드 사이. 카드 안 줄 사이보다 좁아야 이름표가 카드에 붙는다. */
private val LABEL_GAP = 4.dp

/** 묶음 안 줄 사이. */
private val CONTENT_LINE_GAP = 6.dp

/** 카드가 안쪽에 두는 여백. 목록 카드와 같은 값이다. */
private val CARD_PADDING = 16.dp

/**
 * 이름표 기둥의 폭.
 *
 * 지금 쓰는 이름표 중 가장 긴 `Object`가 들어가고 값과 붙지 않을 만큼이다. 값이 아니라 이름표가
 * 폭을 정하므로, 이름표가 길어지면 이 값을 늘린다. 값의 길이는 여기에 영향을 주지 않는다.
 */
private val LABEL_COLUMN_WIDTH = 72.dp

/** 이름표 기둥과 값 사이. */
private val LABEL_VALUE_GAP = 8.dp
