package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ssafy.s15p21a206.tiger.ui.theme.TigerSurface

/**
 * 목록의 한 항목을 담는 카드다.
 *
 * 색을 호출부가 고르지 않게 하려고 둔다. `Card`를 그대로 쓰면 Material 3이 판 색과 콘텐츠 색을
 * 함께 정하는데, 그 콘텐츠 색이 `onSurfaceVariant`라 카드 안의 이름이 저절로 옅어졌다. 판은
 * [TigerSurface.content], 그 위 글자는 [TigerText][com.ssafy.s15p21a206.tiger.ui.theme.TigerText]의
 * 역할이 각자 정한 색을 쓴다. 두 결정이 한곳에 있어야 다음 카드도 같은 판에 놓인다.
 *
 * 그림자와 외곽선을 주지 않는다. 카드가 바닥보다 밝다는 것과 카드 사이 8dp가 경계를 만들고,
 * 여기에 그림자까지 더하면 한 항목에 경계가 셋이 된다.
 */
@Composable
@Suppress("FunctionName")
fun TigerCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier,
        colors =
            CardDefaults.cardColors(
                containerColor = TigerSurface.content,
                contentColor = MaterialTheme.colorScheme.onSurface,
            ),
        content = content,
    )
}
