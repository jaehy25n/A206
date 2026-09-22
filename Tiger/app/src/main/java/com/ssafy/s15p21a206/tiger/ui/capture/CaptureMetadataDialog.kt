package com.ssafy.s15p21a206.tiger.ui.capture

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.RecordingInputValidator
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText

/**
 * 수집을 시작하기 전에 Task·Object·해상도를 받는다.
 *
 * 프리뷰나 카메라를 알지 못한다. 값과 콜백만 받고, 확정이 무엇을 여는지는 부모가 정한다.
 *
 * 키보드 입력이 필요한 다이얼로그는 Material 가이드라인상 전체화면으로 띄우고 확인·취소를 상단
 * 앱바에 둔다. 가운데 띄우는 다이얼로그는 가로 화면에서 키보드가 올라오면 아래쪽 버튼이 가려져
 * 닿을 방법이 없다. 앱바는 키보드와 겹치지 않으므로 방향과 무관하게 항상 누를 수 있다.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Suppress("FunctionName")
@Composable
internal fun CaptureMetadataDialog(
    task: String,
    objectName: String,
    resolution: RecordingResolution,
    onTaskChange: (String) -> Unit,
    onObjectNameChange: (String) -> Unit,
    onResolutionChange: (RecordingResolution) -> Unit,
    onConfirm: () -> Unit,
    onCancel: () -> Unit,
) {
    val focusManager = LocalFocusManager.current
    val objectFieldFocus = remember { FocusRequester() }
    val ready = task.isNotBlank() && objectName.isNotBlank()
    Dialog(
        onDismissRequest = onCancel,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.fillMaxSize().safeDrawingPadding()) {
                TopAppBar(
                    title = { Text(stringResource(R.string.capture_metadata_title)) },
                    navigationIcon = {
                        IconButton(onClick = onCancel) {
                            Icon(
                                painter = painterResource(R.drawable.ic_navigation_back),
                                contentDescription = stringResource(R.string.action_cancel),
                            )
                        }
                    },
                    actions = {
                        TextButton(
                            enabled = ready,
                            onClick = onConfirm,
                        ) { Text(stringResource(R.string.capture_metadata_confirm)) }
                    },
                )
                Column(
                    modifier =
                        Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .imePadding()
                            .padding(horizontal = 24.dp, vertical = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    // Task가 채워진 채로 열렸으면 손댈 곳은 다음 칸이다. 이미 적혀 있는
                    // 칸에 커서를 두면 지우고 다시 쓰라는 신호로 읽힌다.
                    LaunchedEffect(Unit) {
                        if (task.isNotBlank()) objectFieldFocus.requestFocus()
                    }
                    OutlinedTextField(
                        value = task,
                        onValueChange = onTaskChange,
                        label = { Text(stringResource(R.string.capture_metadata_task)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                        keyboardActions = KeyboardActions(onNext = { objectFieldFocus.requestFocus() }),
                    )
                    OutlinedTextField(
                        value = objectName,
                        onValueChange = onObjectNameChange,
                        label = { Text(stringResource(R.string.capture_metadata_object)) },
                        modifier = Modifier.focusRequester(objectFieldFocus),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions =
                            KeyboardActions(
                                onDone = {
                                    if (ready) {
                                        focusManager.clearFocus()
                                        onConfirm()
                                    }
                                },
                            ),
                    )
                    RecordingResolutionPicker(selected = resolution, onSelect = onResolutionChange)
                }
            }
        }
    }
}

/**
 * 이번 Session으로 녹화할 해상도를 고른다.
 *
 * Session마다 다르게 갈 수 있으므로 Task·Object와 함께 매번 고른다. 후보는 실기기에서 확인한
 * ARCore Camera config의 `textureSize`이며, 순서는 [RecordingInputValidator.supportedResolutions]를 따른다.
 */
@Suppress("FunctionName")
@Composable
private fun RecordingResolutionPicker(
    selected: RecordingResolution,
    onSelect: (RecordingResolution) -> Unit,
) {
    Column(modifier = Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = stringResource(R.string.capture_metadata_resolution),
            style = TigerText.formLabel,
        )
        RecordingInputValidator.supportedResolutions.forEach { option ->
            Row(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .selectable(
                            selected = option == selected,
                            role = Role.RadioButton,
                            onClick = { onSelect(option) },
                        ).padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 선택은 Row가 받는다. RadioButton에 onClick을 주면 터치 영역이 둘로 갈린다.
                RadioButton(selected = option == selected, onClick = null)
                Text(
                    text = stringResource(R.string.capture_resolution_option, option.width, option.height),
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }
    }
}
