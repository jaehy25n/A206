package com.ssafy.s15p21a206.tiger.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import com.ssafy.s15p21a206.tiger.R

/**
 * 이 앱이 쓰는 글꼴.
 *
 * 전에는 고른 적이 없었다. `FontFamily.Default`를 썼는데 그것이 무엇인지는 제조사가 정한다. Pixel에서
 * Roboto, One UI에서 삼성이 갈아 끼운 글꼴이다. 검증 기기가 `SM-G973N`이므로 그동안 본 화면은 삼성
 * 글꼴이었고, 다른 기기에서는 다른 글꼴이었다.
 *
 * 더 큰 문제는 한 화면에 글꼴이 둘이었다는 것이다. 라틴은 시스템 글꼴이 그리고 한글은 폴백 글꼴이
 * 그린다. 두 가족은 세로 메트릭과 광학 크기가 달라, 나란히 놓으면 한글만 커 보이고 줄이 어긋난
 * 것처럼 보인다. 코드 주석이 그 증상을 두 번 기록해 두었다. `E`나 `I`는 세로 획이 열을 꽉 채워 서지만
 * `업`의 ㅇ은 완만한 곡선이라 한글 줄만 들여쓴 것처럼 보인다는 것, 같은 14sp라도 한글이 em 상자를 꽉
 * 채워 라틴 글자보다 커 보인다는 것이다. 레이아웃으로 우회하던 그 문제를 글꼴 층에서 없앤다.
 *
 * ## 왜 Pretendard인가
 *
 * 한 가족이 라틴과 한글을 같은 메트릭으로 덮는다. 라틴은 Inter에서 왔고 Inter의 설계 목적이 정확히
 * "화면, 작은 크기 UI"다. 한글은 그 메트릭에 맞춰 그려졌다.
 *
 * 이 앱의 지배적인 타이포 표면이 라틴과 숫자라는 것도 이유다. 프리뷰 위 배지(`DATA COLLECTION
 * START`), 8자리 식별자, 타임스탬프, `1920×1080`이 그렇고 한글은 UI 부속이다. 그래서 작은 크기의
 * 라틴·숫자에 강한 가족을 고르고 한글이 그 메트릭을 따르게 한다.
 *
 * ## 무엇을 담았나
 *
 * 정적 OTF 세 가중치(Regular·Medium·Bold)다. 합쳐 4.7MB다. 가변 폰트 한 벌은 6.7MB라 더 크고, 쓰지
 * 않는 가중치까지 들고 다닌다.
 *
 * KS X 1001만 담은 `PretendardStd`는 954KB로 5배 작지만 쓰지 않는다. 그 바깥 음절이 나오면 그 글자만
 * 시스템 글꼴로 떨어지는데, 지금 없애려는 것이 바로 한 줄에 글꼴이 둘인 상태다. 드물게 나는 일이라도
 * 고치려는 문제가 그대로 돌아온다. APK 크기가 문제가 되면 그때 다시 본다.
 *
 * 라이선스는 SIL Open Font License 1.1이고 전문은 `app/licenses/Pretendard-OFL.txt`에 둔다.
 */
val Pretendard =
    FontFamily(
        Font(R.font.pretendard_regular, FontWeight.Normal),
        Font(R.font.pretendard_medium, FontWeight.Medium),
        Font(R.font.pretendard_bold, FontWeight.Bold),
    )

/**
 * 이 앱이 쓰는 타입 스케일.
 *
 * 화면이 고르는 것은 [TigerText]의 역할이지만, Material 3 컴포넌트는 그 역할을 모른다. `Button`은
 * `labelLarge`를, `AlertDialog`는 제목에 `headlineSmall`과 본문에 `bodyMedium`을, `DropdownMenuItem`은
 * `labelLarge`를, `TextField`의 이름표는 `bodyLarge`를 제 안에서 집어 쓴다. 그래서 여기서 스케일과
 * 글꼴을 정해 두지 않으면 앱이 고른 것과 컴포넌트가 고른 것이 따로 논다.
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
 * | callout | 14sp | 목록의 값, 컨트롤의 글자. `bodyMedium`·`titleSmall`·`labelLarge` (subhead 15) |
 * | caption | 12sp | 묶음 이름표. `labelMedium` (caption1 12) |
 *
 * 22 위는 비워 둔다. `display`와 `headline`은 한 화면에 제목이 여럿인 문서형 화면의 눈금이고, 이
 * 앱에는 그런 화면이 없다. `headlineSmall`만 `AlertDialog`가 집어 쓰므로 title 층으로 끌어내린다.
 *
 * 값은 M3 기본에서 글꼴·숫자 꼴과 `headlineSmall`의 크기만 손대고 줄 높이와 자간은 그대로 둔다. 줄상자의 남는
 * 여백은 [TigerText]가 역할마다 깎으므로 여기서 줄 높이를 줄일 이유가 없다.
 */
val Typography =
    Typography().let { m3 ->
        Typography(
            displayLarge = m3.displayLarge.inPretendard(),
            displayMedium = m3.displayMedium.inPretendard(),
            displaySmall = m3.displaySmall.inPretendard(),
            headlineLarge = m3.headlineLarge.inPretendard(),
            headlineMedium = m3.headlineMedium.inPretendard(),
            // AlertDialog의 제목이 이것을 집어 쓴다. 화면 제목보다 클 이유가 없다.
            headlineSmall = m3.headlineSmall.copy(fontSize = m3.titleLarge.fontSize).inPretendard(),
            titleLarge = m3.titleLarge.inPretendard(),
            titleMedium = m3.titleMedium.inPretendard(),
            titleSmall = m3.titleSmall.inPretendard(),
            bodyLarge = m3.bodyLarge.inPretendard(),
            bodyMedium = m3.bodyMedium.inPretendard(),
            bodySmall = m3.bodySmall.inPretendard(),
            labelLarge = m3.labelLarge.inPretendard(),
            labelMedium = m3.labelMedium.inPretendard(),
            labelSmall = m3.labelSmall.inPretendard(),
        )
    }

/**
 * 글꼴과 숫자 꼴을 함께 준다.
 *
 * 숫자는 고정폭(`tnum`)으로 둔다. 기본값인 비례 숫자는 글자마다 폭이 달라 `1`이 좁다. 한 줄로 읽는
 * 글에서는 그편이 고르지만, 이 앱의 숫자는 세로로 쌓인다. 목록 카드의 수집 일시가 카드마다 같은
 * 자리에서 시작하고, 세션 정보 시트의 값들도 기둥을 이룬다. 폭이 흔들리면 자릿수가 어긋나 보여 두
 * 시각을 견주기 어렵다.
 *
 * Pretendard가 Inter에서 물려받은 기능이고, 이 가족을 고른 이유 중 하나다. 한 곳에서 켜서 화면과
 * 컴포넌트가 같은 숫자 꼴을 쓰게 한다.
 */
private fun TextStyle.inPretendard(): TextStyle =
    copy(
        fontFamily = Pretendard,
        fontFeatureSettings = "tnum",
    )
