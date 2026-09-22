package com.ssafy.s15p21a206.tiger.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
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
 * 색을 지정하지 않는 역할이 있다. 그런 역할은 놓인 자리의 콘텐츠 색을 그대로 따른다. 이것이
 * Compose의 기본 방식이지만, 자리에 따라 같은 역할이 다르게 보일 수 있다는 뜻이기도 하다. 실제로
 * [itemName]은 Card 안에서 `onSurfaceVariant`로, 밖에서 `onSurface`로 렌더된다. Material 3의 Card가
 * 콘텐츠 색으로 `onSurfaceVariant`를 주기 때문이며 아무도 의도한 적이 없다. 이 역할 집합은 지금
 * 렌더를 이름 아래로 옮긴 것이므로 그 어긋남도 그대로 옮겨져 있다.
 */
object TigerText {
    /** 한 묶음을 이끄는 이름. 홈의 `Tasks`, Task Session 목록의 Task 이름이 여기 해당한다. */
    val sectionName: TextStyle
        @Composable get() = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)

    /**
     * 한 항목 또는 한 화면의 이름. 카드의 Task 이름과 수집 일시, 화면 헤더 제목, 세션 정보 제목.
     *
     * 색을 지정하지 않아 자리의 색을 따른다. Card 안에서는 옅게, 밖에서는 진하게 나온다.
     */
    val itemName: TextStyle
        @Composable get() = MaterialTheme.typography.titleMedium

    /** 문장으로 읽는 글. 상세의 전송 상태처럼 그 자리에서 무엇을 할 수 있는지 말하는 한 줄. */
    val body: TextStyle
        @Composable get() = MaterialTheme.typography.bodyLarge

    /** 목록이 비었을 때 남은 공간 가운데 서는 안내. 본문과 크기는 같고 색을 낮춰 둔다. */
    val guidance: TextStyle
        @Composable get() = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurfaceVariant)

    /**
     * 이름표가 가리키는 내용. 세션 정보의 값이 여기 해당한다.
     *
     * 시트 제목([itemName])보다 한 단계 작다. 같은 크기이면 제목이 목록의 첫 항목처럼 읽히고 큰
     * 글자가 사다리처럼 쌓인다. [meta]인 이름표와는 크기 한 단계와 색으로 갈린다.
     */
    val value: TextStyle
        @Composable get() = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface)

    /**
     * 이름에 딸려 그것을 설명하는 값. 카드의 Object, 상세의 Task·Object·짧은 ID, 세션 개수,
     * 실패 사유.
     *
     * 이름과는 크기와 굵기로, [meta]와는 크기와 색으로 갈린다. 층의 경계마다 두 가지가 함께 바뀐다.
     * 2sp 안팎의 크기 차이만으로는 의도한 단계로 읽히지 않는다.
     */
    val supporting: TextStyle
        @Composable get() = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurfaceVariant)

    /**
     * 기계가 부르는 이름. 목록 카드 오른쪽 끝의 짧은 Session 식별자.
     *
     * 이 앱은 배포용이 아니라 수집용이고, 서버에 올라간 수집분을 찾을 때 쓰는 것은 수집 일시가
     * 아니라 이 값이다. 그래서 크기는 가장 낮추되 색은 옅게 하지 않는다. GitHub의 커밋 목록도 짧은
     * SHA를 12px로 두면서 색은 본문과 같게, 굵기는 주변 작은 글자보다 한 단계 굵게 둔다.
     *
     * 고정폭을 쓰지 않는다. 글자 단위 대조에는 고정폭이 낫지만 한 화면에 글꼴이 둘이면 그 이득보다
     * 위계를 가리는 손해가 크다.
     */
    val identifier: TextStyle
        @Composable get() = MaterialTheme.typography.labelMedium.copy(color = MaterialTheme.colorScheme.onSurface)

    /**
     * 항목을 특정해 주지 않는 곁가지와 이름표. 카드의 전송 상태, 세션 정보의 이름표.
     *
     * 무엇을 찍은 것인지 알려 주지 않는 값의 자리다. [supporting]보다 한 단계 더 내린다.
     */
    val meta: TextStyle
        @Composable get() = MaterialTheme.typography.bodySmall.copy(color = MaterialTheme.colorScheme.onSurfaceVariant)

    /** 입력 모달에서 한 무리의 입력을 이끄는 이름표. */
    val formLabel: TextStyle
        @Composable get() = MaterialTheme.typography.labelLarge

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
