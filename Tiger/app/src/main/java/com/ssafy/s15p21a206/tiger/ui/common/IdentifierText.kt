package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/**
 * 목록 카드에서 행의 오른쪽 끝에 놓이는 Session 식별자.
 *
 * 이 앱은 배포용이 아니라 수집용이다. 서버에 올라간 수집분을 찾을 때 쓰는 것은 수집 일시가 아니라
 * 이 값이므로 훑는 눈이 먼저 닿는 자리에 둔다. 작게 두지만 [SupportingText]처럼 옅게 두지 않는다.
 * 크기로 위계를 낮추고 대비는 지키는 것이며, 같은 문제를 다루는 GitHub의 커밋 목록도 짧은 SHA를
 * 12px로 두면서 색은 본문과 같게, 굵기는 주변 작은 글자보다 한 단계 굵게 둔다.
 *
 * 글꼴을 바꾸지 않는다. 고정폭은 값을 글자 단위로 대조하는 자리에만 쓰고, 그 자리는 전체 식별자가
 * 있는 세션 정보다. 목록에서 하는 일은 대조가 아니라 훑기이고, 열 정렬은 오른쪽 맞춤이 이미 준다.
 * 한 화면에 글꼴을 둘 두면 위계를 돕기보다 가린다.
 */
@Composable
@Suppress("FunctionName")
fun IdentifierText(
    text: String,
    modifier: Modifier = Modifier,
) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = modifier,
    )
}
