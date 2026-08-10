package com.example.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.data.McpttRepository
import com.example.sip.engine.CallSessionState
import com.example.sip.engine.FloorState
import com.example.sip.engine.McpttSipStack
import com.example.sip.engine.RegistrationState
import com.example.sip.engine.RtpAudioEngine
import com.example.sip.model.LogDirection
import com.example.sip.model.SipProfile
import com.example.sip.model.SipTrafficLog
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class McpttViewModel(application: Application) : AndroidViewModel(application) {
    private val repository = McpttRepository(application)
    val sipStack = McpttSipStack()
    val audioEngine = RtpAudioEngine()

    val sipProfile: StateFlow<SipProfile> = repository.sipProfile
    val registrationState: StateFlow<RegistrationState> = sipStack.registrationState
    val callState: StateFlow<CallSessionState> = sipStack.callState
    val floorState: StateFlow<FloorState> = sipStack.floorState
    val activeSpeaker: StateFlow<String?> = sipStack.activeSpeaker
    val micAudioLevel: StateFlow<Float> = audioEngine.micAudioLevel

    val allLogs: StateFlow<List<SipTrafficLog>> = repository.logs

    private val _logFilter = MutableStateFlow("ALL")
    val logFilter: StateFlow<String> = _logFilter.asStateFlow()

    val filteredLogs: StateFlow<List<SipTrafficLog>> = combine(allLogs, logFilter) { logs, filter ->
        when (filter) {
            "TX" -> logs.filter { it.direction == LogDirection.OUTBOUND }
            "RX" -> logs.filter { it.direction == LogDirection.INBOUND }
            "MCPTT" -> logs.filter { it.isMcpttTagged }
            "ERRORS" -> logs.filter { it.hasError }
            else -> logs
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    val presetGroups = listOf(
        "sip:mcptt_group_fire@ims.mnc070.mcc901.3gppnetwork.org" to "Fire Response Group",
        "sip:mcptt_group_police@ims.mnc070.mcc901.3gppnetwork.org" to "Tactical Police Alpha",
        "sip:mcptt_group_medical@ims.mnc070.mcc901.3gppnetwork.org" to "EMS Rescue Command",
        "sip:mcptt_group_emergency@ims.mnc070.mcc901.3gppnetwork.org" to "National Emergency Broadcast"
    )

    init {
        val currentProfile = repository.sipProfile.value
        audioEngine.init(currentProfile.localRtpPort)
        sipStack.start(getApplication(), currentProfile)

        viewModelScope.launch {
            sipStack.trafficLogs.collect { log ->
                repository.addLog(log)
            }
        }
    }

    fun updateProfile(profile: SipProfile) {
        repository.saveProfile(profile)
        audioEngine.init(profile.localRtpPort)
        sipStack.updateProfile(getApplication(), profile)
    }

    fun registerSip() {
        sipStack.register()
    }

    fun subscribeGroup(groupUri: String = sipProfile.value.targetGroup) {
        sipStack.subscribeGroup(groupUri)
    }

    fun selectTargetGroup(groupUri: String) {
        val updated = sipProfile.value.copy(targetGroup = groupUri)
        updateProfile(updated)
    }

    fun onPttPressed() {
        audioEngine.playGrantTone()
        sipStack.requestFloor()
        audioEngine.startMicrophoneTransmission(
            destHost = sipProfile.value.pcscfHost,
            destPort = sipProfile.value.localRtpPort
        )
    }

    fun onPttReleased() {
        audioEngine.playReleaseTone()
        sipStack.releaseFloor()
        audioEngine.stopMicrophoneTransmission()
    }

    fun endCallSession() {
        audioEngine.stopMicrophoneTransmission()
        audioEngine.stopAudioPlayback()
        sipStack.endCall()
    }

    fun triggerEmergencyAlert(customNote: String = "EMERGENCY SOS ALERT") {
        audioEngine.playEmergencyTone()
        sipStack.sendEmergencyAlert(customNote)
    }

    fun sendTextMessage(targetUri: String, text: String) {
        sipStack.sendSipMessageText(targetUri, text)
    }

    fun setLogFilter(filter: String) {
        _logFilter.value = filter
    }

    fun clearTrafficLogs() {
        repository.clearLogs()
    }

    fun simulateIncomingMcpttInvite() {
        val simUser = "sip:mcptt_unit02@ims.mnc070.mcc901.3gppnetwork.org"
        val simTarget = sipProfile.value.targetGroup
        val rawSip = """
            INVITE $simTarget SIP/2.0
            Via: SIP/2.0/UDP ${sipProfile.value.pcscfHost}:5060;branch=z9hG4bK-sim123
            From: <$simUser>;tag=sim9988
            To: <$simTarget>
            Call-ID: sim-call-${System.currentTimeMillis()}@ims.mnc070.mcc901.3gppnetwork.org
            CSeq: 100 INVITE
            Contact: <$simUser>;+g.3gpp.mcptt
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require
            User-Agent: ${sipProfile.value.userAgent}
            Content-Type: application/sdp
            Content-Length: 180
            
            v=0
            o=sim_user 1234 1234 IN IP4 ${sipProfile.value.pcscfHost}
            s=Simulated Call
            c=IN IP4 ${sipProfile.value.pcscfHost}
            m=audio 40002 RTP/AVP 0
        """.trimIndent().replace("\n", "\r\n")

        sipStack.injectSimulatedPacket(rawSip)
    }

    override fun onCleared() {
        super.onCleared()
        audioEngine.close()
        sipStack.stop()
    }
}
