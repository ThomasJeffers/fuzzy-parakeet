package com.example.ui.screens

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.McpttViewModel
import com.example.ui.theme.HighDensityBackground
import com.example.ui.theme.HighDensityBorder
import com.example.ui.theme.HighDensityNavy
import com.example.ui.theme.HighDensityPrimary
import com.example.ui.theme.HighDensitySecondary
import com.example.ui.theme.HighDensitySurface
import com.example.ui.theme.HighDensityTextPrimary
import com.example.ui.theme.HighDensityTextSecondary

@Composable
fun SettingsScreen(viewModel: McpttViewModel) {
    val context = LocalContext.current
    val currentProfile by viewModel.sipProfile.collectAsState()

    var displayName by remember(currentProfile) { mutableStateOf(currentProfile.displayName) }
    var mcpttId by remember(currentProfile) { mutableStateOf(currentProfile.mcpttId) }
    var realm by remember(currentProfile) { mutableStateOf(currentProfile.realm) }
    var password by remember(currentProfile) { mutableStateOf(currentProfile.password) }
    var pcscfHost by remember(currentProfile) { mutableStateOf(currentProfile.pcscfHost) }
    var pcscfPort by remember(currentProfile) { mutableStateOf(currentProfile.pcscfPort.toString()) }
    var mcpttAsHost by remember(currentProfile) { mutableStateOf(currentProfile.mcpttAsHost) }
    var mcpttAsPort by remember(currentProfile) { mutableStateOf(currentProfile.mcpttAsPort.toString()) }
    var userAgent by remember(currentProfile) { mutableStateOf(currentProfile.userAgent) }
    var localSipPort by remember(currentProfile) { mutableStateOf(currentProfile.localSipPort.toString()) }
    var targetGroup by remember(currentProfile) { mutableStateOf(currentProfile.targetGroup) }
    var includeMcpttTags by remember(currentProfile) { mutableStateOf(currentProfile.includeMcpttTags) }
    var autoGrantFloor by remember(currentProfile) { mutableStateOf(currentProfile.autoGrantFloor) }

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(HighDensityBackground)
            .padding(16.dp)
            .verticalScroll(scrollState)
    ) {
        Text(
            text = "MCPTT & IMS CONFIGURATION",
            fontSize = 15.sp,
            fontWeight = FontWeight.Bold,
            color = HighDensityNavy,
            fontFamily = FontFamily.Monospace
        )
        Text(
            text = "Configure parameters for Open5GS EPC/IMS, Kamailio S-CSCF & Python AS",
            fontSize = 11.sp,
            color = HighDensityTextSecondary
        )

        Spacer(modifier = Modifier.height(12.dp))

        // KAMAILIO INTERCEPTION ADVISORY CARD
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = HighDensitySurface),
            border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityNavy),
            shape = RoundedCornerShape(12.dp)
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.CheckCircle, contentDescription = null, tint = HighDensitySecondary, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = "KAMAILIO S-CSCF MATCHING ACTIVE",
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        color = HighDensitySecondary,
                        fontFamily = FontFamily.Monospace
                    )
                }
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "Requests route to Python MCPTT AS if: (1) R-URI / To user starts with 'mcptt', 'group', or 'chat', (2) User-Agent contains 'MCOP|MCPTT' (e.g. MCPTT-Android-PoC/1.0), or (3) Content-Type/Contact has 'mcptt'.",
                    fontSize = 11.sp,
                    color = HighDensityTextPrimary
                )
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // PRESETS BUTTONS
        Text("QUICK ENVIRONMENT PRESETS", fontSize = 11.sp, color = HighDensityTextSecondary, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
        Spacer(modifier = Modifier.height(6.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(
                onClick = {
                    pcscfHost = "172.22.0.21"
                    pcscfPort = "5060"
                    mcpttAsHost = "172.30.104.240"
                    mcpttAsPort = "5060"
                    realm = "ims.mnc070.mcc901.3gppnetwork.org"
                    userAgent = "MCPTT-Android-PoC/1.0"
                    mcpttId = "sip:mcptt_user1@ims.mnc070.mcc901.3gppnetwork.org"
                    targetGroup = "sip:mcptt_group_fire@ims.mnc070.mcc901.3gppnetwork.org"
                },
                colors = ButtonDefaults.buttonColors(containerColor = HighDensitySurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityBorder),
                modifier = Modifier.weight(1f)
            ) {
                Text("Lab IMS 172.22.0.21", fontSize = 10.sp, color = HighDensityTextPrimary, fontWeight = FontWeight.Bold)
            }

            Button(
                onClick = {
                    pcscfHost = "172.30.104.240"
                    pcscfPort = "5060"
                    mcpttAsHost = "172.30.104.240"
                    mcpttAsPort = "5060"
                    realm = "ims.mnc070.mcc901.3gppnetwork.org"
                    userAgent = "MCPTT-Android-PoC/1.0"
                },
                colors = ButtonDefaults.buttonColors(containerColor = HighDensitySurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityBorder),
                modifier = Modifier.weight(1f)
            ) {
                Text("Lab VM1 172.30.104.240", fontSize = 10.sp, color = HighDensityTextPrimary, fontWeight = FontWeight.Bold)
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // INPUT FIELDS
        OutlinedField("Display Name / Rank", displayName) { displayName = it }
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedField("MCPTT User Identity (IMPU)", mcpttId) { mcpttId = it }
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedField("IMS Domain / Realm", realm) { realm = it }
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedField("SIP User-Agent Header", userAgent) { userAgent = it }
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedField("SIP Password", password) { password = it }
        Spacer(modifier = Modifier.height(8.dp))

        Text("SIP PROXY / P-CSCF (IMS Entry Point)", fontSize = 11.sp, color = HighDensityNavy, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
        Spacer(modifier = Modifier.height(4.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Box(modifier = Modifier.weight(2f)) {
                OutlinedField("P-CSCF Host IP", pcscfHost) { pcscfHost = it }
            }
            Box(modifier = Modifier.weight(1f)) {
                OutlinedField("P-CSCF Port", pcscfPort) { pcscfPort = it }
            }
        }

        Spacer(modifier = Modifier.height(10.dp))
        Text("MCPTT APPLICATION SERVER (Python AS - Direct Test)", fontSize = 11.sp, color = HighDensityNavy, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
        Spacer(modifier = Modifier.height(4.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Box(modifier = Modifier.weight(2f)) {
                OutlinedField("MCPTT AS IP", mcpttAsHost) { mcpttAsHost = it }
            }
            Box(modifier = Modifier.weight(1f)) {
                OutlinedField("AS Port", mcpttAsPort) { mcpttAsPort = it }
            }
        }

        Spacer(modifier = Modifier.height(10.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Box(modifier = Modifier.weight(1f)) {
                OutlinedField("Local App SIP Port", localSipPort) { localSipPort = it }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))
        OutlinedField("Default Target Talkgroup URI", targetGroup) { targetGroup = it }

        Spacer(modifier = Modifier.height(12.dp))

        // TOGGLES
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = HighDensitySurface),
            border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityBorder),
            shape = RoundedCornerShape(12.dp)
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column {
                        Text("Inject +g.3gpp.mcptt Tags", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = HighDensityTextPrimary)
                        Text("Adds feature tag to Contact / Accept-Contact", fontSize = 11.sp, color = HighDensityTextSecondary)
                    }
                    Switch(
                        checked = includeMcpttTags,
                        onCheckedChange = { includeMcpttTags = it },
                        colors = SwitchDefaults.colors(checkedThumbColor = HighDensityNavy)
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider(color = HighDensityBorder)
                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Auto-Grant Floor (Debug Local Fake)", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = HighDensityTextPrimary)
                        Text("Off = Only real network 200/INFO responses drive Floor state", fontSize = 11.sp, color = HighDensityTextSecondary)
                    }
                    Switch(
                        checked = autoGrantFloor,
                        onCheckedChange = { autoGrantFloor = it },
                        colors = SwitchDefaults.colors(checkedThumbColor = HighDensityNavy)
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(20.dp))

        // SAVE BUTTON
        Button(
            onClick = {
                val updated = currentProfile.copy(
                    displayName = displayName,
                    mcpttId = mcpttId,
                    realm = realm,
                    password = password,
                    pcscfHost = pcscfHost,
                    pcscfPort = pcscfPort.toIntOrNull() ?: 5060,
                    mcpttAsHost = mcpttAsHost,
                    mcpttAsPort = mcpttAsPort.toIntOrNull() ?: 5060,
                    userAgent = userAgent,
                    localSipPort = localSipPort.toIntOrNull() ?: 5062,
                    targetGroup = targetGroup,
                    includeMcpttTags = includeMcpttTags,
                    autoGrantFloor = autoGrantFloor
                )
                viewModel.updateProfile(updated)
                Toast.makeText(context, "SIP Settings Saved & Restarted Engine", Toast.LENGTH_SHORT).show()
            },
            colors = ButtonDefaults.buttonColors(containerColor = HighDensityNavy),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("save_settings_button")
        ) {
            Icon(Icons.Default.Save, contentDescription = null, tint = Color.White)
            Spacer(modifier = Modifier.width(8.dp))
            Text("SAVE CONFIGURATION & RESTART SIP", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 13.sp)
        }
    }
}

@Composable
fun OutlinedField(label: String, value: String, onValueChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label, fontSize = 12.sp, color = HighDensityTextSecondary) },
        modifier = Modifier.fillMaxWidth(),
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = HighDensitySurface,
            unfocusedContainerColor = HighDensitySurface,
            focusedBorderColor = HighDensityNavy,
            unfocusedBorderColor = HighDensityBorder,
            focusedTextColor = HighDensityTextPrimary,
            unfocusedTextColor = HighDensityTextPrimary
        ),
        singleLine = true
    )
}

