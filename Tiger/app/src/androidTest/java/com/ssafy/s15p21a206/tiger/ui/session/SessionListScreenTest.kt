package com.ssafy.s15p21a206.tiger.ui.session

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
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
                onStartCapture = {},
            )
        }

        composeRule.onNodeWithText(string(R.string.session_list_short_id, "session-")).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.session_list_episode_count, 2)).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.upload_failed)).assertIsDisplayed()
        composeRule.onNodeWithContentDescription(sessionLabel).performClick()
        assertEquals(summary.sessionId, selectedSessionId)
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
        )
}
