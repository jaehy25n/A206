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
 * 딸린 줄은 두 층 모두 같은 역할을 써서 무엇이 상위인지는 이름의 크기 하나로만 갈리게 한다.
 *
 * 목록 화면과 세션 상세가 같은 것을 쓴다. 상세의 이름은 수집 일시다.
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
        if (supporting != null) Text(text = supporting, style = TigerText.supporting)
    }
}
