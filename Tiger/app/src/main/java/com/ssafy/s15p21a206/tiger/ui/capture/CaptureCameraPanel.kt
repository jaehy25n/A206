package com.ssafy.s15p21a206.tiger.ui.capture

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCompositionContext
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.google.android.material.sidesheet.SideSheetDialog
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.capture.ManualCameraCapabilities
import com.ssafy.s15p21a206.tiger.capture.ManualCameraConfig
import com.ssafy.s15p21a206.tiger.capture.ShutterPreset
import com.ssafy.s15p21a206.tiger.episode.RecordingInputValidator
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureChoiceSelected
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureChoiceSelectedInk
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureControlDisabled
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureOverlayScrim
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureOverlaySupporting
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText

/**
 * 수집 전에 촬영 조건을 맞추는 패널.
 *
 * 값은 바꾸는 즉시 프리뷰에 걸린다. 초점을 화면으로 보고 고르는 것이 이 패널의 목적이라, 확인
 * 버튼을 눌러야 반영되는 구조로 두면 맞출 수가 없다. [enabled]가 `false`인 동안은 Session이
 * 돌고 있다는 뜻이고, 그때는 어떤 값도 받지 않는다.
 *
 * 기기가 지원하지 않는 항목은 감추지 않고 끈 채로 둔다. 자리가 사라지면 왜 못 쓰는지 물을 데가
 * 없어진다.
 */
@Suppress("FunctionName")
@Composable
internal fun CaptureCameraPanel(
    state: ManualCameraUiState,
    resolution: RecordingResolution,
    enabled: Boolean,
    onChange: (ManualCameraConfig) -> Unit,
    onResolutionChange: (RecordingResolution) -> Unit,
    onFixWhiteBalance: () -> Unit,
    onClearWhiteBalance: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val capabilities = state.capabilities
    val config = state.config
    val closeDescription = stringResource(R.string.capture_camera_close)
    Column(
        modifier =
            modifier
                .fillMaxWidth()
                // 가로 화면에서 항목 다섯이 한 번에 들어가지 않는 기기가 있다. 잘라내는 대신 굴린다.
                .verticalScroll(rememberScrollState())
                .safeDrawingPadding()
                .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text = stringResource(R.string.capture_camera_title), style = TigerText.overlayBadge)
            // 값은 바꾸는 즉시 걸리므로 확정할 것이 없다. "적용"이라 부르면 누르기 전에는 안 걸린 것처럼 읽힌다.
            IconButton(onClick = onClose, modifier = Modifier.semantics { contentDescription = closeDescription }) {
                Text(text = stringResource(R.string.control_close), style = TigerText.overlayGlyph, color = Color.White)
            }
        }
        // 해상도는 카메라가 수동 제어를 지원하지 않아도 고를 수 있다. 사유 문구보다 위에 둔다.
        ResolutionRow(resolution, enabled, onResolutionChange)
        val reason = state.unsupportedReason
        if (capabilities == null || config == null || reason != null) {
            Text(
                text = reason ?: stringResource(R.string.capture_camera_reading),
                style = TigerText.overlaySupporting,
                color = CaptureOverlaySupporting,
            )
            return@Column
        }
        FocusRow(capabilities, config, enabled, onChange)
        IsoRow(capabilities, config, enabled, onChange)
        ShutterRow(capabilities, config, enabled, onChange)
        Text(
            text = stringResource(R.string.capture_camera_fps_fixed, ManualCameraConfig.TARGET_FPS),
            style = TigerText.overlaySupporting,
            color = CaptureOverlaySupporting,
        )
        WhiteBalanceRow(state, enabled, onFixWhiteBalance, onClearWhiteBalance)
    }
}

@Suppress("FunctionName")
@Composable
private fun FocusRow(
    capabilities: ManualCameraCapabilities,
    config: ManualCameraConfig,
    enabled: Boolean,
    onChange: (ManualCameraConfig) -> Unit,
) {
    // 0 D가 무한대, 최대 diopter가 최단 거리다. 슬라이더를 오른쪽으로 밀수록 가까워진다.
    PanelLabel(
        label = stringResource(R.string.capture_camera_focus),
        value = stringResource(R.string.capture_camera_focus_value, config.focusDistanceDiopter),
    )
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = stringResource(R.string.capture_camera_focus_far),
            style = TigerText.overlaySupporting,
            color = CaptureOverlaySupporting,
        )
        Slider(
            value = config.focusDistanceDiopter,
            onValueChange = { onChange(config.copy(focusDistanceDiopter = it)) },
            valueRange = 0f..capabilities.maxFocusDiopter.coerceAtLeast(MIN_SLIDER_SPAN),
            enabled = enabled && capabilities.focusSupported,
            modifier = Modifier.weight(1f),
        )
        Text(
            text = stringResource(R.string.capture_camera_focus_near),
            style = TigerText.overlaySupporting,
            color = CaptureOverlaySupporting,
        )
    }
    if (!capabilities.focusSupported) {
        Text(
            text = stringResource(R.string.capture_camera_focus_unsupported),
            style = TigerText.overlaySupporting,
            color = CaptureControlDisabled,
        )
    }
}

@Suppress("FunctionName")
@Composable
private fun IsoRow(
    capabilities: ManualCameraCapabilities,
    config: ManualCameraConfig,
    enabled: Boolean,
    onChange: (ManualCameraConfig) -> Unit,
) {
    val range = capabilities.isoRange
    PanelLabel(
        label = stringResource(R.string.capture_camera_iso),
        value = stringResource(R.string.capture_camera_iso_value, config.iso),
    )
    Slider(
        value = config.iso.toFloat(),
        onValueChange = { onChange(config.copy(iso = it.toInt())) },
        valueRange = (range?.first?.toFloat() ?: 0f)..(range?.last?.toFloat() ?: 1f),
        enabled = enabled && capabilities.isoSupported,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Suppress("FunctionName")
@Composable
private fun ShutterRow(
    capabilities: ManualCameraCapabilities,
    config: ManualCameraConfig,
    enabled: Boolean,
    onChange: (ManualCameraConfig) -> Unit,
) {
    PanelLabel(
        label = stringResource(R.string.capture_camera_shutter),
        value = stringResource(R.string.capture_camera_shutter_value, config.exposureTimeNs / MICROSECONDS_PER_NS),
    )
    // preset 다섯이 한 줄에 들어가지 않으면 다음 줄로 내린다. 글자를 줄여 넣으면 장갑 낀 손으로
    // 누르기 어려워진다.
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        ShutterPreset.entries.forEach { preset ->
            // 기기가 못 내는 셔터와 30 fps 프레임 간격을 넘는 셔터는 끈다. 노출이 프레임 간격보다
            // 길면 센서가 간격을 늘려 30 fps가 깨진다.
            PanelChoice(
                label = preset.label,
                selected = preset.exposureTimeNs == config.exposureTimeNs,
                enabled = enabled && capabilities.exposureSupported && capabilities.allows(preset),
                onClick = { onChange(config.copy(exposureTimeNs = preset.exposureTimeNs)) },
            )
        }
    }
}

/**
 * 이번 Session으로 녹화할 해상도.
 *
 * 후보는 실기기에서 확인한 ARCore Camera config의 `textureSize`이며, 순서는
 * [RecordingInputValidator.supportedResolutions]를 따른다.
 */
@OptIn(ExperimentalLayoutApi::class)
@Suppress("FunctionName")
@Composable
private fun ResolutionRow(
    resolution: RecordingResolution,
    enabled: Boolean,
    onChange: (RecordingResolution) -> Unit,
) {
    val label = stringResource(R.string.capture_resolution_option, resolution.width, resolution.height)
    PanelLabel(label = stringResource(R.string.capture_camera_resolution), value = label)
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        RecordingInputValidator.supportedResolutions.forEach { option ->
            PanelChoice(
                label = stringResource(R.string.capture_resolution_option, option.width, option.height),
                selected = option == resolution,
                enabled = enabled,
                onClick = { onChange(option) },
            )
        }
    }
}

/**
 * 여럿 중 하나를 고르는 단추. 고른 것은 흰 판으로 채우고 나머지는 윤곽만 남긴다.
 *
 * 강조색(초록)으로 채우지 않는다. 그 색은 재생 버튼의 "시작"이라는 뜻을 이미 갖고 있고, 어두운
 * 판 위에서 흰 글자와의 대비도 낮아 무엇을 골랐는지가 한눈에 들어오지 않았다.
 */
@Suppress("FunctionName")
@Composable
private fun PanelChoice(
    label: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    if (selected) {
        Button(
            onClick = onClick,
            enabled = enabled,
            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
            colors = ButtonDefaults.buttonColors(containerColor = CaptureChoiceSelected),
        ) {
            Text(text = label, style = TigerText.overlayBadge, color = CaptureChoiceSelectedInk)
        }
    } else {
        OutlinedButton(
            onClick = onClick,
            enabled = enabled,
            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
        ) {
            Text(
                text = label,
                style = TigerText.overlayBadge,
                color = if (enabled) CaptureOverlaySupporting else CaptureControlDisabled,
            )
        }
    }
}

/**
 * 화이트 밸런스는 AUTO로 수렴시킨 뒤 그 값을 붙잡는 것만 제공한다.
 *
 * Kelvin이나 RGB gain을 직접 고르는 화면은 만들지 않는다. 목적이 정확한 색을 지정하는 것이 아니라
 * 촬영 내내, 그리고 calibration 촬영과 dataset 수집 사이에 색이 변하지 않게 하는 것이기 때문이다.
 */
@Suppress("FunctionName")
@Composable
private fun WhiteBalanceRow(
    state: ManualCameraUiState,
    enabled: Boolean,
    onFix: () -> Unit,
    onClear: () -> Unit,
) {
    val fixed = state.whiteBalanceFixed
    PanelLabel(
        label = stringResource(R.string.capture_camera_white_balance),
        value =
            stringResource(
                if (fixed) R.string.capture_camera_white_balance_fixed else R.string.capture_camera_white_balance_auto,
            ),
    )
    val supported = state.capabilities?.whiteBalanceSupported == true
    OutlinedButton(onClick = if (fixed) onClear else onFix, enabled = enabled && supported) {
        Text(
            text =
                stringResource(
                    if (fixed) R.string.capture_camera_white_balance_release else R.string.capture_camera_white_balance_hold,
                ),
            style = TigerText.overlayBadge,
            color = if (enabled && supported) CaptureOverlaySupporting else CaptureControlDisabled,
        )
    }
}

@Suppress("FunctionName")
@Composable
private fun PanelLabel(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, style = TigerText.overlaySupporting, color = CaptureOverlaySupporting)
        Text(text = value, style = TigerText.overlayBadge)
    }
}

/**
 * 카메라 설정 시트를 여는 단추. Session이 도는 동안은 받지 않는다.
 *
 * 다른 수집 오버레이와 같은 판에 올린다. 윤곽선만 있는 단추는 밝은 장면의 프리뷰 위에서 묻혔다.
 */
@Suppress("FunctionName")
@Composable
internal fun CaptureCameraSettingsButton(
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    CaptureTooltip(R.string.capture_camera_title, modifier) {
        IconButton(
            onClick = onClick,
            enabled = enabled,
            modifier = Modifier.size(48.dp).background(CaptureOverlayScrim, CircleShape),
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_capture_settings),
                contentDescription = stringResource(R.string.capture_camera_title),
                tint = if (enabled) Color.White else CaptureControlDisabled,
            )
        }
    }
}

/**
 * 카메라 설정을 오른쪽 모달 사이드 시트로 띄운다. 이 Composable이 composition에 있는 동안 열려 있다.
 *
 * Compose Material3에는 사이드 시트가 없어 Material Components의 [SideSheetDialog]를 쓴다. 막 탭과
 * 시스템 뒤로 가기가 [onDismiss]로 온다. 모달이라 열려 있는 동안 뒤의 제어는 받지
 * 않는다. 막은 어둡게 깔지 않는다(`Theme.Tiger.CameraSheet`). 옆의 프리뷰를 보며 값을 맞춰야 한다.
 *
 * 시트의 내용은 이 자리의 composition을 부모로 삼아 그린다. 테마와 CompositionLocal이 그대로
 * 이어지고, [content]가 바뀌면 시트 안도 다시 그려진다.
 */
@Suppress("FunctionName")
@Composable
internal fun CaptureCameraSheet(
    onDismiss: () -> Unit,
    content: @Composable () -> Unit,
) {
    val view = LocalView.current
    val parent = rememberCompositionContext()
    val currentContent by rememberUpdatedState(content)
    val currentOnDismiss by rememberUpdatedState(onDismiss)
    DisposableEffect(view) {
        val dialog = SideSheetDialog(view.context, R.style.Theme_Tiger_CameraSheet)
        val sheetContent =
            ComposeView(dialog.context).apply {
                setParentCompositionContext(parent)
                setContent { currentContent() }
            }
        dialog.setContentView(sheetContent)
        // 가로로 끌어 닫는 동작을 끈다. 초점·ISO 슬라이더를 미는 손이 시트를 끌어 버린다.
        // 닫는 길은 X, 바깥 탭, 시스템 뒤로 가기로 충분하다.
        dialog.behavior.isDraggable = false
        dialog.setOnDismissListener { currentOnDismiss() }
        dialog.show()
        onDispose {
            // 상태가 먼저 닫힌 경우(Session 시작 등)다. 사용자가 닫은 것처럼 다시 알리지 않는다.
            dialog.setOnDismissListener(null)
            dialog.dismiss()
        }
    }
}

/** 초점 슬라이더가 0 폭이 되지 않게 하는 최소 범위. 고정 초점 기기에서도 화면이 깨지지 않는다. */
private const val MIN_SLIDER_SPAN = 1f

private const val MICROSECONDS_PER_NS = 1_000L
