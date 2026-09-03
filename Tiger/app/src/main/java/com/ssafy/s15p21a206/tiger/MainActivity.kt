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
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme

class MainActivity : ComponentActivity() { override fun onCreate(state: Bundle?) { super.onCreate(state); setContent { TigerTheme { CaptureScreen() } } } }

@Composable fun CaptureScreen() {
    var collecting by remember { mutableStateOf(false) }; var active by remember { mutableStateOf(false) }
    var task by remember { mutableStateOf("") }; var objectName by remember { mutableStateOf("") }; var message by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        Text("ARCore · Camera · IMU: ${if (collecting) "READY" else "IDLE"}")
        OutlinedTextField(task, { task = it }, label = { Text("Task") }); OutlinedTextField(objectName, { objectName = it }, label = { Text("Object") })
        Button(onClick = { if (active) message = "ACTIVE Episode를 먼저 END 또는 CANCEL 하세요." else collecting = !collecting }) { Text(if (collecting) "DATA COLLECTION END" else "DATA COLLECTION START") }
        Button(enabled = collecting && !active && task.isNotBlank() && objectName.isNotBlank(), onClick = { active = true }) { Text("EPISODE START") }
        Button(enabled = active, onClick = { active = false }) { Text("EPISODE END") }; Button(enabled = active, onClick = { active = false }) { Text("EPISODE CANCEL") }; Text(message)
    }
}
