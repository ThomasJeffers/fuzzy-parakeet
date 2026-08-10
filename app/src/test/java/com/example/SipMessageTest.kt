package com.example

import com.example.sip.model.SipMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SipMessageTest {

    @Test
    fun testParseMcpttInvite() {
        val rawSip = """
            INVITE sip:mcptt_group_fire@ims.mnc001.mcc001.3gppnetwork.org SIP/2.0
            Via: SIP/2.0/UDP 192.168.1.50:5062;rport;branch=z9hG4bK-12345
            From: <sip:mcptt_user1@ims.mnc001.mcc001.3gppnetwork.org>;tag=abc
            To: <sip:mcptt_group_fire@ims.mnc001.mcc001.3gppnetwork.org>
            Call-ID: call-998877@192.168.1.50
            CSeq: 1 INVITE
            Contact: <sip:mcptt_user1@192.168.1.50:5062>;+g.3gpp.mcptt
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require
            Content-Type: application/sdp
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        val message = SipMessage.parse(rawSip)

        assertEquals("INVITE", message.method)
        assertEquals("call-998877@192.168.1.50", message.callId)
        assertTrue(message.isMcpttTagged)
        assertEquals("<sip:mcptt_user1@192.168.1.50:5062>;+g.3gpp.mcptt", message.contact)
    }

    @Test
    fun testFloorControlParsing() {
        val rawFloorGrant = """
            INFO sip:mcptt_group_fire@ims.mnc001.mcc001.3gppnetwork.org SIP/2.0
            Via: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK-777
            From: <sip:mcptt_as@ims.mnc001.mcc001.3gppnetwork.org>;tag=as1
            To: <sip:mcptt_user1@ims.mnc001.mcc001.3gppnetwork.org>
            Call-ID: call-998877@192.168.1.50
            CSeq: 2 INFO
            Content-Type: application/mcptt-floor-control+xml
            Content-Length: 30
            
            Action=floor-granted
        """.trimIndent().replace("\n", "\r\n")

        val message = SipMessage.parse(rawFloorGrant)

        assertEquals("INFO", message.method)
        assertEquals("GRANTED", message.floorControlState)
    }
}
