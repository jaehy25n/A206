package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText

/**
 * 메뉴의 한 항목이다. 글리프와 글자가 한 덩어리로 읽히게 붙여 놓는다.
 *
 * Material 3의 `leadingIcon` 슬롯을 쓰지 않는다. 그 슬롯은 글리프와 글자 사이를 12dp로 두는데, 항목의
 * 가장자리 여백도 12dp다. 두 간격이 같으면 글리프가 글자에 붙은 것이 아니라 여백 둘 사이에 떠 있는
 * 것으로 읽힌다. 묶고 싶은 것을 더 붙여 놓아야 한다.
 *
 * 색은 여기서 박지 않고 [MenuDefaults.itemColors]에 맡긴다. 메뉴 항목의 색은 스타일이 아니라 상태가
 * 정한다. 되돌릴 수 없는 항목은 error 색으로, 지금 누를 수 없는 항목은 흐린 색으로 그려야 하는데 그
 * 판단은 컴포넌트가 한다. 글자에 색을 박아 두었을 때 삭제 항목의 글리프만 붉고 글자는 검었고,
 * 비활성일 때 흐려지지도 않았다.
 *
 * 글리프에는 접근성 이름을 두지 않는다. 바로 옆 글자가 이미 이름을 말하므로 두 번 읽게 된다.
 */
@Composable
@Suppress("FunctionName")
fun TigerMenuItem(
    label: String,
    icon: Int,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    destructive: Boolean = false,
) {
    DropdownMenuItem(
        modifier = modifier,
        text = {
            Row(
                horizontalArrangement = Arrangement.spacedBy(GLYPH_GAP),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(painter = painterResource(icon), contentDescription = null)
                Text(text = label, style = TigerText.menuItem)
            }
        },
        enabled = enabled,
        colors =
            if (destructive) {
                // 되돌릴 수 없는 항목은 error 색으로 둬서 위 항목과 성격이 다름을 보인다. 글자와
                // 글리프가 같은 색이어야 한 덩어리로 읽힌다.
                MenuDefaults.itemColors(
                    textColor = MaterialTheme.colorScheme.error,
                    leadingIconColor = MaterialTheme.colorScheme.error,
                )
            } else {
                MenuDefaults.itemColors()
            },
        onClick = onClick,
    )
}

/** 글리프와 글자 사이. 항목의 가장자리 여백(12dp)보다 좁아야 둘이 한 덩어리로 읽힌다. */
private val GLYPH_GAP = 8.dp
