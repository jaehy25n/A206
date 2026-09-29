package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText

/**
 * 한 묶음을 이끄는 이름표다.
 *
 * 굵은 이름 아래 그것을 설명하는 한 줄이 붙는다. 카드도 같은 짜임이고 다른 것은 이름의 크기뿐이다.
 * 딸린 줄은 두 층 모두 같은 크기(14sp)라 무엇이 상위인지는 이름의 크기가 가른다. 묶음 이름 아래의
 * 개수는 가장 옅은 잉크([TigerText.sectionCount])로 한 단계 더 물러난다.
 *
 * 홈과 Task Session 목록이 쓴다. 상세는 이름(수집 일시) 아래에 설명 줄 대신 이름표를 단 묶음 카드를
 * 두므로 이것을 쓰지 않는다.
 */
@Composable
@Suppress("FunctionName")
fun ListSectionHeader(
    title: String,
    supporting: String?,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(text = title, style = TigerText.sectionName)
        if (supporting != null) Text(text = supporting, style = TigerText.sectionCount)
    }
}
