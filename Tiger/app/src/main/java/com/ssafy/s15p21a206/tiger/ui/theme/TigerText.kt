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
 * ## 잉크 셋
 *
 * 진한 `onSurface`는 값과 이름([sectionName], [itemTitle], [itemName], [body], [value], [formLabel]), 옅은
 * `onSurfaceVariant`는 값에 딸린 값과 행 이름표([bodyMuted], [supporting]), 가장 옅은 [InkFaint]는
 * 값이 아니라 값을 가리키는 것([groupLabel], [sectionCount], [identifier])이다.
 *
 * 셋째 단계를 둔 것은 표지와 값이 같은 잉크를 쓰면 표지가 값으로 읽히기 때문이다. 묶음 이름표가 행
 * 이름표와 같은 옅은 잉크였던 동안 `세션 정보`가 `Task`의 작은 버전으로 보였다. 목록 카드에서
 * 이름표 낱말을 걷어 낼 수 있는 것도 이 단계 덕이다. `Object`와 `ID`를 적지 않아도 어느 쪽이
 * 기계가 부르는 이름인지 잉크가 말한다.
 *
 * [menuItem]만 색을 비운다. 메뉴 항목의 색은 스타일이 아니라 상태가 정한다.
 *
 * ## 크기 다섯
 *
 * 눈금과 그 이름은 Material 3의 타입 스케일에서 가져오고, 실제 값은 [Typography]가 정한다. 괄호 안은
 * Apple HIG의 대응이다.
 *
 * | 층 | 크기 | 이 파일의 역할 |
 * | --- | --- | --- |
 * | largeTitle (title1 28) | 28 | [sectionName] |
 * | title (title2 22) | 22 | [itemTitle]. `AlertDialog`도 제 제목에 쓴다 |
 * | body (body 17, headline 17) | 16 | [itemName] [body] [bodyMuted] |
 * | callout (subhead 15) | 14 | [value] [supporting] [sectionCount] [identifier] [menuItem] [formLabel] |
 * | caption (caption1 12) | 12 | [groupLabel] |
 *
 * caption 층에는 값을 두지 않는다. 묶음 이름표만 든다. 값을 한 단계 더 내리면 층이 늘어나는 것이
 * 아니라 위가 홀로 커지지만, 표지는 값과 같은 층에 있으면 값으로 읽히므로 내려야 한다.
 *
 * 위 두 층은 이름의 층이고 서로 갈린다. [sectionName]은 묶음의 이름, [itemTitle]은 한 항목의
 * 이름이다. 둘을 같은 층에 두었더니 한 세션의 수집 일시가 `Tasks`와 같은 무게로 서서, 그 화면이
 * 목록인지 항목인지가 크기로 구별되지 않았다.
 *
 * 카드 안의 값은 어느 화면에서나 같은 층이다. 목록 카드와 상세의 묶음 카드가 같은 짜임이므로 같은
 * 밀도로 읽힌다. 한동안 상세만 한 칸 크게 두었는데, 그때는 상세에 카드가 없어 본문이 화면에 직접
 * 놓여 있었다. 카드가 생긴 뒤로는 목록과 다르게 둘 이유가 사라졌다.
 *
 * 한 칸을 건너뛰면 위가 홀로 커 보인다. 상세가 본문 층 없이 제목 22sp에서 값 14sp로 곧장 떨어지던
 * 동안 그랬다. 목록 카드가 16·14·12로 세 칸을 쓰던 동안에도 같은 일이 났는데, 이름과 가장 작은
 * 값의 차이가 1.33배로 벌어졌다. 지금의 상세도 제목(22sp) 아래 값이 14sp지만, 값은 카드에 담기고 그
 * 위에 묶음 이름표가 선다. 값이 카드 없이 화면에 바로 놓였던 그때와는 짜임이 다르다.
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
    /**
     * 묶음의 이름. 홈의 `Tasks`, Task Session 목록의 Task 이름.
     *
     * 한 화면에 하나뿐이고 크다. iOS 메모의 large title이 같은 자리이며, 그 크기가 "여기가 어디인가"를
     * 묻지 않아도 답해 준다. 22sp였을 때는 아래 값들과 한 계단 반밖에 차이가 나지 않아 화면의 이름이
     * 아니라 첫 항목처럼 읽혔다.
     */
    val sectionName: TextStyle
        @Composable get() =
            MaterialTheme.typography.headlineMedium
                .copy(
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                ).hugged

    /**
     * 한 항목을 펼쳐 놓은 화면의 이름. Session 상세의 수집 일시.
     *
     * [sectionName]과 같은 층에 두지 않는다. 그쪽은 묶음의 이름이고 이쪽은 한 항목의 이름이라 종류가
     * 다르다. 묶음 이름을 키우면서 같이 키웠더니 한 세션의 수집 일시가 `Tasks`와 같은 무게로 서서,
     * 이 화면이 목록인지 항목인지가 크기로 구별되지 않았다.
     *
     * 목록 카드에서 같은 값이 [itemName]으로 한 단계 더 작다. 카드에서는 여럿 중 하나이고 여기서는
     * 화면 전체가 그것에 대한 것이므로, 같은 값이라도 자리에 따라 무게가 다르다.
     */
    val itemTitle: TextStyle
        @Composable get() =
            MaterialTheme.typography.titleLarge
                .copy(
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                ).hugged

    /**
     * 한 항목의 이름. 목록 카드의 Task 이름과 수집 일시, 상세 정보 시트 제목. 화면 헤더의 제목 자리도
     * 이 역할이지만 지금은 헤더에 제목을 두는 화면이 없다.
     *
     * 진한 잉크다. 이름은 [supporting]보다 약해질 수 없다.
     */
    val itemName: TextStyle
        @Composable get() =
            MaterialTheme.typography.titleMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 카드에 담기지 않고 화면에 직접 놓이는 진한 문장. 지금은 쓰는 자리가 없다. 그런 문장(세션을 찾을 수
     * 없다는 안내, 재생할 영상이 없다는 안내, 목록이 비었을 때의 안내)은 모두 [bodyMuted]로 옅게 둔다.
     *
     * 카드 안의 값보다 한 단계 크다. 카드는 값을 여럿 담아 훑게 하는 그릇이고, 이 자리의 글은 화면에
     * 혼자 있어 그 한 줄이 곧 화면의 내용이다.
     */
    val body: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 본문 층의 옅은 잉크. 카드에 담기지 않고 화면에 직접 놓이는 문장이 여기 든다. 세션을 찾을 수 없다는
     * 안내, 재생할 영상이 없다는 안내, 목록이 비었을 때의 안내.
     *
     * [body]와 크기가 같고 잉크로만 갈린다. 상세의 Task·Object·ID와 전송 상태는 카드에 담기므로 여기가
     * 아니라 [value]를 쓴다.
     */
    val bodyMuted: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge
                .copy(color = MaterialTheme.colorScheme.onSurfaceVariant)
                .hugged

    /**
     * 카드 안에서 이름표가 가리키는 내용. 상세 묶음 카드의 값, 상세 정보 시트의 값, 전송 상태.
     *
     * 카드는 목록이든 상세든 같은 밀도로 읽힌다. 이름표인 [supporting]과는 크기가 아니라 잉크로
     * 갈린다. 카드를 이끄는 이름([itemName], [itemTitle])보다는 한 단계 이상 작다.
     */
    val value: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 이름에 딸려 그것을 설명하는 값과 이름표. 목록 카드의 Object와 전송 상태, Task 카드의 세션 개수,
     * 상세 묶음 카드와 상세 정보 시트의 이름표, 전송 실패 사유.
     *
     * 이름과는 크기와 굵기로, 같은 크기인 [value]와는 잉크로 갈린다.
     */
    val supporting: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = MaterialTheme.colorScheme.onSurfaceVariant)
                .hugged

    /**
     * 묶음 이름 아래에 그 묶음이 몇 개를 담았는지 적는 줄. 홈의 `1개의 Task`, 목록의 `2개의 Session`.
     *
     * 가장 옅은 잉크다. 이름을 읽은 사람이 곧바로 목록으로 눈을 내리는 자리라, 이 줄이 [supporting]
     * 만큼 진하면 읽고 지나가야 할 값으로 걸린다. iOS 메모도 폴더 이름 아래 개수를 본문보다 옅게 둔다.
     */
    val sectionCount: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = InkFaint)
                .hugged

    /**
     * 기계가 부르는 이름. 목록 카드의 짧은 Session 식별자.
     *
     * 가장 옅은 잉크다. 목록에서 세션을 고를 때 쓰는 값이 아니라 고른 뒤에 쓰는 값이고, 같은 카드의
     * Object보다 한 단계 물러나야 둘이 다른 성격임이 이름표 없이도 읽힌다.
     */
    val identifier: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = InkFaint)
                .hugged

    /**
     * 한 묶음 위에 붙어 그 묶음이 무엇인지 말하는 이름표. 상세의 `세션 정보`, `업로드 상태`.
     *
     * 묶음 안의 값([value])보다 작고 옅다. 이름표는 읽는 대상이 아니라 무엇을 읽고 있는지 알려 주는
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
                .copy(color = InkFaint)
                .hugged

    /**
     * 메뉴 항목의 글자.
     *
     * 이 역할만 색을 비운다. 메뉴 항목의 색은 스타일이 아니라 상태가 정하기 때문이다. 되돌릴 수 없는
     * 항목은 error 색으로, 지금 누를 수 없는 항목은 흐린 색으로 그려야 하는데 그 판단은 컴포넌트가
     * 한다. 역할이 색을 박으면 그 판단을 덮는다.
     *
     * 실제로 덮었다. `onSurface`를 박아 둔 동안 삭제 항목의 글리프만 붉고 글자는 검었다. 호출부가
     * `MenuDefaults.itemColors(textColor = error)`를 주고 있었는데 스타일의 색이 이겼다. 비활성일 때
     * 흐려지는 것도 같은 이유로 막혀 있었다.
     *
     * 색을 비우는 것이 규칙의 예외가 아니라 규칙의 다른 절반이다. 역할은 크기와 굵기를, 컴포넌트는
     * 상태에 따른 색을 정한다.
     */
    val menuItem: TextStyle
        @Composable get() = MaterialTheme.typography.labelLarge.hugged

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

    /** 프리뷰를 덮은 판 위에서 이름에 딸린 줄. 마감 중 이탈 경고, 카메라 설정 시트의 항목 이름과 안내. */
    val overlaySupporting: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge.copy(
                fontSize = 14.sp,
                color = CaptureOverlaySupporting,
            )

    /** 프리뷰 위 알약 배지(수집 상태)와 카메라 설정 시트의 제목·값·선택지. */
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
