package com.example.sip.model

data class SipProfile(
    val displayName: String = "MCPTT UE-1",
    val mcpttId: String = "sip:mcptt_user1@ims.mnc070.mcc901.3gppnetwork.org",
    val realm: String = "ims.mnc070.mcc901.3gppnetwork.org",
    val password: String = "password123",
    val pcscfHost: String = "172.22.0.21",
    val pcscfPort: Int = 5060,
    val mcpttAsHost: String = "172.30.104.240",
    val mcpttAsPort: Int = 5060,
    val userAgent: String = "MCPTT-Android-PoC/1.0",
    val localSipPort: Int = 5062,
    val localRtpPort: Int = 40000,
    val targetGroup: String = "sip:mcptt_group_fire@ims.mnc070.mcc901.3gppnetwork.org",
    val emergencyGroup: String = "sip:mcptt_group_emergency@ims.mnc070.mcc901.3gppnetwork.org",
    val transport: String = "UDP",
    val autoRegister: Boolean = true,
    val includeMcpttTags: Boolean = true,
    val autoGrantFloor: Boolean = false
)
