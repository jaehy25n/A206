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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.capture.ManualCameraCapabilities
import com.ssafy.s15p21a206.tiger.capture.ManualCameraConfig
import com.ssafy.s15p21a206.tiger.capture.ShutterPreset
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureControlDisabled
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureOverlayScrim
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureOverlaySupporting
import com.ssafy.s15p21a206.tiger.ui.theme.CaptureStart
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
    enabled: Boolean,
    onChange: (ManualCameraConfig) -> Unit,
    onFixWhiteBalance: () -> Unit,
    onClearWhiteBalance: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val capabilities = state.capabilities
    val config = state.config
    Column(
        modifier =
            modifier
                .width(PANEL_WIDTH)
                .clip(RoundedCornerShape(16.dp))
                .background(CaptureOverlayScrim)
                // 가로 화면에서 항목 다섯이 한 번에 들어가지 않는 기기가 있다. 잘라내는 대신 굴린다.
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text = stringResource(R.string.capture_camera_title), style = TigerText.overlayBadge)
            TextButton(onClick = onClose) {
                Text(text = stringResource(R.string.capture_camera_apply), style = TigerText.overlayBadge, color = CaptureStart)
            }
        }
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
            val selected = preset.exposureTimeNs == config.exposureTimeNs
            // 기기가 못 내는 셔터와 30 fps 프레임 간격을 넘는 셔터는 끈다. 노출이 프레임 간격보다
            // 길면 센서가 간격을 늘려 30 fps가 깨진다.
            val selectable = enabled && capabilities.exposureSupported && capabilities.allows(preset)
            if (selected) {
                Button(
                    onClick = { onChange(config.copy(exposureTimeNs = preset.exposureTimeNs)) },
                    enabled = selectable,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = CaptureStart),
                ) {
                    Text(text = preset.label, style = TigerText.overlayBadge)
                }
            } else {
                OutlinedButton(
                    onClick = { onChange(config.copy(exposureTimeNs = preset.exposureTimeNs)) },
                    enabled = selectable,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                ) {
                    Text(
                        text = preset.label,
                        style = TigerText.overlayBadge,
                        color = if (selectable) CaptureOverlaySupporting else CaptureControlDisabled,
                    )
                }
            }
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

/** 수동 설정 패널을 여는 단추. Session이 도는 동안은 받지 않는다. */
@Suppress("FunctionName")
@Composable
internal fun CaptureCameraPanelButton(
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedButton(onClick = onClick, enabled = enabled, modifier = modifier) {
        Text(
            text = stringResource(R.string.capture_camera_title),
            style = TigerText.overlayBadge,
            color = if (enabled) CaptureOverlaySupporting else CaptureControlDisabled,
        )
    }
}

private val PANEL_WIDTH = 320.dp

/** 초점 슬라이더가 0 폭이 되지 않게 하는 최소 범위. 고정 초점 기기에서도 화면이 깨지지 않는다. */
private const val MIN_SLIDER_SPAN = 1f

private const val MICROSECONDS_PER_NS = 1_000L
