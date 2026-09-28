package ar.gob.misiones.gateway_alertas

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class ConnectionVault(context: Context) {
    private val preferences = context.getSharedPreferences("gateway_connection", Context.MODE_PRIVATE)
    private val alias = "gateway-pairing-v1"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun deviceId(): String {
        preferences.getString("device_id", null)?.let { return it }
        val id = UUID.randomUUID().toString()
        check(preferences.edit().putString("device_id", id).commit()) { "No se pudo guardar el identificador" }
        return id
    }
    fun save(raw: String) {
        require(raw.length <= 16384) { "Archivo demasiado grande" }
        val json = JSONObject(raw)
        require(json.getInt("version") == 1 && json.getString("mode") == "test") { "Configuración incompatible" }
        require(json.getJSONArray("allowedNumbers").length() in 1..3) { "Se admiten hasta tres números" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.doFinal(raw.toByteArray(Charsets.UTF_8))
        check(preferences.edit().putString("cipher", Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP)).commit()) { "No se pudo guardar el emparejamiento" }
    }
    fun load(): String? {
        val encrypted = preferences.getString("cipher", null) ?: return null
        val iv = preferences.getString("iv", null) ?: error("Configuración incompleta")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
        }
        return String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), Charsets.UTF_8)
    }
}
