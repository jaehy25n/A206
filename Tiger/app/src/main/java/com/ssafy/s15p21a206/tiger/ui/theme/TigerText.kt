package com.ssafy.s15p21a206.tiger.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.sp

/**
 * 이 앱이 글자에 주는 역할.
 *
 * 화면에서는 크기·굵기·색을 직접 고르지 않고 여기 이름 중에서 고른다. 조합을 자리마다 손으로
 * 만들면 축이 하나씩 늘어난다. 실제로 그렇게 됐던 적이 있다. 한 카드 안에서 요소 다섯이 글꼴 2종·
 * 크기 3종·굵기 2종·색 2종을 섞어 조합 다섯 개가 되었고, 어느 요소도 다른 요소와 스타일을 공유하지
 * 않아 위계가 아니라 잡음으로 읽혔다. 값이 넷인 GitHub의 커밋 행은 조합 셋으로 끝내고 글꼴은 하나,
 * 크기는 둘만 쓴다. Apple HIG도 조합을 손으로 만들지 말고 정해진 스타일에서 고르라고 하며, 글꼴을
 * 섞으면 정보 위계를 오히려 가린다고 적는다.
 *
 * 역할은 두 무리다. 표면 위에서 읽는 글과 프리뷰·영상 위에서 읽는 글은 색 체계가 다르다. 뒤가
 * 장면이면 표면 색을 쓸 수 없으므로 흰색으로 고정한다.
 *
 * 표면 위에서 읽는 아홉 역할은 모두 잉크 두 단계 중 하나를 골라 색을 명시한다. 진한 `onSurface`는
 * 그 항목을 짚는 글([sectionName], [itemName], [body], [value], [menuItem], [formLabel])이고, 옅은
 * `onSurfaceVariant`는 딸린 값과 이름표와 안내([bodyMuted], [supporting], [groupLabel])다.
 *
 * 크기는 셋이다. title 22sp, body 16sp, callout 14sp. 눈금과 그 이름은 Material 3의 타입 스케일에서
 * 가져오고, 실제 값은 [Typography]가 정한다. 괄호 안은 Apple HIG의 대응이다.
 *
 * | 층 | 크기 | 이 파일의 역할 |
 * | --- | --- | --- |
 * | title (title2 22) | 22 | [sectionName] |
 * | body (body 17, headline 17) | 16 | [itemName] [body] [bodyMuted] |
 * | callout (subhead 15) | 14 | [value] [supporting] [menuItem] [formLabel] |
 * | caption (caption1 12) | 12 | [groupLabel] |
 *
 * caption 층에는 값을 두지 않는다. 묶음 이름표만 든다. 값을 한 단계 더 내리면 층이 늘어나는 것이
 * 아니라 위가 홀로 커지지만, 표지는 값과 같은 층에 있으면 값으로 읽히므로 내려야 한다.
 *
 * **한 화면이 쓰는 크기는 둘**이고 그 둘은 늘 이웃한 칸이다. 목록은 이름([itemName], 16)과
 * 값([supporting], 14), 상세는 제목([sectionName], 22)과 본문([body], [bodyMuted], 16)
 * 이다. 짝이 화면마다 다를 뿐이다.
 *
 * 한 칸을 건너뛰면 위가 홀로 커 보인다. 상세가 본문 층 없이 제목 22sp에서 값 14sp로 곧장 떨어지던
 * 동안 그랬다. 목록 카드가 16·14·12로 세 칸을 쓰던 동안에도 같은 일이 났는데, 이름과 가장 작은
 * 값의 차이가 1.33배로 벌어졌다.
 *
 * 같은 층에 값이 여럿이라고 크기를 한 단계씩 더 내리지 않는다. 층이 늘어나는 것이 아니라 맨 위가
 * 홀로 커진다. 값들끼리는 굵기와 잉크로 가른다. 값이 넷인 GitHub의 커밋 행도 조합 셋으로 끝내면서
 * 글꼴은 하나, 크기는 둘만 쓴다.
 *
 * 색을 비워 두지 않는 것이 규칙이다. 비우면 놓인 자리의 콘텐츠 색을 따르는데, 그러면 같은 역할이
 * 자리마다 다르게 렌더된다. 실제로 그랬다. [itemName]이 Card 안에서 `onSurfaceVariant`로, 밖에서
 * `onSurface`로 나왔다. Material 3의 Card가 콘텐츠 색으로 `onSurfaceVariant`를 주기 때문이고 아무도
 * 의도한 적이 없다. 그래서 명시적으로 `onSurface`를 쓰던 식별자가 같은 카드의 제목보다
 * 진해져 위계가 뒤집혔다. 색을 여기서 정하면 호출부의 판이 무엇이든 역할이 흔들리지 않는다.
 *
 * 판의 색은 [TigerSurface]가 정한다.
 */
object TigerText {
    /** 한 묶음을 이끄는 이름. 홈의 `Tasks`, Task Session 목록의 Task 이름이 여기 해당한다. */
    val sectionName: TextStyle
        @Composable get() =
            MaterialTheme.typography.titleLarge
                .copy(
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                ).hugged

    /**
     * 한 항목 또는 한 화면의 이름. 카드의 Task 이름과 수집 일시, 화면 헤더 제목, 세션 정보 제목.
     *
     * 진한 잉크다. 이름은 [supporting]보다 약해질 수 없다.
     */
    val itemName: TextStyle
        @Composable get() =
            MaterialTheme.typography.titleMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 화면이 제 내용으로 읽히는 자리의 글. 상세의 전송 상태가 여기 해당한다.
     *
     * 목록 카드의 값보다 한 단계 크다. 상세는 훑는 화면이 아니라 확인하는 화면이라 줄을 아낄 이유가
     * 없고, 줄을 아끼지 않기로 했으면 크기도 목록의 밀도를 따를 이유가 없다.
     *
     * 이 층이 없던 동안 상세는 제목 22sp에서 값 14sp로 곧장 떨어져, 타입 스케일의 한 칸을 건너뛰었다.
     * 제목과 본문 사이가 두 계단이면 제목만 홀로 커 보인다. 한 화면에서 쓰는 크기는 여전히 둘이고,
     * 무엇과 무엇이 짝인지가 화면마다 다를 뿐이다. 목록은 [itemName]과 [supporting], 상세는
     * [sectionName]과 이 층이다.
     */
    val body: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 본문 층의 옅은 잉크. 상세의 Task·Object·짧은 ID, 실패 사유, 목록이 비었을 때의 안내.
     *
     * [body]와 크기가 같고 잉크로만 갈린다. 상세에서 이름에 딸린 값들이 여기 들고, 지금 무엇을 할 수
     * 있는지 말하는 줄은 [body]로 진하게 둔다.
     */
    val bodyMuted: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge
                .copy(color = MaterialTheme.colorScheme.onSurfaceVariant)
                .hugged

    /**
     * 이름표가 가리키는 내용. 세션 정보 시트의 값이 여기 해당한다.
     *
     * 시트 제목([itemName])보다 한 단계 작다. 같은 크기이면 제목이 목록의 첫 항목처럼 읽히고 큰
     * 글자가 사다리처럼 쌓인다. 이름표인 [supporting]과는 크기가 아니라 잉크로 갈린다.
     *
     * 시트는 상세와 달리 목록의 밀도를 따른다. 훑어 확인하고 닫는 판이고, 전체 식별자가 한 줄에
     * 들어가야 행 높이가 고르다.
     */
    val value: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 목록에서 이름에 딸려 그것을 설명하는 값과 이름표. 카드의 Object·짧은 ID와 전송 상태,
     * 세션 개수, 세션 정보 시트의 이름표.
     *
     * 이름과는 크기와 굵기로, 같은 크기인 [value]와는 잉크로 갈린다.
     */
    val supporting: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = MaterialTheme.colorScheme.onSurfaceVariant)
                .hugged

    /**
     * 한 묶음 위에 붙어 그 묶음이 무엇인지 말하는 이름표. 상세의 `세션 정보`, `업로드 상태`.
     *
     * 묶음 안의 글([body])보다 작고 옅다. 이름표는 읽는 대상이 아니라 무엇을 읽고 있는지 알려 주는
     * 표지이므로, 제 묶음보다 커지면 묶음이 이름표에 딸린 것처럼 읽힌다.
     *
     * caption 층이다. 한 번 14sp로 두었더니 본문 16sp와 2sp밖에 차이가 나지 않고 잉크도 같아, 이름표가
     * 표지가 아니라 그냥 작은 한 줄로 읽혔다. 표지는 값과 같은 층에 있으면 값이 된다. 층을 내려야
     * 훑는 눈이 "이건 읽을 것이 아니라 무엇을 읽는지 알려 주는 것"으로 넘긴다.
     *
     * Material 3에서 이 자리의 이름이 `labelMedium`이다. 굵기가 한 단계 높아 작아져도 묻히지 않는다.
     * Apple의 grouped list도 구획 머리를 본문보다 작게 두는데, 영어는 대문자로 한 번 더 가르고 한국어는
     * 그 수단이 없으므로 크기와 굵기가 그 몫을 한다.
     */
    val groupLabel: TextStyle
        @Composable get() =
            MaterialTheme.typography.labelMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 메뉴 항목의 글자.
     *
     * Material 3의 `DropdownMenuItem`은 `labelLarge`를 집어 쓰는데 그 역할은 Medium 굵기다. 버튼의
     * 글자를 굵게 세우는 눈금이라 메뉴에서는 항목 넷이 모두 강조된 것처럼 보인다. 굵기만 한 단계
     * 내린다.
     *
     * 호출부가 `fontWeight`를 직접 지정하고 있었다. 세 자리에서 각자 지정했고 그중 둘은 상수를
     * 따로 두었다. 조합은 화면이 아니라 여기서 정한다.
     */
    val menuItem: TextStyle
        @Composable get() =
            MaterialTheme.typography.labelLarge
                .copy(
                    fontWeight = FontWeight.Normal,
                    color = MaterialTheme.colorScheme.onSurface,
                ).hugged

    /** 입력 모달에서 한 무리의 입력을 이끄는 이름표. */
    val formLabel: TextStyle
        @Composable get() =
            MaterialTheme.typography.labelLarge
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 프리뷰를 덮은 판 위의 이름. 마감 진행과 마감 실패 문구.
     *
     * 아래 네 역할은 뒤가 장면이라 표면 색을 쓸 수 없다. 장면이 가장 밝을 때를 기준으로 명도 대비가
     * WCAG AA를 넘도록 흰색으로 고정한다. 크기가 타입 스케일에 없는 값인 것은 프리뷰 위에서 읽히는
     * 크기를 따로 맞춘 결과이며, 여기 이름을 붙여 다음에 또 새 숫자가 나오지 않게 한다.
     */
    val overlayTitle: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge.copy(
                fontSize = 18.sp,
                fontWeight = FontWeight.Medium,
                color = Color.White,
            )

    /** 프리뷰를 덮은 판 위에서 이름에 딸린 줄. 마감 중 이탈 경고. */
    val overlaySupporting: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge.copy(
                fontSize = 14.sp,
                color = CaptureOverlaySupporting,
            )

    /** 프리뷰 위 알약 배지. 수집 상태와 녹화 해상도. */
    val overlayBadge: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge.copy(
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
                color = Color.White,
            )

    /**
     * 프리뷰 위에서 아이콘 대신 쓰는 글리프. X 닫기.
     *
     * 비활성일 때는 호출부가 색을 덮는다. 의미색을 흐리기만 하면 여전히 그 색으로 읽혀 비활성으로
     * 보이지 않으므로, 중성 색으로 바꾼다.
     */
    val overlayGlyph: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge.copy(
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White,
            )

    /** 검은 배경의 전체 화면 영상 위에서 읽는 글. 재생할 영상이 없다는 안내. */
    val onVideoBody: TextStyle
        @Composable get() = MaterialTheme.typography.bodyLarge.copy(color = Color.White)
}

/**
 * 줄상자가 글자를 감싸게 한다.
 *
 * Material 3의 타입 스케일은 줄 높이를 글자 크기보다 크게 잡는다. 16sp 글자에 24dp 줄상자다. 그
 * 차이는 상자 위아래의 여백으로 남고, 화면에서 `spacedBy`로 준 간격은 그 상자 **바깥**에 더해진다.
 * 그래서 쓴 값과 보이는 값이 달랐다. 목록 카드에서 `spacedBy(4.dp)`를 준 자리의 실제 간격은
 * `SM-G973N`에서 13dp였다.
 *
 * 간격을 눈으로 맞추려면 숫자를 올렸다 내렸다 해야 하고, 그렇게 맞춘 값은 글꼴이나 타입 스케일이
 * 바뀌는 순간 다시 어긋난다. 상자가 글자를 감싸게 해 두면 쓴 값이 곧 보이는 값이 되고, 간격은
 * 그 자리에서 의도한 대로 정할 수 있다.
 *
 * 여러 줄인 글에서는 첫 줄 위와 마지막 줄 아래만 깎는다. 줄과 줄 사이의 간격은 그대로 두므로 문단이
 * 빽빽해지지 않는다.
 *
 * 프리뷰·영상 위 역할에는 걸지 않는다. 그쪽은 알약 배지처럼 제 배경을 갖는 자리라 상자의 여백이
 * 배지 안쪽 여백 노릇을 하고 있다.
 */
private val TextStyle.hugged: TextStyle
    get() =
        copy(
            lineHeightStyle =
                LineHeightStyle(
                    alignment = LineHeightStyle.Alignment.Center,
                    trim = LineHeightStyle.Trim.Both,
                ),
        )
