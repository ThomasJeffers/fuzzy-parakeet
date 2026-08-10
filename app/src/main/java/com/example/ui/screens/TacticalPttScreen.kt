package com.example.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicNone
import androidx.compose.material.icons.filled.PhoneInTalk
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.example.sip.engine.CallSessionState
import com.example.sip.engine.FloorState
import com.example.sip.engine.RegistrationState
import com.example.ui.McpttViewModel
import com.example.ui.theme.HighDensityBackground
import com.example.ui.theme.HighDensityBorder
import com.example.ui.theme.HighDensityEmergency
import com.example.ui.theme.HighDensityNavy
import com.example.ui.theme.HighDensityPrimary
import com.example.ui.theme.HighDensityPttRed
import com.example.ui.theme.HighDensityPttRedDark
import com.example.ui.theme.HighDensitySecondary
import com.example.ui.theme.HighDensitySurface
import com.example.ui.theme.HighDensityTextPrimary
import com.example.ui.theme.HighDensityTextSecondary
import com.example.ui.theme.HighDensityWarning

@Composable
fun TacticalPttScreen(viewModel: McpttViewModel) {
    val context = LocalContext.current
    val registrationState by viewModel.registrationState.collectAsState()
    val callState by viewModel.callState.collectAsState()
    val floorState by viewModel.floorState.collectAsState()
    val activeSpeaker by viewModel.activeSpeaker.collectAsState()
    val profile by viewModel.sipProfile.collectAsState()
    val audioLevel by viewModel.micAudioLevel.collectAsState()

    var isPttHeld by remember { mutableStateOf(false) }
    var quickMsgText by remember { mutableStateOf("") }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted -> }

    LaunchedEffect(Unit) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val pulseScale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.08f,
        animationSpec = infiniteRepeatable(
            animation = tween(800, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulseScale"
    )

    val pttColor by animateColorAsState(
        targetValue = when (floorState) {
            FloorState.GRANTED -> HighDensitySecondary
            FloorState.REQUESTING -> HighDensityWarning
            FloorState.TAKEN -> Color.Gray
            else -> if (isPttHeld) HighDensityPttRedDark else HighDensityPttRed
        },
        label = "pttColor"
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(HighDensityBackground)
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        // TOP: Network & IMS Status Banner (Header Card)
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .testTag("ims_status_card"),
            colors = CardDefaults.cardColors(containerColor = HighDensityNavy),
            shape = RoundedCornerShape(12.dp)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(14.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Radio,
                        contentDescription = "Radio Status",
                        tint = when (registrationState) {
                            RegistrationState.REGISTERED -> Color(0xFF4ADE80)
                            RegistrationState.REGISTERING -> HighDensityWarning
                            else -> HighDensityEmergency
                        },
                        modifier = Modifier.size(24.dp)
                    )
                    Spacer(modifier = Modifier.width(10.dp))
                    Column {
                        Text(
                            text = "APP SIP REGISTERED • 4G/VoLTE",
                            fontSize = 11.sp,
                            color = Color.White.copy(alpha = 0.8f),
                            fontWeight = FontWeight.Bold,
                            fontFamily = FontFamily.Monospace
                        )
                        Text(
                            text = when (registrationState) {
                                RegistrationState.REGISTERED -> "MCPTT PoC Client"
                                RegistrationState.REGISTERING -> "CONNECTING TO S-CSCF..."
                                RegistrationState.FAILED -> "REGISTRATION FAILED"
                                else -> "UNREGISTERED (App SIP Stack)"
                            },
                            fontSize = 14.sp,
                            color = Color.White,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }

                if (registrationState != RegistrationState.REGISTERED) {
                    Button(
                        onClick = { viewModel.registerSip() },
                        colors = ButtonDefaults.buttonColors(containerColor = Color.White),
                        modifier = Modifier.testTag("register_button")
                    ) {
                        Text("REGISTER", fontSize = 11.sp, color = HighDensityNavy, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // CENTER TOP: Target Group Card
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = HighDensitySurface),
            border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityBorder),
            shape = RoundedCornerShape(16.dp)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(14.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "ACTIVE CHANNEL",
                        fontSize = 10.sp,
                        color = HighDensityTextSecondary,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = profile.targetGroup.substringAfter("sip:").substringBefore("@"),
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold,
                        color = HighDensityTextPrimary
                    )
                    Text(
                        text = "UA: ${profile.userAgent}",
                        fontSize = 10.sp,
                        color = HighDensityNavy,
                        fontFamily = FontFamily.Monospace
                    )
                }

                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(12.dp))
                        .background(HighDensityNavy.copy(alpha = 0.1f))
                        .padding(horizontal = 10.dp, vertical = 6.dp)
                ) {
                    Text(
                        text = "GROUP 104",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = HighDensityNavy
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // FLOOR & SPEAKER STATUS BANNER
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = when (floorState) {
                    FloorState.GRANTED -> HighDensitySecondary.copy(alpha = 0.15f)
                    FloorState.REQUESTING -> HighDensityWarning.copy(alpha = 0.15f)
                    FloorState.TAKEN -> HighDensityEmergency.copy(alpha = 0.15f)
                    else -> HighDensitySurface
                }
            ),
            border = androidx.compose.foundation.BorderStroke(
                1.dp,
                when (floorState) {
                    FloorState.GRANTED -> HighDensitySecondary
                    FloorState.REQUESTING -> HighDensityWarning
                    FloorState.TAKEN -> HighDensityEmergency
                    else -> HighDensityBorder
                }
            ),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(14.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = when (floorState) {
                        FloorState.GRANTED -> "● FLOOR GRANTED - TRANSMITTING"
                        FloorState.REQUESTING -> "▲ REQUESTING FLOOR..."
                        FloorState.TAKEN -> "■ FLOOR TAKEN"
                        else -> "Floor Idle / Ready"
                    },
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Bold,
                    color = when (floorState) {
                        FloorState.GRANTED -> HighDensitySecondary
                        FloorState.REQUESTING -> HighDensityWarning
                        FloorState.TAKEN -> HighDensityEmergency
                        else -> HighDensityTextSecondary
                    },
                    fontFamily = FontFamily.Monospace
                )

                if (activeSpeaker != null) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Active Speaker: $activeSpeaker",
                        fontSize = 12.sp,
                        color = HighDensityTextPrimary,
                        fontWeight = FontWeight.Bold
                    )
                }

                if (floorState == FloorState.GRANTED || audioLevel > 0f) {
                    Spacer(modifier = Modifier.height(8.dp))
                    AudioMeterBar(audioLevel = audioLevel)
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // CENTER: GIANT PTT PUSH-TO-TALK BUTTON
        Box(
            modifier = Modifier
                .size(200.dp)
                .scale(if (isPttHeld && floorState == FloorState.GRANTED) pulseScale else 1f)
                .clip(CircleShape)
                .background(pttColor)
                .border(10.dp, HighDensitySurface, CircleShape)
                .testTag("ptt_button")
                .pointerInput(Unit) {
                    detectTapGestures(
                        onPress = {
                            isPttHeld = true
                            viewModel.onPttPressed()
                            tryAwaitRelease()
                            isPttHeld = false
                            viewModel.onPttReleased()
                        }
                    )
                },
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    imageVector = if (isPttHeld) Icons.Default.Mic else Icons.Default.MicNone,
                    contentDescription = "Push To Talk",
                    tint = Color.White,
                    modifier = Modifier.size(56.dp)
                )
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = when (floorState) {
                        FloorState.GRANTED -> "SPEAK NOW"
                        FloorState.REQUESTING -> "WAIT..."
                        else -> "PUSH TO TALK"
                    },
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Black,
                    color = Color.White,
                    fontFamily = FontFamily.SansSerif
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // CALL CONTROL BUTTONS
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceEvenly
        ) {
            Button(
                onClick = { viewModel.subscribeGroup() },
                colors = ButtonDefaults.buttonColors(containerColor = HighDensitySurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, HighDensityNavy),
                modifier = Modifier.testTag("subscribe_button")
            ) {
                Text("SUBSCRIBE", color = HighDensityNavy, fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }

            if (callState == CallSessionState.CONNECTED) {
                Button(
                    onClick = { viewModel.endCallSession() },
                    colors = ButtonDefaults.buttonColors(containerColor = HighDensityEmergency),
                    modifier = Modifier.testTag("end_call_button")
                ) {
                    Icon(Icons.Default.CallEnd, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("END SESSION", fontSize = 11.sp, fontWeight = FontWeight.Bold)
                }
            } else {
                Button(
                    onClick = { viewModel.sipStack.initiateMcpttCall() },
                    colors = ButtonDefaults.buttonColors(containerColor = HighDensityNavy),
                    modifier = Modifier.testTag("initiate_call_button")
                ) {
                    Icon(Icons.Default.PhoneInTalk, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("START CALL", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // QUICK MESSAGE BROADCAST & EMERGENCY SOS
        Column(modifier = Modifier.fillMaxWidth()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                OutlinedTextField(
                    value = quickMsgText,
                    onValueChange = { quickMsgText = it },
                    placeholder = { Text("Send SIP MESSAGE (+g.3gpp.mcptt)", fontSize = 12.sp, color = HighDensityTextSecondary) },
                    modifier = Modifier
                        .weight(1f)
                        .testTag("quick_msg_input"),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = HighDensitySurface,
                        unfocusedContainerColor = HighDensitySurface,
                        focusedBorderColor = HighDensityNavy,
                        unfocusedBorderColor = HighDensityBorder
                    ),
                    singleLine = true
                )
                Spacer(modifier = Modifier.width(8.dp))
                IconButton(
                    onClick = {
                        if (quickMsgText.isNotBlank()) {
                            viewModel.sendTextMessage(profile.targetGroup, quickMsgText)
                            quickMsgText = ""
                        }
                    },
                    modifier = Modifier
                        .background(HighDensityNavy, RoundedCornerShape(8.dp))
                        .testTag("send_msg_button")
                ) {
                    Icon(Icons.Default.Send, contentDescription = "Send", tint = Color.White)
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // EMERGENCY BROADCAST BUTTON
            Button(
                onClick = { viewModel.triggerEmergencyAlert("EMERGENCY SOS ALERT") },
                colors = ButtonDefaults.buttonColors(containerColor = HighDensityEmergency),
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("emergency_sos_button")
            ) {
                Icon(Icons.Default.Warning, contentDescription = "SOS", tint = Color.White)
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "EMERGENCY BROADCAST (+g.3gpp.mcptt.emergency)",
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp
                )
            }
        }
    }
}

@Composable
fun AudioMeterBar(audioLevel: Float) {
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(10.dp)
            .clip(RoundedCornerShape(5.dp))
            .background(HighDensityBorder)
    ) {
        val activeWidth = size.width * audioLevel.coerceIn(0.05f, 1f)
        drawRect(
            color = if (audioLevel > 0.7f) HighDensityEmergency else HighDensitySecondary,
            size = androidx.compose.ui.geometry.Size(activeWidth, size.height)
        )
    }
}

