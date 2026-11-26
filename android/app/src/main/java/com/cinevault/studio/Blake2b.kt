package com.cinevault.studio

import android.os.ParcelFileDescriptor
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Pure Kotlin RFC 7693 BLAKE2b implementation matching Python's `hashlib.blake2b(digest_size=16)`.
 * Produces identical `cvh1_<12hex_size>_<32hex_digest>` composite fingerprints as `src/core/hasher.py`.
 */
class Blake2b(private val digestLength: Int = 16) {

    private val h = LongArray(8)
    private val buf = ByteArray(128)
    private var bufLen = 0
    private var t0 = 0L
    private var t1 = 0L

    init {
        for (i in 0 until 8) h[i] = IV[i]
        h[0] = h[0] xor (0x01010000L or digestLength.toLong())
    }

    fun update(input: ByteArray, offset: Int = 0, len: Int = input.size) {
        var off = offset
        var rem = len
        while (rem > 0) {
            if (bufLen == 128) {
                t0 += 128L
                if (t0 in 0L..127L) t1++
                compress(buf, 0, false)
                bufLen = 0
            }
            val take = minOf(rem, 128 - bufLen)
            System.arraycopy(input, off, buf, bufLen, take)
            bufLen += take
            off += take
            rem -= take
        }
    }

    fun digest(): ByteArray {
        t0 += bufLen.toLong()
        if (t0 >= 0L && t0 < bufLen.toLong()) t1++
        while (bufLen < 128) buf[bufLen++] = 0
        compress(buf, 0, true)

        val out = ByteArray(digestLength)
        for (i in 0 until digestLength) {
            out[i] = ((h[i ushr 3] ushr (8 * (i and 7))) and 0xFFL).toByte()
        }
        return out
    }

    fun hexdigest(): String = digest().joinToString("") { "%02x".format(it) }

    private fun compress(block: ByteArray, off: Int, isLast: Boolean) {
        val m = LongArray(16)
        for (i in 0 until 16) {
            val base = off + i * 8
            m[i] = (block[base].toLong() and 0xFFL) or
                ((block[base + 1].toLong() and 0xFFL) shl 8) or
                ((block[base + 2].toLong() and 0xFFL) shl 16) or
                ((block[base + 3].toLong() and 0xFFL) shl 24) or
                ((block[base + 4].toLong() and 0xFFL) shl 32) or
                ((block[base + 5].toLong() and 0xFFL) shl 40) or
                ((block[base + 6].toLong() and 0xFFL) shl 48) or
                ((block[base + 7].toLong() and 0xFFL) shl 56)
        }

        val v = LongArray(16)
        for (i in 0 until 8) {
            v[i] = h[i]
            v[i + 8] = IV[i]
        }
        v[12] = v[12] xor t0
        v[13] = v[13] xor t1
        if (isLast) v[14] = v[14].inv()

        for (r in 0 until 12) {
            val s = SIGMA[r]
            g(v, 0, 4, 8, 12, m[s[0]], m[s[1]])
            g(v, 1, 5, 9, 13, m[s[2]], m[s[3]])
            g(v, 2, 6, 10, 14, m[s[4]], m[s[5]])
            g(v, 3, 7, 11, 15, m[s[6]], m[s[7]])
            g(v, 0, 5, 10, 15, m[s[8]], m[s[9]])
            g(v, 1, 6, 11, 12, m[s[10]], m[s[11]])
            g(v, 2, 7, 8, 13, m[s[12]], m[s[13]])
            g(v, 3, 4, 9, 14, m[s[14]], m[s[15]])
        }

        for (i in 0 until 8) {
            h[i] = h[i] xor v[i] xor v[i + 8]
        }
    }

    private fun g(v: LongArray, a: Int, b: Int, c: Int, d: Int, x: Long, y: Long) {
        v[a] = v[a] + v[b] + x
        v[d] = java.lang.Long.rotateRight(v[d] xor v[a], 32)
        v[c] = v[c] + v[d]
        v[b] = java.lang.Long.rotateRight(v[b] xor v[c], 24)
        v[a] = v[a] + v[b] + y
        v[d] = java.lang.Long.rotateRight(v[d] xor v[a], 16)
        v[c] = v[c] + v[d]
        v[b] = java.lang.Long.rotateRight(v[b] xor v[c], 63)
    }

    companion object {
        private const val CHUNK_SIZE = 65536

        private val IV = longArrayOf(
            0x6a09e667f3bcc908L, -0x4498517a7b3558c5L, 0x3c6ef372fe94f82bL, -0x5ab00ac5a0e2c90fL,
            0x510e527fade682d1L, -0x64fa9773d4c193e1L, 0x1f83d9abfb41bd6bL, 0x5be0cd19137e2179L
        )

        private val SIGMA = arrayOf(
            intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
            intArrayOf(14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3),
            intArrayOf(11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4),
            intArrayOf(7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8),
            intArrayOf(9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13),
            intArrayOf(2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9),
            intArrayOf(12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11),
            intArrayOf(13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10),
            intArrayOf(6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5),
            intArrayOf(10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0),
            intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
            intArrayOf(14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3)
        )

        fun computeFastFingerprint(pfd: ParcelFileDescriptor, size: Long): String {
            val hasher = Blake2b(16)
            val sizeBytes = ByteBuffer.allocate(8).order(ByteOrder.BIG_ENDIAN).putLong(size).array()
            hasher.update(sizeBytes)

            FileInputStream(pfd.fileDescriptor).use { fis ->
                val ch = fis.channel
                val buf = ByteBuffer.allocate(CHUNK_SIZE)
                if (size <= CHUNK_SIZE * 3L) {
                    ch.position(0)
                    while (true) {
                        buf.clear()
                        val read = ch.read(buf)
                        if (read <= 0) break
                        hasher.update(buf.array(), 0, read)
                    }
                } else {
                    // 1. Head 64KB
                    ch.position(0)
                    readFully(ch, buf, hasher)

                    // 2. Mid 64KB
                    val mid = maxOf(0L, (size / 2L) - (CHUNK_SIZE / 2L))
                    ch.position(mid)
                    readFully(ch, buf, hasher)

                    // 3. Tail 64KB
                    val tail = maxOf(0L, size - CHUNK_SIZE.toLong())
                    ch.position(tail)
                    readFully(ch, buf, hasher)
                }
            }

            return "cvh1_%012x_%s".format(size, hasher.hexdigest())
        }

        private fun readFully(
            ch: java.nio.channels.FileChannel,
            buf: ByteBuffer,
            hasher: Blake2b
        ) {
            buf.clear()
            while (buf.hasRemaining()) {
                val r = ch.read(buf)
                if (r <= 0) break
            }
            val len = buf.position()
            if (len > 0) hasher.update(buf.array(), 0, len)
        }
    }
}
