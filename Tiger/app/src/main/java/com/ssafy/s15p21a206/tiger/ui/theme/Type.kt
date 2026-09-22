package com.ssafy.s15p21a206.tiger.ui.theme

import androidx.compose.material3.Typography

/**
 * 이 앱이 쓰는 타입 스케일.
 *
 * 화면이 고르는 것은 [TigerText]의 역할이지만, Material 3 컴포넌트는 그 역할을 모른다. `Button`은
 * `labelLarge`를, `AlertDialog`는 제목에 `headlineSmall`과 본문에 `bodyMedium`을, `DropdownMenuItem`은
 * `labelLarge`를, `TextField`의 이름표는 `bodyLarge`를 제 안에서 집어 쓴다. 그래서 여기서 스케일을
 * 정해 두지 않으면 앱이 고른 크기와 컴포넌트가 고른 크기가 따로 논다.
 *
 * 실제로 그랬다. 이 파일은 Android Studio 템플릿 그대로였고 유일한 재정의는 M3 기본값을 똑같이 다시
 * 적은 no-op이었다. 그동안 삭제 확인 판의 제목이 `headlineSmall` 24sp로, 앱의 화면 제목 22sp보다
 * 컸다. 앱에서 가장 큰 글자가 "정말 지울까요"였다.
 *
 * ## 층
 *
 * 크기는 넷이다. Material 3의 타입 스케일에서 이름을 빌리고, 괄호 안은 Apple HIG의 대응이다.
 *
 * | 층 | 크기 | 쓰는 곳 |
 * | --- | --- | --- |
 * | title | 22sp | 화면과 묶음의 이름. `titleLarge` (title2 22) |
 * | body | 16sp | 상세 본문, 목록 항목의 이름. `bodyLarge`·`titleMedium` (body 17, headline 17) |
 * | callout | 14sp | 목록의 값, 컨트롤의 글자, 묶음 이름표. `bodyMedium`·`titleSmall`·`labelLarge` (subhead 15) |
 * | caption | 12sp | 아직 쓰는 곳이 없다. `bodySmall` (caption1 12) |
 *
 * 22 위는 비워 둔다. `display`와 `headline`은 한 화면에 제목이 여럿인 문서형 화면의 눈금이고, 이
 * 앱에는 그런 화면이 없다. `headlineSmall`만 `AlertDialog`가 집어 쓰므로 title 층으로 끌어내린다.
 *
 * 값은 M3 기본에서 크기만 손대고 줄 높이와 자간은 그대로 둔다. 줄상자의 남는 여백은 [TigerText]가
 * 역할마다 깎으므로 여기서 줄 높이를 줄일 이유가 없다.
 */
val Typography =
    Typography().let { m3 ->
        m3.copy(
            // AlertDialog의 제목이 이것을 집어 쓴다. 화면 제목보다 클 이유가 없다.
            headlineSmall = m3.headlineSmall.copy(fontSize = m3.titleLarge.fontSize),
        )
    }
