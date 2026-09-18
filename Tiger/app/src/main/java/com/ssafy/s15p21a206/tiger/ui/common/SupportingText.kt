package com.ssafy.s15p21a206.tiger.ui.common

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign

/**
 * 제목에 딸린 보조 정보다.
 *
 * 목록 카드와 수집 상세가 제목과 부속 정보를 같은 크기로 쌓아 두어, 훑을 때 무엇이 제목인지
 * 구분되지 않았다. 두 화면이 같은 기준을 쓰도록 한곳에 둔다.
 */
@Composable
@Suppress("FunctionName")
fun SupportingText(
    text: String,
    modifier: Modifier = Modifier,
    textAlign: TextAlign? = null,
) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = textAlign,
        modifier = modifier,
    )
}
