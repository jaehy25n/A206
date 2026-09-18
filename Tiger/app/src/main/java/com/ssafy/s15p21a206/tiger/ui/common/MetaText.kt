package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/**
 * 항목을 특정하지는 않는 부수 정보다.
 *
 * 사진 앱의 상세 화면이 촬영 일시를 앞세우고 크기·용량·파일명을 그 아래 작은 줄로 묶는 것과 같은
 * 자리다. Episode 수·길이·해상도·ID는 무엇을 찍은 것인지 알려 주지 않으므로 [SupportingText]보다
 * 한 단계 더 내린다.
 */
@Composable
@Suppress("FunctionName")
fun MetaText(
    text: String,
    modifier: Modifier = Modifier,
) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}
