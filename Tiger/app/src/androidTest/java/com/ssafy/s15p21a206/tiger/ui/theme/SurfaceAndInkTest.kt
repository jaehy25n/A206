package com.ssafy.s15p21a206.tiger.ui.theme

import android.util.Log
import androidx.activity.ComponentActivity
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.text.TextStyle
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import kotlin.math.max
import kotlin.math.min

/**
 * 판과 잉크가 서로에 대해 지켜야 하는 관계를 검사한다.
 *
 * 값이 아니라 관계를 검사한다. 지금은 중성 계열을 `TigerTheme`이 고정하므로 값을 박아도 맞겠지만,
 * 그렇게 하면 검사가 "이 상수가 이 상수인가"를 묻는 것이 되어 아무것도 지키지 못한다. "카드가
 * 바닥보다 밝다", "이름이 식별자보다 약하지 않다", "모든 역할이 색을 갖는다"처럼 어느 팔레트에서나
 * 성립해야 하는 것을 검사해야, 나중에 팔레트를 손대거나 중성 고정을 되돌릴 때 이 검사가 잡는다.
 *
 * 실측값은 실패 메시지와 아래 [report]가 남긴다. 값을 문서에 옮겨 적는 대신 검사가 재도록 한다.
 */
class SurfaceAndInkTest {
    @get:Rule val composeRule = createAndroidComposeRule<ComponentActivity>()

    private class Palette(
        val listBackground: Color,
        val card: Color,
        val darkInk: Color,
        val lightInk: Color,
        val faintInk: Color,
        val surfaceRoles: Map<String, TextStyle>,
        val menuItem: TextStyle,
    )

    private fun palette(): Palette {
        lateinit var captured: Palette
        composeRule.setContent {
            // 밝은 테마만 검사한다. `dynamicColor`는 앱이 쓰는 그대로 두어 이 기기의 팔레트를 잰다.
            TigerTheme(darkTheme = false) {
                captured =
                    Palette(
                        listBackground = TigerSurface.listBackground,
                        card = TigerSurface.content,
                        darkInk = MaterialTheme.colorScheme.onSurface,
                        lightInk = MaterialTheme.colorScheme.onSurfaceVariant,
                        faintInk = InkFaint,
                        menuItem = TigerText.menuItem,
                        surfaceRoles =
                            mapOf(
                                "sectionName" to TigerText.sectionName,
                                "itemName" to TigerText.itemName,
                                "body" to TigerText.body,
                                "bodyMuted" to TigerText.bodyMuted,
                                "value" to TigerText.value,
                                "supporting" to TigerText.supporting,
                                "groupLabel" to TigerText.groupLabel,
                                "sectionCount" to TigerText.sectionCount,
                                "identifier" to TigerText.identifier,
                                "formLabel" to TigerText.formLabel,
                            ),
                    )
            }
        }
        composeRule.waitForIdle()
        // 실측값을 남긴다. 검사는 관계만 보지만, 이 기기에서 실제로 무엇이 나왔는지는 바꾼 뒤에
        // 재어 기록해야 한다. 문서에 숫자를 옮겨 적으면 다음 기기에서 거짓이 되므로 검사가 재게 둔다.
        //
        //   adb shell am instrument -w -e class \
        //     "com.ssafy.s15p21a206.tiger.ui.theme.SurfaceAndInkTest" \
        //     com.ssafy.s15p21a206.tiger.test/androidx.test.runner.AndroidJUnitRunner
        //   adb logcat -d -s TigerSurfaceAndInk
        Log.i(LOG_TAG, report(captured))
        captured.surfaceRoles.forEach { (name, style) ->
            Log.i(
                LOG_TAG,
                "$name ${hex(style.color)} 카드 위 ${ratio(style.color, captured.card)}:1, " +
                    "바닥 위 ${ratio(style.color, captured.listBackground)}:1",
            )
        }
        return captured
    }

    @Test
    fun aCardIsLighterThanTheListBackgroundBehindIt() {
        val palette = palette()

        assertTrue(
            "카드가 바닥보다 밝아야 한다. " + report(palette),
            palette.card.luminance() > palette.listBackground.luminance(),
        )
    }

    @Test
    fun everySurfaceRoleStatesItsOwnColor() {
        val palette = palette()

        val unstated = palette.surfaceRoles.filterValues { it.color == Color.Unspecified }
        assertTrue(
            "표면 위 역할은 색을 비워 두지 않는다. 비운 역할: ${unstated.keys}",
            unstated.isEmpty(),
        )
    }

    /**
     * 메뉴 항목만 색을 비운다. 규칙의 예외가 아니라 규칙의 다른 절반이다. 메뉴 항목의 색은 스타일이
     * 아니라 상태가 정하므로, 역할이 색을 박으면 컴포넌트의 판단을 덮는다.
     *
     * 실제로 덮었다. `onSurface`를 박아 둔 동안 삭제 항목의 글리프만 붉고 글자는 검었고, 비활성일 때
     * 흐려지지도 않았다. 눈으로는 글리프 색만 보고 넘기기 쉬워 검사로 못 박는다.
     */
    @Test
    fun aMenuItemLeavesItsColorToTheComponent() {
        val palette = palette()

        assertTrue(
            "메뉴 항목이 색을 박으면 error 색과 비활성 색을 덮는다. 박힌 색: ${hex(palette.menuItem.color)}",
            palette.menuItem.color == Color.Unspecified,
        )
    }

    @Test
    fun anItemNameIsNeverWeakerThanTheValuesBesideIt() {
        val palette = palette()
        val itemName = palette.surfaceRoles.getValue("itemName").color
        val supporting = palette.surfaceRoles.getValue("supporting").color

        // 위계 역전이 여기서 났다. Card가 콘텐츠 색으로 `onSurfaceVariant`를 주는 동안 카드 안
        // 이름만 옅어졌고, 색을 명시해 둔 값들이 같은 카드의 제목보다 진했다.
        assertTrue(
            "카드 안 이름이 딸린 값보다 약하다. " +
                "이름 ${hex(itemName)} ${ratio(itemName, palette.card)}:1, " +
                "딸린 값 ${hex(supporting)} ${ratio(supporting, palette.card)}:1",
            contrast(itemName, palette.card) >= contrast(supporting, palette.card),
        )
    }

    @Test
    fun everyInkMeetsAaOnBothSurfaces() {
        val palette = palette()
        val pairs =
            listOf(
                "진한 잉크 / 카드" to contrast(palette.darkInk, palette.card),
                "옅은 잉크 / 카드" to contrast(palette.lightInk, palette.card),
                "진한 잉크 / 바닥" to contrast(palette.darkInk, palette.listBackground),
                "옅은 잉크 / 바닥" to contrast(palette.lightInk, palette.listBackground),
                "가장 옅은 잉크 / 카드" to contrast(palette.faintInk, palette.card),
                "가장 옅은 잉크 / 바닥" to contrast(palette.faintInk, palette.listBackground),
            )

        val failing = pairs.filter { (_, ratio) -> ratio < AA_NORMAL_TEXT }
        assertTrue(
            "글자 대비가 WCAG AA(4.5:1)에 못 미치는 쌍이 있다. $failing. 전체: $pairs",
            failing.isEmpty(),
        )
    }

    /** 실패했을 때 무엇을 재서 그렇게 판정했는지 남긴다. */
    private fun report(palette: Palette): String =
        "바닥 ${hex(palette.listBackground)}, 카드 ${hex(palette.card)}, " +
            "채움 대비 ${ratio(palette.card, palette.listBackground)}:1"

    private fun hex(color: Color): String = "#%06X".format(color.toArgb() and 0xFFFFFF)

    /** 사람이 읽을 자리에 쓰는 대비값. */
    private fun ratio(
        one: Color,
        other: Color,
    ): String = "%.2f".format(contrast(one, other))

    /** WCAG 2.1의 명도 대비. [Color.luminance]가 이미 상대 휘도를 준다. */
    private fun contrast(
        one: Color,
        other: Color,
    ): Double {
        val a = one.luminance()
        val b = other.luminance()
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)
    }

    private companion object {
        const val AA_NORMAL_TEXT = 4.5
        const val LOG_TAG = "TigerSurfaceAndInk"
    }
}
