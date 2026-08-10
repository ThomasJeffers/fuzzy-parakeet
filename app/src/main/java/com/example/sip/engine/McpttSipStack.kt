package com.example.sip.engine

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.util.Log
import com.example.sip.model.LogDirection
import com.example.sip.model.LogType
import com.example.sip.model.SipMessage
import com.example.sip.model.SipProfile
import com.example.sip.model.SipTrafficLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.security.MessageDigest
import java.util.UUID

enum class RegistrationState {
    UNREGISTERED,
    REGISTERING,
    REGISTERED,
    FAILED
}

enum class CallSessionState {
    IDLE,
    CALLING,
    CONNECTED,
    DISCONNECTING
}

enum class FloorState {
    IDLE,
    REQUESTING,
    GRANTED,
    RELEASED,
    TAKEN
}

class McpttSipStack {
    private val scope = CoroutineScope(Dispatchers.IO)

    private var socket: DatagramSocket? = null
    private var listenJob: Job? = null

    private var profile: SipProfile = SipProfile()
    private var localIp: String = "192.168.101.2"

    private var cseqNumber = 1
    private var activeCallId = ""
    private var activeCallTag = ""
    private var activeCallToTag = ""

    private val _registrationState = MutableStateFlow(RegistrationState.UNREGISTERED)
    val registrationState: StateFlow<RegistrationState> = _registrationState.asStateFlow()

    private val _callState = MutableStateFlow(CallSessionState.IDLE)
    val callState: StateFlow<CallSessionState> = _callState.asStateFlow()

    private val _floorState = MutableStateFlow(FloorState.IDLE)
    val floorState: StateFlow<FloorState> = _floorState.asStateFlow()

    private val _activeSpeaker = MutableStateFlow<String?>(null)
    val activeSpeaker: StateFlow<String?> = _activeSpeaker.asStateFlow()

    private val _trafficLogs = MutableSharedFlow<SipTrafficLog>(extraBufferCapacity = 200)
    val trafficLogs: SharedFlow<SipTrafficLog> = _trafficLogs.asSharedFlow()

    fun start(context: Context? = null, currentProfile: SipProfile) {
        this.profile = currentProfile
        this.localIp = getLocalIpAddress(context)

        try {
            socket?.close()
            val ds = DatagramSocket(profile.localSipPort)
            socket = ds

            bindSocketToCellularNetwork(context, ds)

            Log.d(TAG, "SIP Socket bound & listening on $localIp:${profile.localSipPort}")
            logSystemEvent("SIP Engine initialized on $localIp:${profile.localSipPort}")

            startListeningLoop()

            if (profile.autoRegister) {
                register()
            }
        } catch (e: Exception) {
            val errMsg = e.localizedMessage ?: e.message ?: "Unknown socket error"
            Log.e(TAG, "Failed to start SIP socket: $errMsg", e)
            logSystemEvent("Error starting SIP socket: $errMsg", isError = true)
            _registrationState.value = RegistrationState.FAILED
        }
    }

    private fun bindSocketToCellularNetwork(context: Context?, ds: DatagramSocket) {
        if (context == null) return
        try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
            val networks = cm.allNetworks
            Log.d(TAG, "Scanning ${networks.size} networks for cellular/IMS socket binding...")

            var bound = false
            // 1. Look for Cellular or IMS network
            for (net in networks) {
                val caps = cm.getNetworkCapabilities(net) ?: continue
                val isCellular = caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
                val isIms = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_IMS)
                val linkProps = cm.getLinkProperties(net)
                val ifName = linkProps?.interfaceName ?: "unknown"

                Log.d(TAG, "Network $net ($ifName): cellular=$isCellular, ims=$isIms")

                if (isCellular || isIms) {
                    try {
                        net.bindSocket(ds)
                        bound = true
                        Log.i(TAG, "Bound DatagramSocket to Cellular/IMS Network $net ($ifName)")
                        logSystemEvent("Bound SIP socket to Cellular/IMS Network ($ifName)")

                        linkProps?.linkAddresses?.forEach { linkAddr ->
                            val addr = linkAddr.address
                            if (!addr.isLoopbackAddress && addr.hostAddress.indexOf(':') < 0) {
                                localIp = addr.hostAddress
                                Log.i(TAG, "Updated localIp to interface address: $localIp")
                            }
                        }
                        break
                    } catch (e: Exception) {
                        Log.w(TAG, "Could not bind socket to network $net ($ifName): ${e.message}")
                    }
                }
            }

            // 2. Fallback: match by IP prefix (e.g. 192.168.101.x or rmnet interface)
            if (!bound) {
                for (net in networks) {
                    val linkProps = cm.getLinkProperties(net) ?: continue
                    val ifName = linkProps.interfaceName ?: ""
                    for (linkAddr in linkProps.linkAddresses) {
                        val addr = linkAddr.address
                        if (!addr.isLoopbackAddress && addr.hostAddress.indexOf(':') < 0) {
                            val ipStr = addr.hostAddress
                            if (ipStr.startsWith("192.168.101") || ifName.contains("rmnet")) {
                                try {
                                    net.bindSocket(ds)
                                    bound = true
                                    localIp = ipStr
                                    Log.i(TAG, "Bound DatagramSocket by IP match $ipStr ($ifName)")
                                    logSystemEvent("Bound SIP socket to Cellular Interface ($ifName - $ipStr)")
                                    break
                                } catch (e: Exception) {
                                    Log.w(TAG, "Failed binding by IP match $ipStr: ${e.message}")
                                }
                            }
                        }
                    }
                    if (bound) break
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error binding socket to cellular network: ${e.message}", e)
        }
    }

    fun updateProfile(context: Context? = null, newProfile: SipProfile) {
        val needsRestart = profile.localSipPort != newProfile.localSipPort ||
                           profile.pcscfHost != newProfile.pcscfHost ||
                           profile.pcscfPort != newProfile.pcscfPort
        this.profile = newProfile
        if (needsRestart) {
            start(context, newProfile)
        }
    }

    private fun startListeningLoop() {
        listenJob?.cancel()
        listenJob = scope.launch {
            val buffer = ByteArray(4096)
            while (socket != null && !socket!!.isClosed) {
                try {
                    val packet = DatagramPacket(buffer, buffer.size)
                    socket?.receive(packet)
                    val rawSipText = String(packet.data, 0, packet.length)
                    val remoteAddr = "${packet.address.hostAddress}:${packet.port}"

                    val parsedMsg = SipMessage.parse(rawSipText)

                    val log = SipTrafficLog(
                        direction = LogDirection.INBOUND,
                        type = mapLogType(parsedMsg),
                        methodOrResponse = if (parsedMsg.isResponse) "${parsedMsg.statusCode} ${parsedMsg.statusText}" else parsedMsg.method,
                        remoteAddress = remoteAddr,
                        summary = parsedMsg.startLine,
                        rawPacket = rawSipText,
                        isMcpttTagged = parsedMsg.isMcpttTagged
                    )
                    _trafficLogs.emit(log)

                    handleIncomingSipMessage(parsedMsg)
                } catch (e: Exception) {
                    if (socket?.isClosed == false) {
                        Log.e(TAG, "Listen error: ${e.message}")
                    }
                }
            }
        }
    }

    private fun handleIncomingSipMessage(msg: SipMessage) {
        if (msg.isResponse) {
            when (msg.method) {
                "REGISTER" -> {
                    if (msg.statusCode in 200..299) {
                        _registrationState.value = RegistrationState.REGISTERED
                        logSystemEvent("SIP Registration Successful (200 OK)")
                    } else if (msg.statusCode == 401 || msg.statusCode == 407) {
                        logSystemEvent("Received Digest Auth Challenge (${msg.statusCode}) - Resending with Credentials")
                        handleRegisterAuthChallenge(msg)
                    } else if (msg.statusCode >= 400) {
                        _registrationState.value = RegistrationState.FAILED
                        logSystemEvent("Registration Failed: ${msg.statusCode} ${msg.statusText}", isError = true)
                    }
                }
                "INVITE" -> {
                    if (msg.statusCode == 200 || msg.statusCode == 202) {
                        _callState.value = CallSessionState.CONNECTED
                        activeCallToTag = extractTag(msg.to)
                        sendAck(msg)
                        logSystemEvent("MCPTT Session Connected! (200 OK)")
                    } else if (msg.statusCode in 100..199) {
                        logSystemEvent("MCPTT Call Progress: ${msg.statusCode} ${msg.statusText}")
                    } else if (msg.statusCode >= 400) {
                        _callState.value = CallSessionState.IDLE
                        logSystemEvent("MCPTT Call Rejected: ${msg.statusCode} ${msg.statusText}", isError = true)
                    }
                }
                "SUBSCRIBE" -> {
                    if (msg.statusCode in 200..299) {
                        logSystemEvent("Group Event Subscription Active (200 OK)")
                    }
                }
            }
        } else {
            // Incoming Request from Server / AS / Peer
            when (msg.method) {
                "INVITE" -> {
                    // Incoming MCPTT Call Invite
                    activeCallId = msg.callId
                    _callState.value = CallSessionState.CONNECTED
                    sendResponse(msg, 200, "OK")
                    logSystemEvent("Accepted Incoming MCPTT Call Session from ${msg.from}")
                }
                "INFO" -> {
                    sendResponse(msg, 200, "OK")
                    when (msg.floorControlState) {
                        "GRANTED" -> {
                            _floorState.value = FloorState.GRANTED
                            _activeSpeaker.value = profile.mcpttId
                        }
                        "TAKEN" -> {
                            _floorState.value = FloorState.TAKEN
                            _activeSpeaker.value = msg.from
                        }
                        "RELEASE" -> {
                            _floorState.value = FloorState.IDLE
                            _activeSpeaker.value = null
                        }
                    }
                }
                "MESSAGE" -> {
                    sendResponse(msg, 200, "OK")
                    logSystemEvent("Received MCPTT SIP Message: ${msg.body}")
                }
                "BYE" -> {
                    sendResponse(msg, 200, "OK")
                    _callState.value = CallSessionState.IDLE
                    _floorState.value = FloorState.IDLE
                    _activeSpeaker.value = null
                    logSystemEvent("MCPTT Call Session Ended by Remote")
                }
                "OPTIONS" -> {
                    sendResponse(msg, 200, "OK")
                }
            }
        }
    }

    fun register() {
        _registrationState.value = RegistrationState.REGISTERING
        val branch = generateBranch()
        val callId = generateCallId()
        val cseq = ++cseqNumber

        val user = extractUser(profile.mcpttId)
        val mcpttTagHeader = if (profile.includeMcpttTags) ";+g.3gpp.mcptt" else ""
        val mcpttAcceptHeader = if (profile.includeMcpttTags) "\r\nAccept-Contact: *;+g.3gpp.mcptt;explicit;require" else ""

        val rawSip = """
            REGISTER sip:${profile.realm} SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=${generateTag()}
            To: <${profile.mcpttId}>
            Call-ID: $callId
            CSeq: $cseq REGISTER
            Contact: <sip:$user@$localIp:${profile.localSipPort}>$mcpttTagHeader$mcpttAcceptHeader
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Expires: 3600
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_REGISTER, "REGISTER sip:${profile.realm}")
    }

    private fun handleRegisterAuthChallenge(challengeMsg: SipMessage) {
        val wwwAuth = challengeMsg.headers["www-authenticate"] ?: challengeMsg.headers["proxy-authenticate"] ?: return
        val realm = extractAuthParam(wwwAuth, "realm") ?: profile.realm
        val nonce = extractAuthParam(wwwAuth, "nonce") ?: ""
        val uri = "sip:${profile.realm}"

        val user = extractUser(profile.mcpttId)
        val responseHex = calculateDigestResponse(user, realm, profile.password, "REGISTER", uri, nonce)

        val branch = generateBranch()
        val callId = challengeMsg.callId
        val cseq = ++cseqNumber

        val mcpttTagHeader = if (profile.includeMcpttTags) ";+g.3gpp.mcptt" else ""

        val authHeader = "Digest username=\"$user\", realm=\"$realm\", nonce=\"$nonce\", uri=\"$uri\", response=\"$responseHex\", algorithm=MD5"

        val rawSip = """
            REGISTER sip:${profile.realm} SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=${generateTag()}
            To: <${profile.mcpttId}>
            Call-ID: $callId
            CSeq: $cseq REGISTER
            Contact: <sip:$user@$localIp:${profile.localSipPort}>$mcpttTagHeader
            Authorization: $authHeader
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Expires: 3600
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_REGISTER, "REGISTER (Authenticated)")
    }

    fun subscribeGroup(groupUri: String = profile.targetGroup) {
        val branch = generateBranch()
        val callId = generateCallId()
        val cseq = ++cseqNumber

        val rawSip = """
            SUBSCRIBE $groupUri SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=${generateTag()}
            To: <$groupUri>
            Call-ID: $callId
            CSeq: $cseq SUBSCRIBE
            Contact: <sip:${extractUser(profile.mcpttId)}@$localIp:${profile.localSipPort}>;+g.3gpp.mcptt
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require
            Event: poc-settings
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Expires: 3600
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_SUBSCRIBE, "SUBSCRIBE $groupUri")
    }

    fun initiateMcpttCall(targetUri: String = profile.targetGroup) {
        if (_callState.value != CallSessionState.IDLE) return

        _callState.value = CallSessionState.CALLING
        activeCallId = generateCallId()
        activeCallTag = generateTag()
        val branch = generateBranch()
        val cseq = ++cseqNumber

        val sdp = """
            v=0
            o=mcptt 10001 10001 IN IP4 $localIp
            s=MCPTT Group Call
            c=IN IP4 $localIp
            t=0 0
            m=audio ${profile.localRtpPort} RTP/AVP 0 8 101
            a=rtpmap:0 PCMU/8000
            a=rtpmap:8 PCMA/8000
            a=rtpmap:101 telephone-event/8000
            a=sendrecv
            a=mcptt
        """.trimIndent().replace("\n", "\r\n")

        val sdpLength = sdp.toByteArray().size

        val rawSip = """
            INVITE $targetUri SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=$activeCallTag
            To: <$targetUri>
            Call-ID: $activeCallId
            CSeq: $cseq INVITE
            Contact: <sip:${extractUser(profile.mcpttId)}@$localIp:${profile.localSipPort}>;+g.3gpp.mcptt
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require
            P-Preferred-Identity: <${profile.mcpttId}>
            P-Access-Network-Info: 3GPP-E-UTRAN-FDD; utran-cell-id-3gpp=2089300000001
            User-Agent: ${profile.userAgent}
            Content-Type: application/sdp
            Content-Length: $sdpLength
            
            $sdp
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_INVITE, "INVITE $targetUri (+g.3gpp.mcptt)")
    }

    fun requestFloor() {
        if (_callState.value != CallSessionState.CONNECTED) {
            initiateMcpttCall()
        }

        _floorState.value = FloorState.REQUESTING
        _activeSpeaker.value = profile.mcpttId

        sendFloorControlMessage("floor-request")
    }

    fun releaseFloor() {
        if (_floorState.value == FloorState.GRANTED || _floorState.value == FloorState.REQUESTING) {
            _floorState.value = FloorState.RELEASED
            sendFloorControlMessage("floor-release")
            _floorState.value = FloorState.IDLE
            _activeSpeaker.value = null
        }
    }

    private fun sendFloorControlMessage(action: String) {
        val branch = generateBranch()
        val cseq = ++cseqNumber

        val body = """
            [MCPTT_FLOOR_CONTROL]
            Action=$action
            User=${profile.mcpttId}
            Timestamp=${System.currentTimeMillis()}
        """.trimIndent().replace("\n", "\r\n")

        val bodyLen = body.toByteArray().size

        val rawSip = """
            INFO ${profile.targetGroup} SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=$activeCallTag
            To: <${profile.targetGroup}>${if (activeCallToTag.isNotEmpty()) ";tag=$activeCallToTag" else ""}
            Call-ID: $activeCallId
            CSeq: $cseq INFO
            Contact: <sip:${extractUser(profile.mcpttId)}@$localIp:${profile.localSipPort}>;+g.3gpp.mcptt
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Content-Type: application/mcptt-floor-control+xml
            Content-Length: $bodyLen
            
            $body
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_INFO, "INFO Floor Control ($action)")

        if (action == "floor-request" && profile.autoGrantFloor) {
            // Optional local fake floor grant (disabled by default)
            scope.launch {
                kotlinx.coroutines.delay(300)
                if (_floorState.value == FloorState.REQUESTING) {
                    _floorState.value = FloorState.GRANTED
                    logSystemEvent("Floor Locally Granted (Debug Mode Active)")
                }
            }
        }
    }

    fun sendEmergencyAlert(messageText: String = "EMERGENCY SOS ALERT BROADCAST") {
        val branch = generateBranch()
        val cseq = ++cseqNumber
        val callId = generateCallId()

        val body = "[EMERGENCY_ALERT] User: ${profile.displayName} (${profile.mcpttId}) - $messageText"
        val bodyLen = body.toByteArray().size

        val rawSip = """
            MESSAGE ${profile.emergencyGroup} SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=${generateTag()}
            To: <${profile.emergencyGroup}>
            Call-ID: $callId
            CSeq: $cseq MESSAGE
            Contact: <sip:${extractUser(profile.mcpttId)}@$localIp:${profile.localSipPort}>;+g.3gpp.mcptt;+g.3gpp.mcptt.emergency
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require;+g.3gpp.mcptt.emergency
            Priority: emergency
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Content-Type: text/plain
            Content-Length: $bodyLen
            
            $body
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_MESSAGE, "MESSAGE Emergency Alert (+g.3gpp.mcptt.emergency)")
    }

    fun sendSipMessageText(targetUri: String, textMessage: String) {
        val branch = generateBranch()
        val cseq = ++cseqNumber
        val callId = generateCallId()

        val bodyLen = textMessage.toByteArray().size

        val rawSip = """
            MESSAGE $targetUri SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=${generateTag()}
            To: <$targetUri>
            Call-ID: $callId
            CSeq: $cseq MESSAGE
            Contact: <sip:${extractUser(profile.mcpttId)}@$localIp:${profile.localSipPort}>;+g.3gpp.mcptt
            Accept-Contact: *;+g.3gpp.mcptt;explicit;require
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Content-Type: text/plain
            Content-Length: $bodyLen
            
            $textMessage
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_MESSAGE, "MESSAGE $targetUri")
    }

    fun endCall() {
        if (_callState.value == CallSessionState.IDLE) return

        _callState.value = CallSessionState.DISCONNECTING
        val branch = generateBranch()
        val cseq = ++cseqNumber

        val rawSip = """
            BYE ${profile.targetGroup} SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=$activeCallTag
            To: <${profile.targetGroup}>${if (activeCallToTag.isNotEmpty()) ";tag=$activeCallToTag" else ""}
            Call-ID: $activeCallId
            CSeq: $cseq BYE
            Contact: <sip:${extractUser(profile.mcpttId)}@$localIp:${profile.localSipPort}>;+g.3gpp.mcptt
            P-Preferred-Identity: <${profile.mcpttId}>
            User-Agent: ${profile.userAgent}
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_BYE, "BYE ${profile.targetGroup}")

        _callState.value = CallSessionState.IDLE
        _floorState.value = FloorState.IDLE
        _activeSpeaker.value = null
    }

    private fun sendAck(inviteResponseMsg: SipMessage) {
        val branch = generateBranch()
        val rawSip = """
            ACK ${profile.targetGroup} SIP/2.0
            Via: SIP/2.0/UDP $localIp:${profile.localSipPort};rport;branch=$branch
            From: <${profile.mcpttId}>;tag=$activeCallTag
            To: <${profile.targetGroup}>;tag=$activeCallToTag
            Call-ID: $activeCallId
            CSeq: ${inviteResponseMsg.cseq.split(" ")[0]} ACK
            User-Agent: ${profile.userAgent}
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_ACK, "ACK ${profile.targetGroup}")
    }

    private fun sendResponse(requestMsg: SipMessage, code: Int, text: String) {
        val via = requestMsg.headers["via"] ?: ""
        val from = requestMsg.headers["from"] ?: ""
        val to = requestMsg.headers["to"] ?: ""
        val callId = requestMsg.callId
        val cseq = requestMsg.cseq

        val rawSip = """
            SIP/2.0 $code $text
            Via: $via
            From: $from
            To: $to;tag=${generateTag()}
            Call-ID: $callId
            CSeq: $cseq
            User-Agent: ${profile.userAgent}
            Content-Length: 0
            
        """.trimIndent().replace("\n", "\r\n")

        sendSipText(rawSip, LogType.SIP_RESPONSE, "SIP/2.0 $code $text")
    }

    private fun sendSipText(rawSipText: String, type: LogType, summary: String) {
        scope.launch {
            try {
                val bytes = rawSipText.toByteArray()
                val targetAddr = InetAddress.getByName(profile.pcscfHost)
                val packet = DatagramPacket(bytes, bytes.size, targetAddr, profile.pcscfPort)

                val currentSocket = socket
                if (currentSocket == null || currentSocket.isClosed) {
                    throw IllegalStateException("SIP DatagramSocket is closed or not initialized")
                }

                currentSocket.send(packet)
                Log.d(TAG, "Successfully sent SIP packet to ${profile.pcscfHost}:${profile.pcscfPort}:\n$rawSipText")

                val log = SipTrafficLog(
                    direction = LogDirection.OUTBOUND,
                    type = type,
                    methodOrResponse = summary.split(" ")[0],
                    remoteAddress = "${profile.pcscfHost}:${profile.pcscfPort}",
                    summary = summary,
                    rawPacket = rawSipText,
                    isMcpttTagged = rawSipText.contains("+g.3gpp.mcptt")
                )
                _trafficLogs.emit(log)
            } catch (e: Exception) {
                val errMsg = e.localizedMessage ?: e.message ?: e.javaClass.simpleName
                Log.e(TAG, "Error sending SIP packet to ${profile.pcscfHost}:${profile.pcscfPort}: $errMsg", e)

                val errorLog = SipTrafficLog(
                    direction = LogDirection.OUTBOUND,
                    type = type,
                    methodOrResponse = "SEND_FAIL",
                    remoteAddress = "${profile.pcscfHost}:${profile.pcscfPort}",
                    summary = "[ERROR] Send Failed: $errMsg",
                    rawPacket = "--- FAILED SIP PACKET TRANSMISSION ---\nTarget P-CSCF: ${profile.pcscfHost}:${profile.pcscfPort}\nError: $errMsg\nException Class: ${e.javaClass.canonicalName}\n\nRAW INTENDED MESSAGE:\n$rawSipText",
                    hasError = true,
                    isMcpttTagged = rawSipText.contains("+g.3gpp.mcptt")
                )
                _trafficLogs.emit(errorLog)
                logSystemEvent("Send failed to ${profile.pcscfHost}:${profile.pcscfPort}: $errMsg", isError = true)
            }
        }
    }

    fun injectSimulatedPacket(rawPacketText: String) {
        scope.launch {
            val parsedMsg = SipMessage.parse(rawPacketText)
            val log = SipTrafficLog(
                direction = LogDirection.INBOUND,
                type = mapLogType(parsedMsg),
                methodOrResponse = if (parsedMsg.isResponse) "${parsedMsg.statusCode} ${parsedMsg.statusText}" else parsedMsg.method,
                remoteAddress = "${profile.pcscfHost}:${profile.pcscfPort} (Simulated)",
                summary = parsedMsg.startLine,
                rawPacket = rawPacketText,
                isMcpttTagged = parsedMsg.isMcpttTagged
            )
            _trafficLogs.emit(log)
            handleIncomingSipMessage(parsedMsg)
        }
    }

    private fun logSystemEvent(msg: String, isError: Boolean = false) {
        scope.launch {
            val log = SipTrafficLog(
                direction = LogDirection.INBOUND,
                type = LogType.SYSTEM_EVENT,
                methodOrResponse = if (isError) "ERROR" else "INFO",
                remoteAddress = "Local Engine",
                summary = msg,
                rawPacket = msg,
                hasError = isError
            )
            _trafficLogs.emit(log)
        }
    }

    fun stop() {
        listenJob?.cancel()
        listenJob = null
        socket?.close()
        socket = null
        _registrationState.value = RegistrationState.UNREGISTERED
        _callState.value = CallSessionState.IDLE
        _floorState.value = FloorState.IDLE
    }

    private fun getLocalIpAddress(context: Context? = null): String {
        try {
            if (context != null) {
                val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                if (cm != null) {
                    for (net in cm.allNetworks) {
                        val caps = cm.getNetworkCapabilities(net) ?: continue
                        if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) || caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_IMS)) {
                            val linkProps = cm.getLinkProperties(net)
                            linkProps?.linkAddresses?.forEach { linkAddr ->
                                val addr = linkAddr.address
                                if (!addr.isLoopbackAddress && addr.hostAddress.indexOf(':') < 0) {
                                    return addr.hostAddress
                                }
                            }
                        }
                    }
                }
            }

            val interfaces = NetworkInterface.getNetworkInterfaces()
            var fallbackIp: String? = null
            while (interfaces.hasMoreElements()) {
                val intf = interfaces.nextElement()
                val name = intf.name.lowercase()
                val addrs = intf.inetAddresses
                while (addrs.hasMoreElements()) {
                    val addr = addrs.nextElement()
                    if (!addr.isLoopbackAddress && addr.hostAddress.indexOf(':') < 0) {
                        val ipStr = addr.hostAddress
                        if (name.contains("rmnet") || name.contains("ccmni") || name.contains("pdp") || ipStr.startsWith("192.168.101")) {
                            return ipStr
                        }
                        if (fallbackIp == null) {
                            fallbackIp = ipStr
                        }
                    }
                }
            }
            if (fallbackIp != null) return fallbackIp
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get local IP: ${e.message}")
        }
        return "192.168.101.2"
    }

    private fun mapLogType(msg: SipMessage): LogType {
        if (msg.isResponse) return LogType.SIP_RESPONSE
        return when (msg.method) {
            "REGISTER" -> LogType.SIP_REGISTER
            "SUBSCRIBE" -> LogType.SIP_SUBSCRIBE
            "INVITE" -> LogType.SIP_INVITE
            "MESSAGE" -> LogType.SIP_MESSAGE
            "INFO" -> LogType.SIP_INFO
            "BYE" -> LogType.SIP_BYE
            "ACK" -> LogType.SIP_ACK
            else -> LogType.SYSTEM_EVENT
        }
    }

    private fun generateBranch() = "z9hG4bK-${UUID.randomUUID().toString().substring(0, 8)}"
    private fun generateCallId() = "${UUID.randomUUID()}@$localIp"
    private fun generateTag() = UUID.randomUUID().toString().substring(0, 8)
    private fun extractUser(sipUri: String): String {
        val clean = sipUri.replace("sip:", "")
        return clean.substringBefore("@")
    }

    private fun extractTag(header: String): String {
        val parts = header.split(";")
        for (p in parts) {
            if (p.trim().startsWith("tag=")) {
                return p.trim().substringAfter("tag=")
            }
        }
        return ""
    }

    private fun extractAuthParam(authHeader: String, paramName: String): String? {
        val regex = Regex("""$paramName="([^"]+)"""")
        return regex.find(authHeader)?.groupValues?.get(1)
    }

    private fun calculateDigestResponse(
        user: String,
        realm: String,
        pass: String,
        method: String,
        uri: String,
        nonce: String
    ): String {
        val md5 = MessageDigest.getInstance("MD5")
        fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }

        val ha1 = hex(md5.digest("$user:$realm:$pass".toByteArray()))
        val ha2 = hex(md5.digest("$method:$uri".toByteArray()))
        return hex(md5.digest("$ha1:$nonce:$ha2".toByteArray()))
    }

    companion object {
        private const val TAG = "McpttSipStack"
    }
}
