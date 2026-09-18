package com.ssafy.s15p21a206.tiger.ui.theme

import androidx.compose.ui.graphics.Color

val Purple80 = Color(0xFFD0BCFF)
val PurpleGrey80 = Color(0xFFCCC2DC)
val Pink80 = Color(0xFFEFB8C8)

val Purple40 = Color(0xFF6650a4)
val PurpleGrey40 = Color(0xFF625b71)
val Pink40 = Color(0xFF7D5260)

/** 수집·작업 구간 시작을 알리는 강조색. 프리뷰 위 어두운 스크림에서도 읽히도록 밝게 잡았다. */
val CaptureStart = Color(0xFF69F0AE)

/** Session 종료처럼 되돌릴 수 없는 동작에 쓰는 붉은색. 같은 자리의 다른 버튼과 구분되어야 한다. */
val CaptureDestructive = Color(0xFFFF5252)

/**
 * 프리뷰 위 오버레이의 배경. 뒤에 무엇이 오든 같은 밝기로 읽혀야 하므로 순검정이 아니라
 * 중성 회색을 거의 불투명하게 깐다. 반투명 검정은 레터박스의 검은 띠 위에서 사라져
 * 배지가 잘린 것처럼 보였다.
 */
val CaptureOverlayScrim = Color(0xF23A3A3C)

/**
 * 화면 전체를 덮는 판의 배경.
 *
 * [CaptureOverlayScrim]은 배지 하나만큼의 좁은 면적을 채우는 색이라 거의 불투명하다. 같은 값으로
 * 화면 전체를 덮으면 프리뷰가 사라져, 무엇을 찍다가 멈춘 것인지 알 수 없게 된다. 글자가 읽히는
 * 선까지만 어둡게 깔고 뒤가 비치게 둔다.
 */
val CaptureFullScreenScrim = Color(0x99000000)

/**
 * 화면을 덮는 판 위 보조 문구의 색.
 *
 * 뒤가 카메라 프리뷰라 배경 밝기가 장면마다 달라진다. 가장 불리한 흰 장면에서도 읽혀야 하므로
 * 스크림 위 명도 대비를 기준으로 정했다. 90% 흰색은 그 장면에서 5.0:1로 WCAG AA(4.5:1)를 넘고,
 * 80%로 내리면 4.4:1이 되어 걸린다. 비활성 컨트롤에 쓰는 38% 흰색은 2.2:1까지 떨어진다.
 */
val CaptureOverlaySupporting = Color(0xE6FFFFFF)

/** 비활성 제어의 색. 의미색을 흐리기만 하면 여전히 그 색으로 읽히므로 색상을 빼고 중성으로 떨어뜨린다. */
val CaptureControlDisabled = Color(0x61FFFFFF)
