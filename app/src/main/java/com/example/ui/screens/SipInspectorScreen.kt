package com.example.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.sip.model.LogDirection
import com.example.sip.model.SipTrafficLog
import com.example.ui.McpttViewModel
import com.example.ui.theme.HighDensityBackground
import com.example.ui.theme.HighDensityBorder
import com.example.ui.theme.HighDensityEmergency
import com.example.ui.theme.HighDensityNavy
import com.example.ui.theme.HighDensityPrimary
import com.example.ui.theme.HighDensitySecondary
import com.example.ui.theme.HighDensitySurface
import com.example.ui.theme.HighDensityTerminalBg
import com.example.ui.theme.HighDensityTextPrimary
import com.example.ui.theme.HighDensityTextSecondary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun SipInspectorScreen(viewModel: McpttViewModel) {
    val context = LocalContext.current
    val logs by viewModel.filteredLogs.collectAsState()
    val currentFilter by viewModel.logFilter.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(HighDensityBackground)
            .padding(12.dp)
    ) {
        // TOP CONTROLS & FILTER CHIPS
        Text(
            text = "LIVE SIP TRAFFIC INSPECTOR",
            fontSize = 15.sp,
            fontWeight = FontWeight.Bold,
            color = HighDensityNavy,
            fontFamily = FontFamily.Monospace
        )
        Text(
            text = "Monitors raw SIP datagrams sent/received with +g.3gpp.mcptt headers",
            fontSize = 11.sp,
            color = HighDensityTextSecondary
        )

        Spacer(modifier = Modifier.height(10.dp))

        // FILTER CHIPS ROW
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            val filters = listOf("ALL", "TX", "RX", "MCPTT", "ERRORS")
            filters.forEach { f ->
                FilterChip(
                    selected = currentFilter == f,
                    onClick = { viewModel.setLogFilter(f) },
                    label = { Text(f, fontSize = 11.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = HighDensityNavy,
                        selectedLabelColor = Color.White,
                        containerColor = HighDensitySurface,
                        labelColor = HighDensityTextPrimary
                    ),
                    modifier = Modifier.testTag("filter_$f")
                )
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // ACTION BUTTONS
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Button(
                onClick = { viewModel.simulateIncomingMcpttInvite() },
                colors = ButtonDefaults.buttonColors(containerColor = HighDensitySurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityNavy),
                modifier = Modifier.testTag("simulate_packet_button")
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, tint = HighDensityNavy, modifier = Modifier.size(14.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("TEST INCOMING INVITE", fontSize = 11.sp, color = HighDensityNavy, fontWeight = FontWeight.Bold)
            }

            IconButton(
                onClick = { viewModel.clearTrafficLogs() },
                modifier = Modifier.testTag("clear_logs_button")
            ) {
                Icon(Icons.Default.Delete, contentDescription = "Clear Logs", tint = HighDensityEmergency)
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // LOG LIST
        if (logs.isEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text(
                    text = "NO SIP TRAFFIC LOGGED",
                    color = HighDensityTextSecondary,
                    fontSize = 14.sp,
                    fontFamily = FontFamily.Monospace
                )
                Text(
                    text = "Tap REGISTER or PTT button to transmit packets",
                    color = HighDensityTextSecondary,
                    fontSize = 11.sp
                )
            }
        } else {
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxSize()
            ) {
                items(logs, key = { it.id }) { log ->
                    SipPacketCard(log = log, onCopy = { text ->
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        val clip = ClipData.newPlainText("SIP Packet", text)
                        clipboard.setPrimaryClip(clip)
                        Toast.makeText(context, "Copied Raw SIP Packet to Clipboard", Toast.LENGTH_SHORT).show()
                    })
                }
            }
        }
    }
}

@Composable
fun SipPacketCard(log: SipTrafficLog, onCopy: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }

    val directionColor = if (log.direction == LogDirection.OUTBOUND) HighDensityNavy else HighDensitySecondary
    val timeStr = SimpleDateFormat("HH:mm:ss.SSS", Locale.getDefault()).format(Date(log.timestamp))

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded }
            .testTag("sip_card_${log.id}"),
        colors = CardDefaults.cardColors(containerColor = HighDensitySurface),
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            if (log.hasError) HighDensityEmergency else if (log.isMcpttTagged) HighDensityNavy else HighDensityBorder
        ),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = if (log.direction == LogDirection.OUTBOUND) Icons.Default.ArrowForward else Icons.Default.ArrowBack,
                        contentDescription = null,
                        tint = directionColor,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = if (log.direction == LogDirection.OUTBOUND) "TX" else "RX",
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        color = directionColor,
                        fontFamily = FontFamily.Monospace
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = log.methodOrResponse,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = HighDensityTextPrimary,
                        fontFamily = FontFamily.Monospace
                    )
                }

                Text(
                    text = timeStr,
                    fontSize = 10.sp,
                    color = HighDensityTextSecondary,
                    fontFamily = FontFamily.Monospace
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = log.remoteAddress,
                fontSize = 11.sp,
                color = HighDensityTextSecondary,
                fontFamily = FontFamily.Monospace
            )

            if (log.isMcpttTagged) {
                Spacer(modifier = Modifier.height(4.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(HighDensityNavy.copy(alpha = 0.1f))
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = "+g.3gpp.mcptt MATCHED",
                        fontSize = 10.sp,
                        color = HighDensityNavy,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )
                }
            }

            // EXPANDED RAW SIP TEXT VIEWER
            if (expanded) {
                Spacer(modifier = Modifier.height(8.dp))
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = HighDensityTerminalBg),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Column(modifier = Modifier.padding(8.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "RAW SIP DATAGRAM",
                                fontSize = 10.sp,
                                color = Color.Gray,
                                fontFamily = FontFamily.Monospace
                            )
                            IconButton(
                                onClick = { onCopy(log.rawPacket) },
                                modifier = Modifier.size(24.dp)
                            ) {
                                Icon(
                                    Icons.Default.ContentCopy,
                                    contentDescription = "Copy",
                                    tint = Color.White,
                                    modifier = Modifier.size(14.dp)
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = log.rawPacket,
                            fontSize = 11.sp,
                            color = Color(0xFF4ADE80),
                            fontFamily = FontFamily.Monospace,
                            lineHeight = 14.sp
                        )
                    }
                }
            }
        }
    }
}

