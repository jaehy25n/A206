package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FloatingActionButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.text
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.round
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.ui.common.ListSectionHeader
import com.ssafy.s15p21a206.tiger.ui.common.MetaText
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeader
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeaderTitleCenter
import com.ssafy.s15p21a206.tiger.ui.common.SupportingText
import com.ssafy.s15p21a206.tiger.ui.upload.labelRes

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
    val label = stringResource(R.string.session_list_new_capture)
    ExtendedFloatingActionButton(
        onClick = onClick,
        icon = {
            Icon(
                painter = painterResource(R.drawable.ic_new_session),
                contentDescription = null,
            )
        },
        text = { Text(label) },
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
        //
        // 이름은 글자가 아니라 여기에 둔다. M3의 Extended FAB는 글자를 접었다 펴는 칸으로 다루고
        // 그 칸을 `clearAndSetSemantics`로 감싼다. 접히면 사라질 글자가 이름 노릇을 하면 이름도
        // 함께 사라지기 때문이다. 그래서 글자의 semantics는 merged 트리에서 통째로 지워지고,
        // 글자만 두면 보조 기술에는 이름 없는 버튼으로 읽힌다. merged 트리가 곧 접근성 트리이므로
        // 이름은 FAB 노드 자신이 가져야 한다. 눈에 보이는 문구를 그대로 써야 음성 조작이 들은
        // 대로 부를 수 있다.
        modifier =
            modifier
                .padding(16.dp)
                .semantics { text = AnnotatedString(label) },
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
    onDeleteSession: (String) -> Unit,
    onStartCapture: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val title = taskName.ifBlank { stringResource(R.string.task_name_unknown) }
    Box(modifier = modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            // 이름은 아래 이름표가 말하므로 헤더에는 뒤로 가기만 남긴다. 60dp 안에서 같은 이름을 두 번
            // 읽게 할 이유가 없다.
            NavigationHeader(title = "", onBack = onBack)
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                // 홈과 달리 이 화면에는 헤더가 얹히므로 위 여백을 적게 둔다. 헤더가 이미 아래로
                // 여백을 두고 있어, 여기서 16dp를 더 띄우면 이름표가 화면 한참 아래에서 시작한다.
                //
                // 아래 여백은 홈과 같은 이유로 FAB가 마지막 카드를 가리지 않을 만큼 둔다.
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 88.dp),
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
                    SessionSummaryItem(summary, onOpenSession, onDeleteSession)
                }
            }
        }
        // 같은 Task를 한 번 더 찍으려고 홈까지 나갔다 올 이유가 없다. 여기서 시작하면 Task 이름은
        // 이 화면이 알고 있으므로 다시 입력하지 않는다.
        NewSessionFab(
            onClick = onStartCapture,
            modifier = Modifier.align(Alignment.BottomEnd),
        )
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

/**
 * 목록의 Session 카드다. 열기는 탭, 삭제는 길게 누르기에 둔다.
 *
 * 카드마다 삭제 표를 상주시키지 않는다. 이 목록의 주 동작은 여는 것이고, 모든 행에 부수 동작이
 * 붙으면 목록이 점으로 얼룩진다. 길게 누르기는 안드로이드에서 항목별 동작을 여는 관용구다.
 *
 * 밀어서 삭제는 쓰지 않는다. 그 제스처는 실행취소가 따라온다는 약속을 달고 다니는데, 여기서는
 * 번들을 실제로 지우므로 되돌릴 수 없다. 확인 판을 붙이면 제스처의 약속을 깨고, 붙이지 않으면
 * 스크롤 오조작이 그대로 영구 삭제가 된다.
 *
 * 발견성은 상세 화면의 메뉴가 담당한다. 여기 제스처는 아는 사람을 위한 지름길이다.
 */
@Composable
@Suppress("FunctionName")
private fun SessionSummaryItem(
    summary: SessionSummary,
    onOpenSession: (String) -> Unit,
    onDeleteSession: (String) -> Unit,
) {
    val captureTime =
        java.text.DateFormat
            .getDateTimeInstance()
            .format(java.util.Date(summary.recordingStartEpochMs))
    val sessionLabel = stringResource(R.string.session_list_item_content_description, captureTime)
    val deleteAction = SessionDeleteAction.from(summary.uploadState)
    var menuExpanded by remember { mutableStateOf(false) }
    var pendingDelete by remember { mutableStateOf<SessionDeleteAction?>(null) }
    // 길게 누른 지점. 메뉴는 카드가 아니라 이 지점에 건다.
    var pressPosition by remember { mutableStateOf(IntOffset.Zero) }
    Box {
        Card(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = sessionLabel }
                    // 누른 자리를 기록만 하고 소비하지 않는다. Initial pass에서 보기만 하므로
                    // 아래 `combinedClickable`의 탭·길게 누르기와 ripple이 그대로 동작한다.
                    .pointerInput(Unit) {
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent(PointerEventPass.Initial)
                                if (event.type == PointerEventType.Press) {
                                    pressPosition =
                                        event.changes
                                            .first()
                                            .position
                                            .round()
                                }
                            }
                        }
                    }.combinedClickable(
                        role = Role.Button,
                        onLongClickLabel = stringResource(R.string.session_delete),
                        onLongClick = { menuExpanded = true },
                        onClick = { onOpenSession(summary.sessionId) },
                    ),
        ) {
            Column(modifier = Modifier.padding(CARD_CONTENT_PADDING), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(text = captureTime, style = MaterialTheme.typography.titleMedium)
                SupportingText(stringResource(summary.uploadState.labelRes))
                MetaText(stringResource(R.string.session_list_episode_count, summary.completedEpisodeCount))
                MetaText(stringResource(R.string.session_list_short_id, summary.sessionId.take(8)))
            }
        }
        // 메뉴는 누른 손가락 자리에서 열린다. 카드를 앵커로 쓰면 폭이 화면을 꽉 채우므로 어디를
        // 눌렀든 카드 왼쪽 아래 구석에서 열려, 방금 건드린 곳과 메뉴가 멀리 떨어진다.
        // 크기 0짜리 앵커를 누른 지점에 두고 거기에 건다.
        Box(modifier = Modifier.offset { pressPosition }) {
            DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.session_delete), fontWeight = FontWeight.Normal) },
                    leadingIcon = {
                        Icon(
                            painter = painterResource(R.drawable.ic_session_delete),
                            // 이름은 바로 옆 글자가 말한다. 아이콘까지 읽히면 같은 말을 두 번 한다.
                            contentDescription = null,
                        )
                    },
                    // 업로드가 번들을 읽고 있는 동안은 지울 수 없다. 이유는 카드의 전송 상태가 말한다.
                    enabled = deleteAction != null,
                    colors =
                        MenuDefaults.itemColors(
                            textColor = MaterialTheme.colorScheme.error,
                            leadingIconColor = MaterialTheme.colorScheme.error,
                        ),
                    onClick = {
                        menuExpanded = false
                        pendingDelete = deleteAction
                    },
                )
            }
        }
    }
    pendingDelete?.let { action ->
        SessionDeleteConfirmation(
            action = action,
            onConfirm = {
                pendingDelete = null
                onDeleteSession(summary.sessionId)
            },
            onDismiss = { pendingDelete = null },
        )
    }
}
