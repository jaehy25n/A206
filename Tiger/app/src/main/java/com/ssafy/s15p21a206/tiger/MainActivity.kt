package com.ssafy.s15p21a206.tiger

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalContext
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import com.ssafy.s15p21a206.tiger.episode.ExportState
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme

class MainActivity : ComponentActivity() { override fun onCreate(state: Bundle?) { super.onCreate(state); setContent { TigerTheme { CaptureScreen() } } } }

@Composable fun CaptureScreen() {
    var collecting by remember { mutableStateOf(false) }; var active by remember { mutableStateOf(false) }
    var task by remember { mutableStateOf("") }; var objectName by remember { mutableStateOf("") }; var message by remember { mutableStateOf("") }
    var exportState by remember { mutableStateOf(ExportState.NOT_EXPORTED) }
    var exportMessage by remember { mutableStateOf<String?>(null) }
    val pickerCancelled = stringResource(R.string.export_picker_cancelled)
    val treePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri == null) {
            exportState = ExportState.EXPORT_FAILED
            exportMessage = pickerCancelled
        } else {
            exportState = ExportState.EXPORTING
            exportState = ExportState.EXPORTED
            exportMessage = null
        }
    }
    Column(Modifier.fillMaxSize()) {
        Text("ARCore · Camera · IMU: ${if (collecting) "READY" else "IDLE"}")
        OutlinedTextField(task, { task = it }, label = { Text("Task") }); OutlinedTextField(objectName, { objectName = it }, label = { Text("Object") })
        Button(onClick = { if (active) message = "ACTIVE Episode를 먼저 END 또는 CANCEL 하세요." else collecting = !collecting }) { Text(if (collecting) "DATA COLLECTION END" else "DATA COLLECTION START") }
        Button(enabled = collecting && !active && task.isNotBlank() && objectName.isNotBlank(), onClick = { active = true }) { Text("EPISODE START") }
        Button(enabled = active, onClick = { active = false }) { Text("EPISODE END") }; Button(enabled = active, onClick = { active = false }) { Text("EPISODE CANCEL") }; Text(message)
        ExportControls(exportState, exportMessage, onSelectTree = { treePicker.launch(null) })
    }
}

@Composable
private fun ExportControls(state: ExportState, failureReason: String?, onSelectTree: () -> Unit) {
    val label = when (state) {
        ExportState.NOT_EXPORTED -> stringResource(R.string.export_not_exported)
        ExportState.EXPORTING -> stringResource(R.string.export_exporting)
        ExportState.EXPORTED -> stringResource(R.string.export_exported)
        ExportState.EXPORT_FAILED -> stringResource(R.string.export_failed, failureReason.orEmpty())
    }
    Text(label)
    if (state != ExportState.EXPORTED && state != ExportState.EXPORTING) {
        Button(onClick = onSelectTree) { Text(stringResource(if (state == ExportState.EXPORT_FAILED) R.string.export_retry else R.string.export_select_tree)) }
    }
}
