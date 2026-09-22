package com.ssafy.s15p21a206.tiger.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme =
    darkColorScheme(
        primary = Purple80,
        secondary = PurpleGrey80,
        tertiary = Pink80,
    )

private val LightColorScheme =
    lightColorScheme(
        primary = Purple40,
        secondary = PurpleGrey40,
        tertiary = Pink40,
    /* Other default colors to override
    background = Color(0xFFFFFBFE),
    surface = Color(0xFFFFFBFE),
    onPrimary = Color.White,
    onSecondary = Color.White,
    onTertiary = Color.White,
    onBackground = Color(0xFF1C1B1F),
    onSurface = Color(0xFF1C1B1F),
     */
    )

@Suppress("FunctionName")
@Composable
fun TigerTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // Dynamic color is available on Android 12+
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colorScheme =
        when {
            dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
                val context = LocalContext.current
                if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
            }

            darkTheme -> DarkColorScheme
            else -> LightColorScheme
        }

    MaterialTheme(
        colorScheme = if (darkTheme) colorScheme else colorScheme.withFixedNeutrals(),
        typography = Typography,
        content = content,
    )
}

/**
 * 중성 계열만 앱이 고정한다. 강조색은 배경화면에서 받아 온 것을 그대로 둔다.
 *
 * `dynamicColor`가 켜져 있으면 M3의 중성 팔레트도 배경화면에서 색조를 조금 받는다. `SM-G973N`에서
 * 잰 목록 바닥은 `#E8EFF6`으로, 파랑이 빨강보다 14 높은 푸른 회색이었다. 회색으로 보이라고 깐 바닥이
 * 기기 배경화면마다 다른 색을 띤다. Android 12는 13 이후보다 중성 채도가 높아 OS 버전에 따라서도
 * 달라진다.
 *
 * 화면의 대부분을 차지하는 것이 이 판과 그 위 글자이므로, 앱이 어떻게 보이는지를 배경화면에 맡기는
 * 셈이 된다. 반대로 강조색은 면적이 좁고 그 자리에서 "이것이 주 동작"이라는 말만 하면 되므로
 * 배경화면을 따라가도 잃는 것이 없다. 그래서 중성만 고정한다.
 *
 * 어두운 테마는 이번 범위가 아니다(2026-09-22). 손대지 않은 채로 둔다.
 */
private fun ColorScheme.withFixedNeutrals(): ColorScheme =
    copy(
        background = SurfaceBase,
        onBackground = InkStrong,
        surface = SurfaceBase,
        onSurface = InkStrong,
        surfaceVariant = SurfaceSunken,
        onSurfaceVariant = InkMuted,
        surfaceBright = SurfaceRaised,
        surfaceDim = SurfaceSunken,
        surfaceContainerLowest = SurfaceRaised,
        surfaceContainerLow = SurfaceBase,
        surfaceContainer = SurfaceRecessed,
        surfaceContainerHigh = SurfaceSunken,
        surfaceContainerHighest = SurfaceDeep,
        outline = OutlineNeutral,
        outlineVariant = OutlineNeutralFaint,
    )
