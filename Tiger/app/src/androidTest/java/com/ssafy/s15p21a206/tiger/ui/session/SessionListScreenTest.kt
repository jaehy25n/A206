package com.ssafy.s15p21a206.tiger.ui.session

import androidx.activity.ComponentActivity
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.getBoundsInRoot
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

        // 메타 둘은 왼쪽에 세로로 쌓여 서로 붙는다. 값을 부호로 이어 붙이지 않고, 묶이는 것은 서로의
        // 바로 아래위에 있다는 사실이 말한다. 이름표 낱말은 적지 않고, 무엇이 값이고
        // 무엇이 기계 이름인지는 잉크의 단계와 `#`가 가른다.
        composeRule.onNodeWithText("cup").assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_short_id_tag, "session-")).assertIsDisplayed()
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
        // 값이 없으면 줄째로 뺀다. 이름표 낱말을 적지 않으므로 빈 줄이 남을 자리도 없다.
        composeRule.onNodeWithText("cup").assertDoesNotExist()
        composeRule.onNodeWithText(string(R.string.session_short_id_tag, "session-")).assertIsDisplayed()
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

    /**
     * 홈은 헤더가 없고 Task의 Session 목록은 헤더를 얹는다. 두 이름표가 같은 높이에서 시작해야
     * 화면을 오갈 때 글자가 제자리에 머무르는 것으로 보인다.
     *
     * 전에는 홈이 제목의 중심을 헤더 제목의 중심에 맞췄다. 헤더에 제목을 두는 화면이 없어 맞출
     * 상대가 없는 정렬이었고, 그동안 홈의 이름표만 50dp 위에 붙어 있었다.
     */
    @Test
    fun bothListScreensStartTheirSectionNameAtTheSameHeight() {
        var showHome by mutableStateOf(true)
        val summary = summary()

        composeRule.setContent {
            if (showHome) {
                SessionListScreen(listOf(summary), onStartCapture = {}, onOpenTask = {})
            } else {
                TaskSessionListScreen(
                    taskName = summary.taskName,
                    sessions = listOf(summary),
                    onBack = {},
                    onOpenSession = {},
                    onDeleteSession = {},
                    onStartCapture = {},
                )
            }
        }

        val homeTop = composeRule.onNodeWithText(string(R.string.session_list_title)).getBoundsInRoot().top
        showHome = false
        composeRule.waitForIdle()
        val taskTop = composeRule.onNodeWithText(summary.taskName).getBoundsInRoot().top

        assertEquals(homeTop.value.toDouble(), taskTop.value.toDouble(), 0.5)
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
