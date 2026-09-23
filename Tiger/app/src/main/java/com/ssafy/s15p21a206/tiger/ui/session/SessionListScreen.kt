package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.text
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.round
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.ui.common.ListSectionHeader
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeader
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeaderHeight
import com.ssafy.s15p21a206.tiger.ui.common.TigerCard
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText
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
    // 이 화면에는 헤더가 없다. Task를 열면 나오는 화면은 헤더를 얹고 그 아래에서 본문을 시작하므로,
    // 여기서도 헤더만큼을 비워야 화면을 오갈 때 이름표가 제자리에 머무르는 것으로 보인다.
    //
    // 전에는 제목의 중심을 헤더 제목의 중심에 맞춰 14dp만 비웠다. 그 정렬은 맞출 상대가 없었다.
    // 헤더에 제목을 두는 화면이 없어 어느 화면이든 이름은 본문의 이름표가 말하는데, 그 이름표는
    // 헤더 아래 64dp에서 시작한다. 홈만 50dp 위에 붙어 화면 위쪽에 눌린 것으로 보였다.
    val sectionTopPadding = NavigationHeaderHeight + LIST_CONTENT_TOP_PADDING
    Box(modifier = modifier.fillMaxSize()) {
        if (taskGroups.isEmpty()) {
            // 비어 있으면 목록이 아니다. 이름표는 제자리에 두고 안내만 남은 공간 가운데로 보낸다.
            // 목록 항목처럼 왼쪽 위에 붙여 두면 채워질 자리를 기다리는 빈 행으로 읽힌다.
            Column(
                modifier =
                    Modifier
                        .fillMaxSize()
                        .padding(start = 16.dp, end = 16.dp, top = sectionTopPadding, bottom = FAB_CLEARANCE),
            ) {
                ListSectionHeader(
                    modifier = Modifier.padding(bottom = SECTION_HEADER_BOTTOM_PADDING),
                    title = stringResource(R.string.session_list_title),
                    // 비어 있을 때는 아래 안내가 같은 말을 하므로 세지 않는다.
                    supporting = null,
                )
                EmptyListMessage(stringResource(R.string.session_list_empty), Modifier.weight(1f))
            }
        } else {
            // 이름표를 목록 바깥에 두면 홀로 뜬 머리띠가 되고, FAB가 아래로 내려간 뒤로는 같은 줄에
            // 짝이 될 것도 없다. 목록의 첫 항목으로 넣어 카드와 같은 기둥 안에서 함께 흐르게 한다.
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                // 아래 여백은 FAB가 마지막 카드를 가리지 않을 만큼 둔다.
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = sectionTopPadding, bottom = FAB_CLEARANCE),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item(key = HOME_SECTION_KEY) {
                    ListSectionHeader(
                        modifier = Modifier.padding(bottom = SECTION_HEADER_BOTTOM_PADDING),
                        title = stringResource(R.string.session_list_title),
                        supporting = stringResource(R.string.task_list_count, taskGroups.size),
                    )
                }
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

/** 이름표가 화면 맨 위나 헤더에 붙지 않도록 본문 위에 두는 여백. 두 목록 화면이 같은 값을 쓴다. */
private val LIST_CONTENT_TOP_PADDING = 8.dp

private const val HOME_SECTION_KEY = "home-section"
private const val TASK_SESSIONS_SECTION_KEY = "task-sessions-section"

/** FAB가 마지막 카드나 안내를 가리지 않도록 목록 아래에 두는 여백. */
private val FAB_CLEARANCE = 88.dp

/**
 * 목록이 비었을 때 남은 공간 가운데에 놓는 안내다.
 *
 * 목록 항목처럼 왼쪽 위에 붙여 두면 곧 채워질 자리를 기다리는 빈 행으로 읽힌다. 화면에 혼자 있는
 * 문장이므로 카드 안 메타 정보와 같은 크기일 이유도 없다.
 */
@Composable
@Suppress("FunctionName")
private fun EmptyListMessage(
    text: String,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            text = text,
            style = TigerText.bodyMuted,
            textAlign = TextAlign.Center,
        )
    }
}

/** 카드가 안쪽에 두는 여백. 카드 바깥의 글자를 카드 안 글자와 맞출 때 같은 값을 쓴다. */
private val CARD_CONTENT_PADDING = 16.dp

/**
 * 카드 안 두 줄 사이.
 *
 * 안쪽 여백의 절반이다. 이름과 그에 딸린 값이 한 덩어리로 읽히려면 둘을 가르는 간격이 덩어리를
 * 감싸는 여백보다 뚜렷하게 작아야 한다. 전에는 줄상자의 남는 여백까지 더해져 실제 13dp였고, 카드
 * 여백 18~20dp와 맞먹어 두 줄이 따로 떴다.
 */
private val CARD_LINE_GAP = 8.dp

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
            // 마지막 세션을 지우면 이 화면이 빈 채로 남는다. 삭제하기 전에는 세션이 있는 Task만
            // 홈에 나타나 이 상태에 닿을 수 없었다. 홈과 같은 짜임으로 안내를 가운데에 둔다.
            if (sessions.isEmpty()) {
                Column(
                    modifier =
                        Modifier
                            .fillMaxSize()
                            .padding(start = 16.dp, end = 16.dp, top = LIST_CONTENT_TOP_PADDING, bottom = FAB_CLEARANCE),
                ) {
                    ListSectionHeader(
                        modifier = Modifier.padding(bottom = SECTION_HEADER_BOTTOM_PADDING),
                        title = title,
                        supporting = null,
                    )
                    EmptyListMessage(stringResource(R.string.task_session_list_empty), Modifier.weight(1f))
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    // 위 여백은 헤더 아래에서부터 재므로 홈이 헤더 높이에 더해 쓰는 것과 같은 값이다.
                    // 두 화면의 이름표가 같은 높이에서 시작한다.
                    //
                    // 아래 여백은 홈과 같은 이유로 FAB가 마지막 카드를 가리지 않을 만큼 둔다.
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = LIST_CONTENT_TOP_PADDING, bottom = FAB_CLEARANCE),
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
    TigerCard(
        modifier =
            Modifier
                .fillMaxWidth()
                .semantics { contentDescription = taskName }
                .clickable(role = Role.Button, onClick = onOpenTask),
    ) {
        Column(modifier = Modifier.padding(CARD_CONTENT_PADDING), verticalArrangement = Arrangement.spacedBy(CARD_LINE_GAP)) {
            // 카드는 섹션 이름표 아래에 놓이므로 제목보다 한 단계 작아야 한다.
            Text(text = taskName, style = TigerText.itemName)
            Text(text = stringResource(R.string.task_list_session_count, sessionCount), style = TigerText.supporting)
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
        TigerCard(
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
            Column(modifier = Modifier.padding(CARD_CONTENT_PADDING), verticalArrangement = Arrangement.spacedBy(CARD_LINE_GAP)) {
                // 이름과 상태를 한 행에 둔다. 상태는 이름에 딸린 값이 아니라 그 세션이 지금 어떤지를
                // 말하므로 왼쪽 더미에 끼워 넣지 않는다. Material 3 리스트가 개수·날짜 같은 부수
                // 정보를 trailing에 두는 자리다.
                //
                // 왼쪽 더미에서 한글 줄이 빠지는 효과도 있다. `E`나 `I`는 세로 획이 열을 꽉 채워
                // 서지만 `업`의 ㅇ은 완만한 곡선이라, 나란히 쌓으면 상자 원점이 같은데도 한글 줄만
                // 들여쓴 것처럼 보였다.
                // 스타일은 셋만 쓴다. 이름(16sp 진함), 딸린 값(14sp 옅음), 식별자(14sp Medium
                // 진함)다. Object와 전송 상태가 한 스타일을 함께 쓰는 것이 핵심이다.
                //
                // 요소마다 새 조합을 만들지 않는다. 전에는 다섯 요소가 글꼴·크기·굵기·색 네 축을
                // 섞어 조합 다섯 개를 만들었고, 그러면 어느 요소도 다른 요소와 스타일을 공유하지
                // 않아 위계가 아니라 잡음으로 읽힌다. 값이 넷인 GitHub의 커밋 행은 조합 셋으로
                // 끝내고, 글꼴은 하나에 크기는 둘만 쓴다.
                //
                // 행으로 종류를 가른다. 첫 행은 이 수집이 무엇이고 지금 어떤가(수집 일시·전송 상태),
                // 둘째 행은 그것에 딸린 메타(Object·짧은 ID)다.
                //
                // 전에는 열로 갈랐고, 그래서 종류가 섞였다. 오른쪽 열에 식별자와 전송 상태가 함께
                // 있었는데 앞은 메타이고 뒤는 상태다. 왼쪽 열에는 이름과 메타가 함께 있었다. 어느
                // 열도 한 종류를 담지 않아, 무엇과 무엇이 같은 부류인지를 자리가 말해 주지 못했다.
                //
                // 상태가 첫 행의 오른쪽 끝에 오는 것은 그것이 이 행에서 변하는 유일한 값이기
                // 때문이다. 목록을 훑는 이유가 무엇이 올라갔고 무엇이 안 올라갔는지 보는 것이다.
                // 메타는 변하지 않으므로 아래 행에서 기다려도 된다.
                //
                // 두 행 모두 글자 크기가 다르므로 baseline을 맞춘다. 위를 맞추면 작은 글자가 큰
                // 글자의 윗선에 붙어 떠 보인다.
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = captureTime,
                        style = TigerText.itemName,
                        modifier =
                            Modifier
                                .weight(1f)
                                .alignByBaseline(),
                    )
                    Text(
                        text = stringResource(summary.uploadState.labelRes),
                        style = TigerText.supporting,
                        modifier = Modifier.alignByBaseline(),
                    )
                }
                // 메타 둘은 왼쪽에 세로로 쌓는다. 값을 부호로 이어 붙이지 않는다. 값마다 제 줄을
                // 주고, 묶이는 것은 서로 붙어 있다는 사실이 말한다.
                //
                // 열로 갈라 Object를 왼쪽, 식별자를 오른쪽 끝에 두었더니 근접성이 종류를 이겼다.
                // 식별자와 전송 상태가 같은 오른쪽 기둥에 세로로 붙어 한 묶음으로 보였는데 앞은
                // 메타이고 뒤는 상태다. 붙여 놓은 것이 곧 묶인 것으로 읽히므로, 묶고 싶은 것을
                // 붙여 놓아야 한다. 지금은 두 메타가 서로의 바로 아래위에 있고 상태는 첫 행의 반대쪽
                // 끝에 있다.
                //
                // 두 이름을 Session 행에 저장하기 전에 마감된 세션은 Object가 비어 있다. 그때는 빈
                // 이름표를 세우지 않고 줄째로 뺀다. 아래 식별자가 올라와 붙으므로 구멍이 남지 않는다.
                if (summary.objectName.isNotBlank()) {
                    Text(
                        text = stringResource(R.string.session_object, summary.objectName),
                        style = TigerText.supporting,
                    )
                }
                Text(
                    text = stringResource(R.string.session_list_short_id, summary.sessionId.take(8)),
                    style = TigerText.supporting,
                )
            }
        }
        // 메뉴는 누른 손가락 자리에서 열린다. 카드를 앵커로 쓰면 폭이 화면을 꽉 채우므로 어디를
        // 눌렀든 카드 왼쪽 아래 구석에서 열려, 방금 건드린 곳과 메뉴가 멀리 떨어진다.
        // 크기 0짜리 앵커를 누른 지점에 두고 거기에 건다.
        Box(modifier = Modifier.offset { pressPosition }) {
            DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.session_delete), style = TigerText.menuItem) },
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
