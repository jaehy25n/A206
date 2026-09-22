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
 * 표면 위에서 읽는 일곱 역할은 모두 잉크 두 단계 중 하나를 골라 색을 명시한다. 진한 `onSurface`는
 * 그 항목을 짚는 글([sectionName], [itemName], [value], [identifier], [formLabel])이고, 옅은
 * `onSurfaceVariant`는 딸린 값과 이름표와 안내([supporting], [guidance])다.
 *
 * 크기는 둘이다. 이름([sectionName], [itemName])과 값이다. 값 쪽 넷([value], [supporting],
 * [identifier], [formLabel])은 크기가 같고 굵기와 잉크로만 갈린다. 전에는 셋이었고, 카드에서 이름과
 * 가장 작은 값의 차이가 1.33배로 벌어져 이름만 과하게 커 보였다. 값이 여럿이라고 크기를 한 단계씩
 * 더 내리면, 층이 늘어나는 것이 아니라 맨 위가 홀로 커진다.
 *
 * 색을 비워 두지 않는 것이 규칙이다. 비우면 놓인 자리의 콘텐츠 색을 따르는데, 그러면 같은 역할이
 * 자리마다 다르게 렌더된다. 실제로 그랬다. [itemName]이 Card 안에서 `onSurfaceVariant`로, 밖에서
 * `onSurface`로 나왔다. Material 3의 Card가 콘텐츠 색으로 `onSurfaceVariant`를 주기 때문이고 아무도
 * 의도한 적이 없다. 그래서 명시적으로 `onSurface`를 쓰는 [identifier]가 같은 카드의 제목보다
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
     * 진한 잉크다. 이름은 [identifier]나 [supporting]보다 약해질 수 없다.
     */
    val itemName: TextStyle
        @Composable get() =
            MaterialTheme.typography.titleMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /** 목록이 비었을 때 남은 공간 가운데 서는 안내. 화면에 혼자 있는 문장이라 값들보다 크게 둔다. */
    val guidance: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyLarge
                .copy(color = MaterialTheme.colorScheme.onSurfaceVariant)
                .hugged

    /**
     * 이름표가 가리키는 내용과, 지금 이 항목이 어떤지를 말하는 한 줄. 세션 정보의 값, 상세의 전송 상태.
     *
     * 이름([itemName])보다 한 단계 작다. 같은 크기이면 이름이 목록의 첫 항목처럼 읽히고 큰 글자가
     * 사다리처럼 쌓인다. 이름표인 [supporting]과는 크기가 아니라 잉크로 갈린다.
     *
     * 전송 상태가 여기 드는 것은 그것이 이름에 딸린 값이 아니라 지금 무엇을 할 수 있는지를 말하기
     * 때문이다. 옅게 두지 않는 이유가 그것이고, 크기까지 올릴 이유는 아니었다. 한 단계 큰 조합을
     * 그 한 줄만 쓰던 동안, 상세에서 그 줄만 위아래와 다른 글자로 보였다.
     */
    val value: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = MaterialTheme.colorScheme.onSurface)
                .hugged

    /**
     * 이름에 딸려 그것을 설명하는 값과 이름표. 카드의 Object와 전송 상태, 상세의 Task·Object·짧은
     * ID, 세션 정보의 이름표, 세션 개수, 실패 사유.
     *
     * 이름과는 크기와 굵기로, 같은 크기인 [value]·[identifier]와는 잉크로 갈린다.
     */
    val supporting: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(color = MaterialTheme.colorScheme.onSurfaceVariant)
                .hugged

    /**
     * 기계가 부르는 이름. 목록 카드 오른쪽 끝의 짧은 Session 식별자.
     *
     * 이 앱은 배포용이 아니라 수집용이고, 서버에 올라간 수집분을 찾을 때 쓰는 것은 수집 일시가
     * 아니라 이 값이다. 그래서 색은 옅게 하지 않고 굵기를 한 단계 올린다. GitHub의 커밋 목록도 짧은
     * SHA의 색을 본문과 같게, 굵기를 주변 작은 글자보다 한 단계 굵게 둔다.
     *
     * 크기는 [supporting]과 같다. 전에는 한 단계 더 낮춰 카드가 크기 셋을 썼는데, 그러면 이름과의
     * 차이가 1.33배로 벌어져 이름만 과하게 커 보였다. 같은 GitHub의 커밋 행이 조합 셋을 쓰면서도
     * 글꼴은 하나, 크기는 둘로 끝내는 것이 이 이유다. 값이 여럿이면 크기를 늘리는 대신 굵기와
     * 잉크로 가른다.
     *
     * 고정폭을 쓰지 않는다. 글자 단위 대조에는 고정폭이 낫지만 한 화면에 글꼴이 둘이면 그 이득보다
     * 위계를 가리는 손해가 크다.
     */
    val identifier: TextStyle
        @Composable get() =
            MaterialTheme.typography.bodyMedium
                .copy(
                    fontWeight = FontWeight.Medium,
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
