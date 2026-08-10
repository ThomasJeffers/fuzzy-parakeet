package com.example

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.McpttViewModel
import com.example.ui.screens.GroupsScreen
import com.example.ui.screens.SettingsScreen
import com.example.ui.screens.SipInspectorScreen
import com.example.ui.screens.TacticalPttScreen
import com.example.ui.theme.HighDensityBackground
import com.example.ui.theme.HighDensityNavy
import com.example.ui.theme.HighDensitySurface
import com.example.ui.theme.HighDensityTextSecondary
import com.example.ui.theme.MyApplicationTheme

class MainActivity : ComponentActivity() {
    private val viewModel: McpttViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MyApplicationTheme {
                MainAppScreen(viewModel = viewModel)
            }
        }
    }
}

data class NavItem(val label: String, val icon: ImageVector, val tag: String)

@Composable
fun MainAppScreen(viewModel: McpttViewModel) {
    var selectedTab by remember { mutableIntStateOf(0) }

    val navItems = listOf(
        NavItem("PTT Radio", Icons.Default.Radio, "tab_ptt"),
        NavItem("SIP Inspector", Icons.Default.Code, "tab_inspector"),
        NavItem("Talkgroups", Icons.Default.Group, "tab_groups"),
        NavItem("Settings", Icons.Default.Settings, "tab_settings")
    )

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = HighDensityBackground,
        bottomBar = {
            NavigationBar(
                containerColor = HighDensitySurface,
                tonalElevation = 8.dp
            ) {
                navItems.forEachIndexed { index, item ->
                    val isSelected = selectedTab == index
                    NavigationBarItem(
                        selected = isSelected,
                        onClick = { selectedTab = index },
                        label = {
                            Text(
                                text = item.label,
                                fontSize = 10.sp,
                                fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                color = if (isSelected) HighDensityNavy else HighDensityTextSecondary
                            )
                        },
                        icon = {
                            Icon(
                                imageVector = item.icon,
                                contentDescription = item.label,
                                tint = if (isSelected) HighDensityNavy else HighDensityTextSecondary,
                                modifier = Modifier.size(20.dp)
                            )
                        },
                        colors = NavigationBarItemDefaults.colors(
                            indicatorColor = HighDensityNavy.copy(alpha = 0.12f)
                        ),
                        modifier = Modifier.testTag(item.tag)
                    )
                }
            }
        }
    ) { innerPadding ->
        Box(modifier = Modifier.padding(innerPadding)) {
            when (selectedTab) {
                0 -> TacticalPttScreen(viewModel = viewModel)
                1 -> SipInspectorScreen(viewModel = viewModel)
                2 -> GroupsScreen(viewModel = viewModel)
                3 -> SettingsScreen(viewModel = viewModel)
            }
        }
    }
}

