package com.ssafy.s15p21a206.tiger

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.ssafy.s15p21a206.tiger.ui.theme.TigerTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { TigerTheme { TigerApp() } }
    }
}
