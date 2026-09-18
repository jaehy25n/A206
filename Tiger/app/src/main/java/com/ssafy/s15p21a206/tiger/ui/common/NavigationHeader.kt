package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R

/**
 * 뒤로 가기와 제목을 담는 조회 화면 공통 헤더다.
 *
 * Task 목록·세션 상세·업로드 상태가 같은 헤더를 각자 갖고 있었다. 한곳에 두어야 제목의 타이포와
 * 여백이 화면마다 어긋나지 않는다. 시스템 바 회피는 각 목적지를 감싸는 판이 담당하므로 여기서
 * 인셋을 다시 처리하지 않는다.
 *
 * [actions]에는 이 화면에 딸린 부수 동작을 둔다. 화면의 주 동작은 여기가 아니라 본문이나 FAB가
 * 맡는다.
 */
@Composable
@Suppress("FunctionName")
fun NavigationHeader(
    title: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    actions: @Composable RowScope.() -> Unit = {},
) {
    Row(
        modifier = modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = HEADER_VERTICAL_PADDING),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(
                painter = painterResource(R.drawable.ic_navigation_back),
                contentDescription = stringResource(R.string.navigation_back),
            )
        }
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            // 제목이 남는 폭을 다 가져가야 동작이 오른쪽 끝에 붙는다.
            modifier = Modifier.weight(1f),
        )
        actions()
    }
}

private val HEADER_VERTICAL_PADDING = 4.dp

/** 헤더가 담는 뒤로 가기 버튼의 크기. 제목은 이 높이의 한가운데에 놓인다. */
private val HEADER_ACTION_SIZE = 48.dp

/**
 * 헤더 제목의 중심이 헤더 위쪽 끝에서 떨어진 거리.
 *
 * 헤더가 없는 화면이 제목을 같은 높이에 놓으려 할 때 쓴다. 화면을 오갈 때 제목이 제자리에
 * 머무르는 것으로 보이려면 두 화면이 같은 값을 봐야 한다.
 */
val NavigationHeaderTitleCenter = HEADER_VERTICAL_PADDING + HEADER_ACTION_SIZE / 2
