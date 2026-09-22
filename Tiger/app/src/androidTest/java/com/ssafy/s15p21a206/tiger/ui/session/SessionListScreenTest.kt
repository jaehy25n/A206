package com.ssafy.s15p21a206.tiger.ui.session

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.string
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.text.DateFormat
import java.util.Date

class SessionListScreenTest {
    @get:Rule val composeRule = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun emptyListShowsStartCaptureAction() {
        var startRequests = 0

        composeRule.setContent {
            SessionListScreen(emptyList(), onStartCapture = { startRequests += 1 }, onOpenTask = {})
        }

        composeRule.onNodeWithText(string(R.string.session_list_empty)).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_list_new_capture)).performClick()
        assertEquals(1, startRequests)
    }

    @Test
    fun taskSelectionOpensItsSessionList() {
        var selectedTask: String? = null

        composeRule.setContent {
            SessionListScreen(listOf(summary()), onStartCapture = {}, onOpenTask = { selectedTask = it })
        }

        composeRule.onNodeWithContentDescription("Door opening").performClick()
        assertEquals("Door opening", selectedTask)
    }

    @Test
    fun sessionSummaryShowsDetailsAndOpensDetail() {
        val summary = summary()
        var selectedSessionId: String? = null
        val captureTime = DateFormat.getDateTimeInstance().format(Date(summary.recordingStartEpochMs))
        val sessionLabel = string(R.string.session_list_item_content_description, captureTime)

        composeRule.setContent {
            TaskSessionListScreen(
                taskName = summary.taskName,
                sessions = listOf(summary),
                onBack = {},
                onOpenSession = { selectedSessionId = it },
                onDeleteSession = {},
                onStartCapture = {},
            )
        }

        // 값마다 제 자리가 있다. 종류가 다른 값을 한 줄에 부호로 이어 붙이지 않는다.
        composeRule.onNodeWithText(string(R.string.session_list_episode_count, 2)).assertIsDisplayed()
        // 서버에 올라간 영상을 찾을 때 쓰는 값이라 첫 행의 오른쪽 끝에 둔다.
        composeRule.onNodeWithText(string(R.string.session_list_short_id, "session-")).assertIsDisplayed()
        // 한 Task 안의 세션을 갈라 주는 유일한 이름이다. 시각만으로는 어느 물체를 찍은 것인지 모른다.
        composeRule.onNodeWithText(string(R.string.session_object, "cup")).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.upload_failed)).assertIsDisplayed()
        composeRule.onNodeWithContentDescription(sessionLabel).performClick()
        assertEquals(summary.sessionId, selectedSessionId)
    }

    /**
     * 두 이름을 Session 행에 저장하기 전에 마감된 세션은 Object가 비어 있다. 값이 없는 줄을
     * "Object" 한 마디로 세워 두면 없는 것을 있는 것처럼 읽히므로 줄째로 뺀다.
     */
    @Test
    fun aSessionWithoutAnObjectShowsNoObjectLine() {
        val summary = summary().copy(objectName = "")
        val captureTime = DateFormat.getDateTimeInstance().format(Date(summary.recordingStartEpochMs))

        composeRule.setContent {
            TaskSessionListScreen(
                taskName = summary.taskName,
                sessions = listOf(summary),
                onBack = {},
                onOpenSession = {},
                onDeleteSession = {},
                onStartCapture = {},
            )
        }

        composeRule.onNodeWithContentDescription(string(R.string.session_list_item_content_description, captureTime)).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_object, "")).assertDoesNotExist()
    }

    /** 삭제는 카드에 표를 두지 않고 길게 누르기에 숨긴다. 확인을 거치지 않으면 지워지지 않는다. */
    @Test
    fun longPressDeletesASessionOnlyAfterConfirmation() {
        val summary = summary()
        var deletedSessionId: String? = null
        val captureTime = DateFormat.getDateTimeInstance().format(Date(summary.recordingStartEpochMs))
        val sessionLabel = string(R.string.session_list_item_content_description, captureTime)

        composeRule.setContent {
            TaskSessionListScreen(
                taskName = summary.taskName,
                sessions = listOf(summary),
                onBack = {},
                onOpenSession = {},
                onDeleteSession = { deletedSessionId = it },
                onStartCapture = {},
            )
        }

        composeRule.onNodeWithContentDescription(sessionLabel).performTouchInput { longClick() }
        composeRule.onNodeWithText(string(R.string.session_delete)).performClick()
        // 확인 판이 뜨고, 취소하면 아무것도 지워지지 않는다.
        composeRule.onNodeWithText(string(R.string.session_delete_message_only_copy)).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.action_cancel)).performClick()
        assertEquals(null, deletedSessionId)

        composeRule.onNodeWithContentDescription(sessionLabel).performTouchInput { longClick() }
        composeRule.onNodeWithText(string(R.string.session_delete)).performClick()
        composeRule.onNodeWithText(string(R.string.action_delete)).performClick()
        assertEquals(summary.sessionId, deletedSessionId)
    }

    /** 업로드가 번들을 읽고 있는 동안은 지울 수 없다. */
    @Test
    fun longPressOnAnUploadingSessionOffersNoEnabledDeleteAction() {
        val summary = summary().copy(uploadState = UploadState.UPLOADING)
        val captureTime = DateFormat.getDateTimeInstance().format(Date(summary.recordingStartEpochMs))
        val sessionLabel = string(R.string.session_list_item_content_description, captureTime)

        composeRule.setContent {
            TaskSessionListScreen(
                taskName = summary.taskName,
                sessions = listOf(summary),
                onBack = {},
                onOpenSession = {},
                onDeleteSession = {},
                onStartCapture = {},
            )
        }

        composeRule.onNodeWithContentDescription(sessionLabel).performTouchInput { longClick() }
        composeRule.onNodeWithText(string(R.string.session_delete)).assertIsNotEnabled()
    }

    /**
     * 마지막 세션을 지우면 닿게 되는 화면이다. 삭제를 붙이기 전에는 세션이 있는 Task만 홈에
     * 나타나 도달할 수 없었다.
     */
    @Test
    fun anEmptyTaskSessionListExplainsHowToAddOne() {
        composeRule.setContent {
            TaskSessionListScreen(
                taskName = "Door opening",
                sessions = emptyList(),
                onBack = {},
                onOpenSession = {},
                onDeleteSession = {},
                onStartCapture = {},
            )
        }

        composeRule.onNodeWithText(string(R.string.task_session_list_empty)).assertIsDisplayed()
        // 비어 있을 때는 바로 아래 안내가 같은 말을 하므로 개수를 세지 않는다.
        composeRule.onNodeWithText(string(R.string.session_list_count, 0)).assertDoesNotExist()
    }

    private fun summary() =
        SessionSummary(
            sessionId = "session-12345678",
            displayNumber = 1,
            uploadState = UploadState.FAILED,
            recordingStartEpochMs = 0L,
            recordingStartMonotonicTimestampNs = 1L,
            recordingEndMonotonicTimestampNs = 2L,
            bundlePath = "/managed/session-12345678",
            completedEpisodeCount = 2,
            taskName = "Door opening",
            objectName = "cup",
        )
}
