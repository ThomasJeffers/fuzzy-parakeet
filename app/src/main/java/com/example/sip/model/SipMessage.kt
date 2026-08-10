package com.example.sip.model

data class SipMessage(
    val rawText: String,
    val isResponse: Boolean,
    val method: String = "", // e.g. "INVITE", "REGISTER", "MESSAGE"
    val statusCode: Int = 0, // e.g. 200, 401, 180
    val statusText: String = "", // e.g. "OK", "Unauthorized"
    val startLine: String = "",
    val headers: Map<String, String> = emptyMap(),
    val body: String = "",
    val callId: String = "",
    val cseq: String = "",
    val from: String = "",
    val to: String = "",
    val contact: String = "",
    val contentType: String = ""
) {
    val isMcpttTagged: Boolean
        get() = rawText.contains("+g.3gpp.mcptt") || 
                rawText.contains("mcptt") || 
                headers.values.any { it.contains("3gpp-service.ims.icsi.mcptt") }

    val floorControlState: String?
        get() {
            if (rawText.contains("floor-request", ignoreCase = true)) return "REQUEST"
            if (rawText.contains("floor-granted", ignoreCase = true)) return "GRANTED"
            if (rawText.contains("floor-release", ignoreCase = true)) return "RELEASE"
            if (rawText.contains("floor-taken", ignoreCase = true)) return "TAKEN"
            return null
        }

    companion object {
        fun parse(rawText: String): SipMessage {
            val lines = rawText.lines()
            if (lines.isEmpty()) return SipMessage(rawText, false)

            val startLine = lines[0].trim()
            val isResponse = startLine.startsWith("SIP/2.0")

            var method = ""
            var statusCode = 0
            var statusText = ""

            if (isResponse) {
                val parts = startLine.split(" ", limit = 3)
                if (parts.size >= 2) {
                    statusCode = parts[1].toIntOrNull() ?: 0
                }
                if (parts.size >= 3) {
                    statusText = parts[2]
                }
            } else {
                val parts = startLine.split(" ")
                if (parts.isNotEmpty()) {
                    method = parts[0].uppercase()
                }
            }

            val headers = mutableMapOf<String, String>()
            var bodyStartIndex = -1

            for (i in 1 until lines.size) {
                val line = lines[i]
                if (line.isEmpty() || line == "\r") {
                    bodyStartIndex = i + 1
                    break
                }
                val colonIndex = line.indexOf(':')
                if (colonIndex > 0) {
                    val headerName = line.substring(0, colonIndex).trim().lowercase()
                    val headerValue = line.substring(colonIndex + 1).trim()
                    headers[headerName] = headerValue
                }
            }

            val body = if (bodyStartIndex in 1..lines.size) {
                lines.subList(bodyStartIndex, lines.size).joinToString("\n")
            } else ""

            val cseqVal = headers["cseq"] ?: ""
            if (isResponse && method.isEmpty() && cseqVal.isNotEmpty()) {
                val cseqParts = cseqVal.split(" ")
                if (cseqParts.size >= 2) {
                    method = cseqParts[1].uppercase()
                }
            }

            return SipMessage(
                rawText = rawText,
                isResponse = isResponse,
                method = method,
                statusCode = statusCode,
                statusText = statusText,
                startLine = startLine,
                headers = headers,
                body = body,
                callId = headers["call-id"] ?: "",
                cseq = cseqVal,
                from = headers["from"] ?: "",
                to = headers["to"] ?: "",
                contact = headers["contact"] ?: "",
                contentType = headers["content-type"] ?: ""
            )
        }
    }
}
