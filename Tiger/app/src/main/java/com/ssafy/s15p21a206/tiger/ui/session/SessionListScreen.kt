package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FloatingActionButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.ui.common.ListSectionHeader
import com.ssafy.s15p21a206.tiger.ui.common.MetaText
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeader
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeaderTitleCenter
import com.ssafy.s15p21a206.tiger.ui.common.SupportingText

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
    // 이 화면에는 헤더가 없다. Task를 열면 나오는 화면의 헤더 제목과 이름표가 같은 높이에
    // 놓여야 화면을 오갈 때 글자가 제자리에 머무르는 것으로 보인다. 글자 높이는 사용자가 고른
    // 글꼴 크기에 따라 달라지므로 값을 박지 않고 줄 높이에서 끌어낸다.
    val sectionTitleLineHeight = MaterialTheme.typography.titleLarge.lineHeight
    val sectionTopPadding =
        with(LocalDensity.current) {
            (NavigationHeaderTitleCenter - sectionTitleLineHeight.toDp() / 2).coerceAtLeast(0.dp)
        }
    Box(modifier = modifier.fillMaxSize()) {
        // 이름표를 목록 바깥에 두면 홀로 뜬 머리띠가 되고, FAB가 아래로 내려간 뒤로는 같은 줄에
        // 짝이 될 것도 없다. 목록의 첫 항목으로 넣어 카드와 같은 기둥 안에서 함께 흐르게 한다.
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            // 아래 여백은 FAB가 마지막 카드를 가리지 않을 만큼 둔다.
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = sectionTopPadding, bottom = 88.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item(key = HOME_SECTION_KEY) {
                ListSectionHeader(
                    modifier = Modifier.padding(bottom = SECTION_HEADER_BOTTOM_PADDING),
                    title = stringResource(R.string.session_list_title),
                    // 비어 있을 때는 바로 아래 안내가 같은 말을 하므로 세지 않는다.
                    supporting =
                        taskGroups.size
                            .takeIf { it > 0 }
                            ?.let { stringResource(R.string.task_list_count, it) },
                )
            }
            if (taskGroups.isEmpty()) {
                item(key = HOME_EMPTY_KEY) {
                    Text(
                        text = stringResource(R.string.session_list_empty),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                items(taskGroups.entries.toList(), key = { it.key }) { (taskName, taskSessions) ->
                    val label = taskName.ifBlank { unknownTask }
                    TaskSummaryItem(label, taskSessions.size) { onOpenTask(taskName) }
                }
            }
        }
        NewSessionFab(
            onClick = onStartCapture,
            modifier = Modifier.align(Alignment.BottomEnd),
        )
    }
}

/**
 * 새 세션을 시작하는 FAB다.
 *
 * 새 세션은 목록 화면의 유일한 주 동작이다. Material 3은 그런 동작을 헤더의 아이콘이 아니라 FAB에
 * 두라고 하며, 아이콘 버튼은 부수 동작 자리로 본다. 글자를 함께 둬서 카메라 글리프가 촬영인지
 * 세션 시작인지 헷갈리지 않게 한다.
 */
@Composable
@Suppress("FunctionName")
private fun NewSessionFab(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ExtendedFloatingActionButton(
        onClick = onClick,
        icon = {
            Icon(
                painter = painterResource(R.drawable.ic_new_session),
                contentDescription = null,
            )
        },
        text = { Text(stringResource(R.string.session_list_new_capture)) },
        // 기본값인 primaryContainer는 연한 판이라 목록 위에서 흐릿하게 뜬다. 짙은 primary를
        // 써야 주 동작으로 읽힌다. 그림자도 기본 6dp는 과해서 떠 있는 정도만 남긴다.
        containerColor = MaterialTheme.colorScheme.primary,
        contentColor = MaterialTheme.colorScheme.onPrimary,
        elevation =
            FloatingActionButtonDefaults.elevation(
                defaultElevation = 2.dp,
                pressedElevation = 2.dp,
                focusedElevation = 3.dp,
                hoveredElevation = 3.dp,
            ),
        // 카드와 같은 16dp에 맞춰 오른쪽 끝을 하나로 정렬한다.
        modifier = modifier.padding(16.dp),
    )
}

/**
 * 목록 이름표가 첫 카드에 붙지 않도록 두는 여백.
 *
 * 목록 자체의 8dp 간격에 더해져 카드와 카드 사이보다 넓어야 한 묶음을 이끄는 줄로 읽힌다.
 */
private val SECTION_HEADER_BOTTOM_PADDING = 8.dp

private const val HOME_SECTION_KEY = "home-section"
private const val HOME_EMPTY_KEY = "home-empty"
private const val TASK_SESSIONS_SECTION_KEY = "task-sessions-section"

/** 카드가 안쪽에 두는 여백. 카드 바깥의 글자를 카드 안 글자와 맞출 때 같은 값을 쓴다. */
private val CARD_CONTENT_PADDING = 16.dp

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
        // 이름은 아래 이름표가 말하므로 헤더에는 뒤로 가기만 남긴다. 60dp 안에서 같은 이름을 두 번
        // 읽게 할 이유가 없다.
        NavigationHeader(title = "", onBack = onBack)
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            // 홈과 달리 이 화면에는 헤더가 얹히므로 위 여백을 적게 둔다. 헤더가 이미 아래로
            // 여백을 두고 있어, 여기서 16dp를 더 띄우면 이름표가 화면 한참 아래에서 시작한다.
            //
            // 마지막 카드가 화면 끝에 붙지 않도록 아래 여백을 목록 안쪽에 둔다. Modifier.padding으로
            // 주면 스크롤 영역 자체가 줄어 카드가 여백 위에서 잘린다.
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item(key = TASK_SESSIONS_SECTION_KEY) {
                ListSectionHeader(
                    modifier = Modifier.padding(bottom = SECTION_HEADER_BOTTOM_PADDING),
                    title = title,
                    supporting = stringResource(R.string.session_list_count, sessions.size),
                )
            }
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
        Column(modifier = Modifier.padding(CARD_CONTENT_PADDING), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            // 카드는 섹션 이름표 아래에 놓이므로 제목보다 한 단계 작아야 한다.
            Text(text = taskName, style = MaterialTheme.typography.titleMedium)
            SupportingText(stringResource(R.string.task_list_session_count, sessionCount))
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
    val sessionLabel = stringResource(R.string.session_list_item_content_description, captureTime)
    Card(
        modifier =
            Modifier
                .fillMaxWidth()
                .semantics { contentDescription = sessionLabel }
                .clickable(role = Role.Button) { onOpenSession(summary.sessionId) },
    ) {
        Column(modifier = Modifier.padding(CARD_CONTENT_PADDING), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(text = captureTime, style = MaterialTheme.typography.titleMedium)
            SupportingText(stringResource(uploadStateLabel(summary.uploadState)))
            MetaText(stringResource(R.string.session_list_episode_count, summary.completedEpisodeCount))
            MetaText(stringResource(R.string.session_list_short_id, summary.sessionId.take(8)))
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
