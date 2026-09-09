package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionSummary

@Suppress("FunctionName")
@Composable
fun SessionListScreen(
    sessions: List<SessionSummary>,
    onStartCapture: () -> Unit,
    onOpenTask: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val unknownTask = stringResource(R.string.task_name_unknown)
    val taskGroups = sessions.groupBy { it.taskName.trim() }.toSortedMap()
    Column(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(stringResource(R.string.task_list_title))
        Button(onClick = onStartCapture) {
            Text(stringResource(R.string.session_list_new_capture))
        }
        if (taskGroups.isEmpty()) {
            Text(stringResource(R.string.session_list_empty))
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(taskGroups.entries.toList(), key = { it.key }) { (taskName, taskSessions) ->
                    val label = taskName.ifBlank { unknownTask }
                    TaskSummaryItem(label, taskSessions.size) { onOpenTask(taskName) }
                }
            }
        }
    }
}

@Composable
@Suppress("FunctionName")
fun TaskSessionListScreen(
    taskName: String,
    sessions: List<SessionSummary>,
    onBack: () -> Unit,
    onOpenSession: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val title = taskName.ifBlank { stringResource(R.string.task_name_unknown) }
    Column(modifier = modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(
                    painter = painterResource(R.drawable.ic_navigation_back),
                    contentDescription = stringResource(R.string.navigation_back),
                )
            }
            Text(title)
        }
        LazyColumn(
            modifier = Modifier.padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(sessions, key = SessionSummary::sessionId) { summary ->
                SessionSummaryItem(summary, onOpenSession)
            }
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun TaskSummaryItem(
    taskName: String,
    sessionCount: Int,
    onOpenTask: () -> Unit,
) {
    Card(
        modifier =
            Modifier
                .fillMaxWidth()
                .semantics { contentDescription = taskName }
                .clickable(role = Role.Button, onClick = onOpenTask),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(taskName)
            Text(stringResource(R.string.task_list_session_count, sessionCount))
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun SessionSummaryItem(
    summary: SessionSummary,
    onOpenSession: (String) -> Unit,
) {
    val captureTime =
        java.text.DateFormat
            .getDateTimeInstance()
            .format(java.util.Date(summary.recordingStartEpochMs))
    val sessionLabel = stringResource(R.string.session_list_capture_time, captureTime)
    Card(
        modifier =
            Modifier
                .fillMaxWidth()
                .semantics { contentDescription = sessionLabel }
                .clickable(role = Role.Button) { onOpenSession(summary.sessionId) },
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(sessionLabel)
            Text(stringResource(R.string.session_list_short_id, summary.sessionId.take(8)))
            Text(stringResource(R.string.session_list_episode_count, summary.completedEpisodeCount))
            Text(stringResource(uploadStateLabel(summary.uploadState)))
        }
    }
}

private fun uploadStateLabel(state: com.ssafy.s15p21a206.tiger.episode.UploadState): Int =
    when (state) {
        com.ssafy.s15p21a206.tiger.episode.UploadState.LOCAL_ONLY -> R.string.upload_local_only
        com.ssafy.s15p21a206.tiger.episode.UploadState.UPLOADING -> R.string.upload_in_progress
        com.ssafy.s15p21a206.tiger.episode.UploadState.UPLOADED -> R.string.upload_completed
        com.ssafy.s15p21a206.tiger.episode.UploadState.FAILED -> R.string.upload_failed
    }
