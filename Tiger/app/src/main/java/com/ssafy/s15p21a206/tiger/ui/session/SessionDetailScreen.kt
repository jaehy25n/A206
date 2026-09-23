package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.common.LabelledGroup
import com.ssafy.s15p21a206.tiger.ui.common.LabelledValue
import com.ssafy.s15p21a206.tiger.ui.common.ListSectionHeader
import com.ssafy.s15p21a206.tiger.ui.common.NavigationHeader
import com.ssafy.s15p21a206.tiger.ui.common.TigerMenuItem
import com.ssafy.s15p21a206.tiger.ui.theme.TigerSurface
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText
import com.ssafy.s15p21a206.tiger.ui.upload.labelRes
import com.ssafy.s15p21a206.tiger.ui.video.SharedVideoPlayer
import com.ssafy.s15p21a206.tiger.ui.video.VideoPlayer
import com.ssafy.s15p21a206.tiger.ui.video.rememberVideoAspectRatio
import java.io.File

@Suppress("FunctionName")
@Composable
internal fun SessionDetailScreen(
    summary: SessionSummary?,
    onBack: () -> Unit,
    onUpload: () -> Unit,
    onDelete: () -> Unit,
    deleteFailureReason: String?,
    uploadFailureReason: String?,
    sharedPlayer: SharedVideoPlayer,
    onOpenFullscreenVideo: () -> Unit,
) {
    var showSessionInfo by remember { mutableStateOf(false) }
    var pendingDelete by remember { mutableStateOf<SessionDeleteAction?>(null) }
    val presentation = summary?.let(SessionDetailPresentation::from)
    // 재생 영역 높이와 전송·내보내기 상태에 따라 내용이 화면을 넘는다. 스크롤이 없으면 잘린다.
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
    ) {
        NavigationHeader(
            // 어느 세션인지는 본문의 이름표가 말한다. 헤더에는 뒤로 가기와 메뉴만 남긴다.
            title = "",
            onBack = onBack,
        ) {
            if (summary != null) {
                SessionDetailMenu(
                    deleteAction = presentation?.deleteAction,
                    onOpenSessionInfo = { showSessionInfo = true },
                    onRequestDelete = { pendingDelete = it },
                )
            }
        }
        if (summary == null) {
            Text(
                text = stringResource(R.string.session_detail_unavailable),
                style = TigerText.bodyMuted,
                modifier = Modifier.padding(horizontal = DETAIL_CONTENT_PADDING),
            )
        } else if (presentation != null) {
            // 영상은 좌우 여백 없이 화면 폭을 다 쓴다. 16:9 안에 컨트롤이 오버레이로 놓이므로
            // 여백을 주면 재생 영역만 줄고 얻는 것이 없다.
            SessionVideoPreview(summary.bundlePath, sharedPlayer, onOpenFullscreenVideo)
            Column(
                modifier =
                    Modifier.padding(
                        start = DETAIL_CONTENT_PADDING,
                        end = DETAIL_CONTENT_PADDING,
                        top = DETAIL_VIDEO_GAP,
                        bottom = DETAIL_CONTENT_PADDING,
                    ),
                verticalArrangement = Arrangement.spacedBy(DETAIL_GROUP_GAP),
            ) {
                // 이 화면의 이름은 언제 찍은 것인지이고, 그 아래로 무엇을 찍었는지와 식별자가 온다.
                //
                // 두 이름이 본문에 있어야 하는 이유는 수집을 마감한 직후 경로다. 그때는 Task 묶음도
                // 세션 카드도 지나오지 않고 이 화면으로 바로 오므로, 둘 다 화면에 한 번도 나온 적이
                // 없다. 방금 찍은 것이 맞는지 확인하는 자리에서 메뉴를 한 번 더 열게 할 수 없다.
                //
                // 목록 카드와 달리 Task도 함께 둔다. 카드는 Task 이름을 단 화면 안에 있지만 이
                // 화면은 스스로 말하지 않으면 알 길이 없고, Object만으로는 이름의 절반이다.
                //
                // 상세는 목록 항목이 아니다. Material 3이 보조 줄을 1~3줄로 제한하는 것은 훑는
                // 목록의 규칙이고, 여기서는 줄을 아낄 이유가 없다. 이름표와 값을 쌓는다. 세션 정보
                // 시트가 이미 같은 형태다.
                //
                // 이름과 정보는 띄어서 두 묶음으로 가른다. 같은 간격으로 쌓으면 네 줄이 한 덩어리가
                // 되어 무엇이 이 화면의 이름인지 드러나지 않는다.
                ListSectionHeader(
                    title =
                        java.text.DateFormat
                            .getDateTimeInstance()
                            .format(java.util.Date(summary.recordingStartEpochMs)),
                    supporting = null,
                )
                // 묶음마다 이름표를 붙인다. 이 화면에는 성격이 다른 것이 둘 있다. 이 수집이 무엇인지
                // 말하는 값들과, 그 기록이 지금 어떤 상태인지 말하는 줄이다. 이름표가 없으면 네 줄이
                // 한 더미로 쌓여, 전송 상태가 Task·Object·ID와 같은 종류의 값으로 읽힌다.
                //
                // 이름표는 묶음 안의 글보다 작고 옅다. 읽을 대상이 아니라 무엇을 읽고 있는지 알려
                // 주는 표지이기 때문이다.
                LabelledGroup(stringResource(R.string.session_group_info)) {
                    // 세 줄이 모두 이름표와 값이라 같은 짜임을 쓴다. 이름표 기둥이 고정폭이라 값이
                    // 한 기둥에 정렬되고, 훑는 눈이 값만 따라 내려갈 수 있다.
                    if (summary.taskName.isNotBlank()) {
                        LabelledValue(stringResource(R.string.session_label_task), summary.taskName)
                    }
                    if (summary.objectName.isNotBlank()) {
                        LabelledValue(stringResource(R.string.session_label_object), summary.objectName)
                    }
                    LabelledValue(stringResource(R.string.session_label_id), summary.sessionId.take(8))
                }
                // 아직 올리지 않았다는 것은 업로드 버튼이 이미 말한다. 그 상태에서만 나오는
                // 버튼이므로 같은 말을 한 줄 더 적지 않고, 이름표도 함께 뺀다.
                if (summary.uploadState != UploadState.LOCAL_ONLY) {
                    LabelledGroup(stringResource(R.string.session_group_upload)) {
                        Text(
                            text = stringResource(summary.uploadState.labelRes),
                            style = TigerText.body,
                        )
                        // 무엇이 막았는지 알아야 다시 걸어 볼지 판단할 수 있다. 상태와 같은 카드에
                        // 둔다. 그 상태를 설명하는 줄이지 따로 선 값이 아니다. 앱을 다시 켜면 남지
                        // 않는다. 전송 실패는 기록하는 컬럼이 없다.
                        if (summary.uploadState == UploadState.FAILED && uploadFailureReason != null) {
                            Text(text = uploadFailureReason, style = TigerText.bodyMuted)
                        }
                    }
                }
                // 지우지 못했으면 화면이 그대로 남는다. 아무 말이 없으면 눌리지 않은 것처럼 보인다.
                if (deleteFailureReason != null) {
                    Text(text = deleteFailureReason, style = TigerText.bodyMuted)
                }
                if (presentation.uploadAction != null) {
                    Button(onClick = onUpload) {
                        Text(
                            stringResource(
                                if (presentation.uploadAction ==
                                    SessionDetailPresentation.UploadAction.Retry
                                ) {
                                    R.string.upload_retry
                                } else {
                                    R.string.upload_session
                                },
                            ),
                        )
                    }
                }
            }
        }
    }
    if (showSessionInfo && presentation != null && summary != null) {
        SessionInfoSheet(
            summary = summary,
            durationSeconds = presentation.durationSeconds,
            onDismiss = { showSessionInfo = false },
        )
    }
    // 삭제를 묻는 동안은 영상을 멈춘다. 되돌릴 수 없는 확인을 받는데 뒤에서 소리가 계속 나면
    // 무엇을 묻고 있는지 흐려진다.
    //
    // 확인을 누르면 재생기가 연 그 파일이 곧 사라진다. unlink 자체는 열린 파일에도 안전하지만,
    // 멈춰 두면 재생기가 파일을 다시 열 일이 없어 사라진 뒤에 읽으려 드는 경우가 생기지 않는다.
    LaunchedEffect(pendingDelete) {
        if (pendingDelete != null) sharedPlayer.pause()
    }
    pendingDelete?.let { action ->
        SessionDeleteConfirmation(
            action = action,
            onConfirm = {
                pendingDelete = null
                onDelete()
            },
            onDismiss = { pendingDelete = null },
        )
    }
}

/**
 * 세션 정보와 삭제를 담는 헤더 메뉴다.
 *
 * 둘 다 이 화면의 주 동작이 아니다. 본문의 전송 버튼이 주 동작을 맡고 있고, 이쪽은 확인하거나
 * 정리하러 들어왔을 때만 찾는다. 제목이 없는 헤더에 흐린 글리프를 나란히 세우면 둘 다 무엇인지
 * 추측해야 하는 표가 된다. 메뉴로 접으면 글자로 이름이 붙고 헤더에는 뒤로 가기만 남는다.
 *
 * 삭제는 되돌릴 수 없으므로 메뉴를 여는 한 단계가 더 있는 편이 낫다. 업로드가 번들을 읽고 있는
 * 동안은 누를 수 없으며, 흐린 아이콘과 달리 흐린 글자는 무엇이 막혔는지를 스스로 말한다.
 */
@Composable
@Suppress("FunctionName")
private fun SessionDetailMenu(
    deleteAction: SessionDeleteAction?,
    onOpenSessionInfo: () -> Unit,
    onRequestDelete: (SessionDeleteAction) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { expanded = true }) {
            Icon(
                painter = painterResource(R.drawable.ic_more_actions),
                contentDescription = stringResource(R.string.session_detail_more_actions),
                // 뒤로 가기와 같은 급으로 보이지 않도록 글리프를 작게, 색은 옅게 둔다.
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(HEADER_MENU_ICON_SIZE),
            )
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            TigerMenuItem(
                label = stringResource(R.string.session_info_title),
                icon = R.drawable.ic_session_info,
                onClick = {
                    expanded = false
                    onOpenSessionInfo()
                },
            )
            TigerMenuItem(
                label = stringResource(R.string.session_delete),
                icon = R.drawable.ic_session_delete,
                enabled = deleteAction != null,
                destructive = true,
                onClick = {
                    expanded = false
                    deleteAction?.let(onRequestDelete)
                },
            )
        }
    }
}

/**
 * 세션을 특정해 주지 않는 값들을 담는 시트다.
 *
 * Episode 수·길이·해상도·전체 ID는 세션을 고를 때가 아니라 확인하러 들어왔을 때만 필요하다.
 * 사진 앱이 ⓘ 뒤에 두는 것과 같은 성격이라 상세 본문에서 빼고 여기로 옮겼다.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
@Suppress("FunctionName")
private fun SessionInfoSheet(
    summary: SessionSummary,
    durationSeconds: Long,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = TigerSurface.content) {
        // 행 사이는 12dp다. 값이 한 단계 작아졌으니 사이도 좁혀야 라벨-값 2dp와의 대비가 유지된다.
        // 16dp로 두면 행이 작아진 만큼 빈 자리만 늘어 사다리가 더 늘어져 보인다.
        Column(
            modifier = Modifier.padding(start = 24.dp, end = 24.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = stringResource(R.string.session_info_title),
                style = TigerText.itemName,
            )
            SessionInfoRow(stringResource(R.string.session_info_id), summary.sessionId)
            SessionInfoRow(
                label = stringResource(R.string.session_info_captured_at),
                value =
                    java.text.DateFormat
                        .getDateTimeInstance()
                        .format(java.util.Date(summary.recordingStartEpochMs)),
            )
            SessionInfoRow(
                label = stringResource(R.string.session_info_episodes),
                value = stringResource(R.string.session_info_episode_count, summary.completedEpisodeCount),
            )
            SessionInfoRow(
                label = stringResource(R.string.session_info_duration),
                value = stringResource(R.string.session_detail_duration, durationSeconds),
            )
            SessionInfoRow(
                label = stringResource(R.string.session_info_resolution),
                value =
                    when (val resolution = rememberVideoResolution(summary.bundlePath)) {
                        is VideoResolutionState.Available ->
                            stringResource(R.string.session_detail_resolution, resolution.width, resolution.height)
                        VideoResolutionState.Loading -> stringResource(R.string.session_detail_resolution_loading)
                        VideoResolutionState.Unavailable -> stringResource(R.string.session_detail_resolution_unavailable)
                    },
            )
        }
    }
}

@Composable
@Suppress("FunctionName")
private fun SessionInfoRow(
    label: String,
    value: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(text = label, style = TigerText.supporting)
        // 값은 시트 제목보다 작아야 한다. 전에는 값이 `bodyLarge`라 제목과 같은 16sp였고, 그래서
        // 제목이 목록의 첫 항목처럼 읽히며 큰 글자 다섯 개가 사다리처럼 쌓였다. 한 단계 내리면
        // 제목이 이 시트의 유일한 최상위가 되고, 라벨과의 낙차도 4sp에서 2sp로 좁아져 두 줄이
        // 한 묶음으로 붙는다. 36자 식별자도 한 줄에 들어가 행 높이가 고르게 된다.
        Text(
            text = value,
            style = TigerText.value,
        )
    }
}

@Composable
@Suppress("FunctionName")
private fun SessionVideoPreview(
    bundlePath: String,
    sharedPlayer: SharedVideoPlayer,
    onOpenFullscreenVideo: () -> Unit,
) {
    val videoFile = remember(bundlePath) { File(bundlePath, SessionBundle.MAIN_VIDEO_FILE) }
    val videoDescription = stringResource(R.string.session_detail_video_content_description)
    if (!videoFile.isFile || videoFile.length() == 0L) {
        // 영상은 화면 폭을 다 쓰지만 이 문구는 본문이다. 여백 없이 두면 화면 왼쪽 끝에 붙는다.
        Text(
            text = stringResource(R.string.session_detail_video_unavailable),
            style = TigerText.bodyMuted,
            modifier = Modifier.padding(horizontal = DETAIL_CONTENT_PADDING),
        )
        return
    }
    val player = sharedPlayer.playerFor(videoFile)
    VideoPlayer(
        player = player,
        fullscreen = false,
        onFullscreenClick = onOpenFullscreenVideo,
        modifier =
            Modifier
                .fillMaxWidth()
                .aspectRatio(rememberVideoAspectRatio(player))
                .semantics { contentDescription = videoDescription },
    )
}

/** 세션 상세 본문의 여백. 영상은 화면 폭을 다 쓰므로 이 여백은 그 아래 내용에만 적용된다. */
private val DETAIL_CONTENT_PADDING = 16.dp

/** 영상과 본문 사이 간격. 좌우 여백보다 넓어야 영상이 끝나고 설명이 시작되는 것으로 읽힌다. */
private val DETAIL_VIDEO_GAP = 24.dp

/**
 * 이름과 그 아래 정보 묶음 사이 간격.
 *
 * 줄 사이(2dp)보다 뚜렷하게 넓어야 이름이 정보와 갈린다. 다만 아래 묶음(16dp)보다는 좁아야 둘이
 * 한 덩어리로 묶여 보인다. 간격의 크기가 곧 묶음의 경계다.
 */
private val DETAIL_TITLE_GAP = 8.dp

/**
 * 묶음과 묶음 사이.
 *
 * 묶음 안 줄 사이(6dp)와 이름표가 제 묶음에 붙는 간격(4dp)보다 뚜렷하게 넓어야 한다. 셋이 엇비슷하면
 * 이름표가 어느 묶음의 것인지 간격이 말해 주지 못한다.
 */
private val DETAIL_GROUP_GAP = 20.dp

/**
 * 헤더 메뉴 버튼의 글리프 크기.
 *
 * 헤더에서 뒤로 가기와 나란히 서지만 같은 급의 동작은 아니다. 기본 24dp보다 작게 두어 있는 줄만
 * 알면 되는 단추로 남긴다. 터치 영역은 `IconButton`의 48dp를 그대로 둔다.
 */
private val HEADER_MENU_ICON_SIZE = 20.dp

/** 헤더 메뉴 항목의 글자 굵기. `labelLarge`의 Medium에서 한 단계 내린 값이다. */
