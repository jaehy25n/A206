package com.ssafy.s15p21a206.tiger.ui.upload

import androidx.activity.OnBackPressedDispatcher
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * 업로드 상태 화면의 `BackHandler`가 `NavHost`의 백스택 pop보다 우선하는지 확인한다.
 *
 * 화면 전환을 Navigation Compose로 옮기면서(S15P21A206-40) 이 화면의 뒤로 가기는 두 처리기와
 * 경쟁하게 됐다. 목적지 안의 `BackHandler`가 이기지 않으면 업로드 중 뒤로 가기가 취소 확인을
 * 건너뛰고 곧바로 이전 화면으로 돌아가, `capture-control-ui.md`의 업로드 이탈 계약이 깨진다.
 *
 * 이 테스트는 그 프레임워크 동작만 고정한다. `MainActivity`의 배선 자체를 검증하지는 않으므로,
 * 실기기에서 실제 전송 중 뒤로 가기를 눌러 보는 확인을 대신하지 않는다.
 */
class UploadStatusBackNavigationTest {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun uploading_back_press_confirms_instead_of_leaving_the_destination() {
        val host = setUpHost(UploadState.UPLOADING)
        openUploadStatus()

        composeRule.runOnIdle { host.dispatcher.onBackPressed() }

        composeRule.onNodeWithText("업로드를 중단할까요?").assertIsDisplayed()
        composeRule.onNodeWithText(DETAIL_MARKER).assertDoesNotExist()
        assertEquals(0, host.cancellations)
    }

    @Test
    fun confirming_cancellation_cancels_the_upload_and_returns_to_the_previous_destination() {
        val host = setUpHost(UploadState.UPLOADING)
        openUploadStatus()
        composeRule.runOnIdle { host.dispatcher.onBackPressed() }

        composeRule.onNodeWithText("업로드 중단").performClick()

        assertEquals(1, host.cancellations)
        composeRule.onNodeWithText(DETAIL_MARKER).assertIsDisplayed()
    }

    @Test
    fun terminal_state_back_press_returns_without_confirmation() {
        val host = setUpHost(UploadState.FAILED)
        openUploadStatus()

        composeRule.runOnIdle { host.dispatcher.onBackPressed() }

        composeRule.onNodeWithText(DETAIL_MARKER).assertIsDisplayed()
        assertEquals(0, host.cancellations)
    }

    private fun openUploadStatus() {
        composeRule.onNodeWithText(OPEN_UPLOAD_STATUS).performClick()
        composeRule.onNodeWithText("업로드 상태").assertIsDisplayed()
    }

    private fun setUpHost(uploadState: UploadState): HostHandle {
        val handle = HostHandle()
        composeRule.setContent {
            handle.dispatcher = LocalOnBackPressedDispatcherOwner.current!!.onBackPressedDispatcher
            TigerTheme {
                TestNavHost(uploadState) { handle.cancellations++ }
            }
        }
        return handle
    }

    private class HostHandle {
        lateinit var dispatcher: OnBackPressedDispatcher
        var cancellations = 0
    }
}

private const val DETAIL_MARKER = "session-detail-destination"
private const val OPEN_UPLOAD_STATUS = "open-upload-status"

/**
 * production과 같은 배치를 만든다. 업로드 상태를 다른 목적지 위에 쌓아, pop할 곳이 있는 상태에서
 * 뒤로 가기를 받게 한다. 전환 애니메이션은 `MainActivity`와 같이 끈다.
 */
@Suppress("FunctionName")
@Composable
private fun TestNavHost(
    uploadState: UploadState,
    onCancelUpload: () -> Unit,
) {
    val navController = rememberNavController()
    NavHost(
        navController = navController,
        startDestination = "detail",
        enterTransition = { EnterTransition.None },
        exitTransition = { ExitTransition.None },
        popEnterTransition = { EnterTransition.None },
        popExitTransition = { ExitTransition.None },
    ) {
        composable("detail") {
            Column {
                Text(DETAIL_MARKER)
                Button(onClick = { navController.navigate("uploadStatus") }) { Text(OPEN_UPLOAD_STATUS) }
            }
        }
        composable("uploadStatus") {
            UploadStatusScreen(
                uploadState = uploadState,
                onBack = { navController.popBackStack() },
                onCancelUpload = {
                    onCancelUpload()
                    navController.popBackStack()
                },
            )
        }
    }
}
