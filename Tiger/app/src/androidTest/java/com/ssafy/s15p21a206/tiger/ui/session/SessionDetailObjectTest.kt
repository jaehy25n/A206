package com.ssafy.s15p21a206.tiger.ui.session

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.string
import com.ssafy.s15p21a206.tiger.ui.video.rememberSharedVideoPlayer
import org.junit.Rule
import org.junit.Test

/**
 * 수집 대상 물체를 확인하는 자리.
 *
 * 본문에 두는 이유는 수집을 마감한 직후 경로다. 그때는 Task 묶음도 세션 카드도 지나오지 않고
 * 이 화면으로 바로 오므로, Task와 Object가 화면에 한 번도 나온 적이 없다. 방금 찍은 것이 맞는지
 * 확인하는 자리에서 메뉴를 한 번 더 열게 할 수 없다.
 */
class SessionDetailObjectTest {
    @get:Rule val composeRule = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun sessionDetailNamesTheTaskAndObjectThatWereCaptured() {
        showDetail(summary())

        // 메뉴를 열지 않고 본문에서 바로 읽힌다. 둘은 같은 종류라 같은 층에 쌓는다. 한 줄에 몰면
        // 무엇으로 이어도 어색해지므로 잇지 않는다.
        composeRule.onNodeWithText(string(R.string.session_task, "mvi-check")).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_object, "cup")).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_list_short_id, "ce9c7947")).assertIsDisplayed()
    }

    /** 이름이 하나뿐이면 그것만 적는다. 없는 쪽의 이름표를 빈 채로 세우지 않는다. */
    @Test
    fun sessionDetailNamesOnlyWhatItHas() {
        showDetail(summary().copy(objectName = ""))

        composeRule.onNodeWithText(string(R.string.session_task, "mvi-check")).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_object, "")).assertDoesNotExist()
    }

    /** 두 이름이 다 없는 세션. 두 줄이 빠지고 식별자는 그대로 남는다. */
    @Test
    fun sessionDetailDropsBothNameLinesWhenThereAreNone() {
        showDetail(summary().copy(taskName = "", objectName = ""))

        composeRule.onNodeWithText(string(R.string.session_object, "")).assertDoesNotExist()
        composeRule.onNodeWithText(string(R.string.session_task, "")).assertDoesNotExist()
        composeRule.onNodeWithText(string(R.string.session_list_short_id, "ce9c7947")).assertIsDisplayed()
    }

    /**
     * 세션 정보는 세션을 특정해 주지 않는 값의 자리다. 두 이름은 고를 때 쓰는 값이라 여기 두지
     * 않는다. 본문에 있는 것을 한 탭 뒤에 한 번 더 두면 같은 말을 두 곳에서 하게 된다.
     */
    @Test
    fun sessionInfoLeavesTheNamesToTheBody() {
        showDetail(summary())

        composeRule.onNodeWithContentDescription(string(R.string.session_detail_more_actions)).performClick()
        composeRule.onNodeWithText(string(R.string.session_info_title)).performClick()

        composeRule.onNodeWithText(string(R.string.session_info_episodes)).assertIsDisplayed()
        // 본문의 한 곳에만 있다.
        composeRule.onAllNodesWithText(string(R.string.session_task, "mvi-check")).assertCountEquals(1)
        composeRule.onAllNodesWithText(string(R.string.session_object, "cup")).assertCountEquals(1)
    }

    private fun showDetail(summary: SessionSummary) {
        composeRule.setContent {
            SessionDetailScreen(
                summary = summary,
                onBack = {},
                onUpload = {},
                onDelete = {},
                deleteFailureReason = null,
                uploadFailureReason = null,
                sharedPlayer = rememberSharedVideoPlayer(),
                onOpenFullscreenVideo = {},
            )
        }
    }

    // 번들에 영상이 없으므로 재생 영역 대신 안내 문구가 놓인다. 이 테스트가 보는 것은 본문이다.
    private fun summary() =
        SessionSummary(
            sessionId = "ce9c7947-0000-0000-0000-000000000000",
            displayNumber = 1,
            uploadState = UploadState.LOCAL_ONLY,
            recordingStartEpochMs = 0L,
            recordingStartMonotonicTimestampNs = 1L,
            recordingEndMonotonicTimestampNs = 1_000_000_001L,
            bundlePath = "/bundles/ce9c7947",
            completedEpisodeCount = 0,
            taskName = "mvi-check",
            objectName = "cup",
        )
}
