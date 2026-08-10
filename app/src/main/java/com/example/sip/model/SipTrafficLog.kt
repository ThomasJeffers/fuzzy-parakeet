package com.example.sip.model

enum class LogDirection {
    OUTBOUND, // Sent from UE
    INBOUND   // Received from S-CSCF / P-CSCF / AS
}

enum class LogType {
    SIP_REGISTER,
    SIP_SUBSCRIBE,
    SIP_INVITE,
    SIP_MESSAGE,
    SIP_INFO,
    SIP_BYE,
    SIP_ACK,
    SIP_RESPONSE,
    SYSTEM_EVENT
}

data class SipTrafficLog(
    val id: String = java.util.UUID.randomUUID().toString(),
    val timestamp: Long = System.currentTimeMillis(),
    val direction: LogDirection,
    val type: LogType,
    val methodOrResponse: String,
    val remoteAddress: String,
    val summary: String,
    val rawPacket: String,
    val isMcpttTagged: Boolean = false,
    val hasError: Boolean = false
)
