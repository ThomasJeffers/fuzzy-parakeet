package com.example.sip.engine

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import kotlin.math.sin

class RtpAudioEngine {
    private val scope = CoroutineScope(Dispatchers.IO)

    private var rtpSocket: DatagramSocket? = null
    private var isTransmitting = false
    private var isReceiving = false

    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null

    private var transmitJob: Job? = null
    private var receiveJob: Job? = null

    private val _micAudioLevel = MutableStateFlow(0f)
    val micAudioLevel: StateFlow<Float> = _micAudioLevel.asStateFlow()

    private val sampleRate = 8000
    private val channelConfigIn = AudioFormat.CHANNEL_IN_MONO
    private val channelConfigOut = AudioFormat.CHANNEL_OUT_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT

    fun init(localRtpPort: Int) {
        try {
            rtpSocket?.close()
            rtpSocket = DatagramSocket(localRtpPort)
            Log.d(TAG, "RTP Socket bound to port $localRtpPort")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to bind RTP Socket: ${e.message}")
        }
    }

    fun playGrantTone() {
        scope.launch {
            playToneSequence(intArrayOf(880, 1200), intArrayOf(80, 100))
        }
    }

    fun playReleaseTone() {
        scope.launch {
            playToneSequence(intArrayOf(1000, 600), intArrayOf(60, 80))
        }
    }

    fun playEmergencyTone() {
        scope.launch {
            playToneSequence(intArrayOf(1500, 1800, 1500, 1800), intArrayOf(100, 100, 100, 100))
        }
    }

    private fun playToneSequence(frequencies: IntArray, durationsMs: IntArray) {
        try {
            val minBufSize = AudioTrack.getMinBufferSize(
                sampleRate,
                channelConfigOut,
                audioFormat
            )
            val track = AudioTrack(
                AudioManager.STREAM_MUSIC,
                sampleRate,
                channelConfigOut,
                audioFormat,
                minBufSize * 2,
                AudioTrack.MODE_STREAM
            )
            track.play()

            for (i in frequencies.indices) {
                val freq = frequencies[i]
                val durMs = durationsMs[i]
                val numSamples = (sampleRate * durMs / 1000)
                val buffer = ShortArray(numSamples)

                for (j in 0 until numSamples) {
                    val angle = 2.0 * Math.PI * j / (sampleRate / freq)
                    buffer[j] = (sin(angle) * 20000).toInt().toShort()
                }
                track.write(buffer, 0, numSamples)
            }

            track.stop()
            track.release()
        } catch (e: Exception) {
            Log.e(TAG, "Error playing tone: ${e.message}")
        }
    }

    @SuppressLint("MissingPermission")
    fun startMicrophoneTransmission(destHost: String, destPort: Int) {
        if (isTransmitting) return
        isTransmitting = true

        transmitJob = scope.launch {
            val minBufSize = AudioRecord.getMinBufferSize(
                sampleRate,
                channelConfigIn,
                audioFormat
            )

            try {
                audioRecord = AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    sampleRate,
                    channelConfigIn,
                    audioFormat,
                    minBufSize * 2
                )

                if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                    Log.e(TAG, "AudioRecord failed to initialize")
                    isTransmitting = false
                    return@launch
                }

                audioRecord?.startRecording()
                val buffer = ShortArray(160) // 20ms frames at 8kHz
                val targetAddr = InetAddress.getByName(destHost)
                var sequenceNum = 0
                var timestamp = 0L

                while (isTransmitting) {
                    val readBytes = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (readBytes > 0) {
                        // Calculate audio power level for UI visualizer
                        var sum = 0.0
                        for (i in 0 until readBytes) {
                            sum += buffer[i] * buffer[i]
                        }
                        val amplitude = Math.sqrt(sum / readBytes)
                        _micAudioLevel.value = (amplitude / 32768.0).toFloat().coerceIn(0f, 1f)

                        // Format basic RTP Packet (12 byte header + payload)
                        val rtpPacketData = ByteArray(12 + readBytes * 2)
                        // Version=2, Padding=0, Extension=0, CSRC count=0 -> 0x80
                        rtpPacketData[0] = 0x80.toByte()
                        // Payload Type 0 (PCMU/PCM) -> 0x00
                        rtpPacketData[1] = 0x00.toByte()
                        // Sequence Number
                        rtpPacketData[2] = ((sequenceNum shr 8) and 0xFF).toByte()
                        rtpPacketData[3] = (sequenceNum and 0xFF).toByte()
                        // Timestamp
                        rtpPacketData[4] = ((timestamp shr 24) and 0xFF).toByte()
                        rtpPacketData[5] = ((timestamp shr 16) and 0xFF).toByte()
                        rtpPacketData[6] = ((timestamp shr 8) and 0xFF).toByte()
                        rtpPacketData[7] = (timestamp and 0xFF).toByte()
                        // SSRC = 0x12345678
                        rtpPacketData[8] = 0x12
                        rtpPacketData[9] = 0x34
                        rtpPacketData[10] = 0x56
                        rtpPacketData[11] = 0x78

                        // Copy PCM data
                        for (i in 0 until readBytes) {
                            val sample = buffer[i]
                            rtpPacketData[12 + i * 2] = (sample.toInt() and 0xFF).toByte()
                            rtpPacketData[12 + i * 2 + 1] = ((sample.toInt() shr 8) and 0xFF).toByte()
                        }

                        val packet = DatagramPacket(
                            rtpPacketData,
                            rtpPacketData.size,
                            targetAddr,
                            destPort
                        )
                        rtpSocket?.send(packet)

                        sequenceNum = (sequenceNum + 1) and 0xFFFF
                        timestamp += readBytes
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Transmission loop error: ${e.message}")
            } finally {
                try {
                    audioRecord?.stop()
                    audioRecord?.release()
                    audioRecord = null
                } catch (e: Exception) {
                    Log.e(TAG, "Clean up mic error: ${e.message}")
                }
                _micAudioLevel.value = 0f
            }
        }
    }

    fun stopMicrophoneTransmission() {
        isTransmitting = false
        transmitJob?.cancel()
        transmitJob = null
        _micAudioLevel.value = 0f
    }

    fun startAudioPlayback() {
        if (isReceiving) return
        isReceiving = true

        receiveJob = scope.launch {
            val minBufSize = AudioTrack.getMinBufferSize(
                sampleRate,
                channelConfigOut,
                audioFormat
            )

            try {
                audioTrack = AudioTrack(
                    AudioManager.STREAM_MUSIC,
                    sampleRate,
                    channelConfigOut,
                    audioFormat,
                    minBufSize * 2,
                    AudioTrack.MODE_STREAM
                )
                audioTrack?.play()

                val recvBuf = ByteArray(1024)
                val packet = DatagramPacket(recvBuf, recvBuf.size)

                while (isReceiving) {
                    rtpSocket?.receive(packet)
                    val len = packet.length
                    if (len > 12) {
                        val payloadLen = len - 12
                        val pcmShorts = ShortArray(payloadLen / 2)

                        for (i in pcmShorts.indices) {
                            val low = recvBuf[12 + i * 2].toInt() and 0xFF
                            val high = recvBuf[12 + i * 2 + 1].toInt()
                            pcmShorts[i] = ((high shl 8) or low).toShort()
                        }

                        audioTrack?.write(pcmShorts, 0, pcmShorts.size)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "RTP receive playback error: ${e.message}")
            } finally {
                try {
                    audioTrack?.stop()
                    audioTrack?.release()
                    audioTrack = null
                } catch (e: Exception) {
                    Log.e(TAG, "Clean up speaker error: ${e.message}")
                }
            }
        }
    }

    fun stopAudioPlayback() {
        isReceiving = false
        receiveJob?.cancel()
        receiveJob = null
    }

    fun close() {
        stopMicrophoneTransmission()
        stopAudioPlayback()
        rtpSocket?.close()
        rtpSocket = null
    }

    companion object {
        private const val TAG = "RtpAudioEngine"
    }
}
