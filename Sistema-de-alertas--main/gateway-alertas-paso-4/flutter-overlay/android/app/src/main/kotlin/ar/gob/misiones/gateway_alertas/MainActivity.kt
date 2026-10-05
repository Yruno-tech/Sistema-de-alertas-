package ar.gob.misiones.gateway_alertas

import android.Manifest
import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.telephony.SmsManager
import android.telephony.SmsMessage
import android.telephony.SubscriptionManager
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject

class MainActivity : FlutterActivity() {
    private var permissionResult: MethodChannel.Result? = null
    private var importResult: MethodChannel.Result? = null
    private var resumed = false
    private val journal by lazy { SmsJournal(applicationContext) }
    private val vault by lazy { ConnectionVault(applicationContext) }

    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
        MethodChannel(engine.dartExecutor.binaryMessenger, "ar.gob.misiones.gateway_alertas/gateway")
            .setMethodCallHandler { call, result ->
                try { handle(call, result) }
                catch (error: Exception) {
                    // Never log tokens, phone numbers or message bodies.
                    result.error("GATEWAY_ERROR", if (error is IllegalArgumentException || error is IllegalStateException)
                        error.message else "Android no pudo completar la operación. Revisá permisos, SIM y almacenamiento.", null)
                }
            }
    }

    override fun onResume() { super.onResume(); resumed = true }
    override fun onPause() { resumed = false; super.onPause() }
    override fun onDestroy() {
        permissionResult?.error("CLOSED", "Se cerró la solicitud de permisos", null)
        importResult?.error("CLOSED", "Se cerró la selección del archivo", null)
        permissionResult = null; importResult = null
        journal.close()
        super.onDestroy()
    }

    private fun status() = mapOf(
        "sendSmsGranted" to (checkSelfPermission(Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED),
        "readPhoneStateGranted" to (checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED),
        "hasTelephonyMessaging" to packageManager.hasSystemFeature("android.hardware.telephony.messaging"),
    )

    private fun subscriptions(): List<Map<String, Any>> {
        check(status()["readPhoneStateGranted"] == true) { "Concedé el permiso de teléfono para elegir la SIM" }
        val manager = getSystemService(SubscriptionManager::class.java)
        return manager.activeSubscriptionInfoList.orEmpty().map {
            mapOf("id" to it.subscriptionId, "label" to "SIM ${it.simSlotIndex + 1} · ${it.carrierName}")
        }
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        fun string(key: String) = requireNotNull(call.argument<String>(key)) { "Falta $key" }
        when (call.method) {
            "status" -> result.success(status())
            "subscriptions" -> result.success(subscriptions())
            "deviceId" -> result.success(vault.deviceId())
            "loadConnection" -> result.success(vault.load())
            "saveConnection" -> { vault.save(string("json")); result.success(null) }
            "importConnection" -> {
                check(importResult == null) { "Ya hay un selector abierto" }
                importResult = result
                try {
                    startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
                    }, 6202)
                } catch (error: Exception) { importResult = null; throw error }
            }
            "requestPermissions" -> {
                check(permissionResult == null) { "Ya se están solicitando permisos" }
                val missing = arrayOf(Manifest.permission.SEND_SMS, Manifest.permission.READ_PHONE_STATE)
                    .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
                if (missing.isEmpty()) result.success(status())
                else { permissionResult = result; requestPermissions(missing.toTypedArray(), 6201) }
            }
            "openSettings" -> {
                startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:$packageName"))); result.success(null)
            }
            "keepAwake" -> {
                if (call.argument<Boolean>("active") == true) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                result.success(null)
            }
            "prepare" -> {
                val job = JSONObject(string("job"))
                validateJob(job, string("serverId")); journal.prepare(string("serverId"), job)
                result.success(null)
            }
            "sendPrepared" -> {
                sendPrepared(string("serverId"), string("id"), requireNotNull(call.argument<Int>("simId")))
                result.success(null)
            }
            "prepared" -> result.success(journal.prepared(string("serverId")))
            "reports" -> { journal.expireSubmissions(); result.success(journal.reports(string("serverId"))) }
            "recent" -> { journal.expireSubmissions(); result.success(journal.recent(string("serverId"))) }
            "ack" -> { journal.ack(string("serverId"), string("id"), requireNotNull(call.argument<Int>("revision"))); result.success(null) }
            "abandon" -> { journal.abandon(string("serverId"), string("id")); result.success(null) }
            else -> result.notImplemented()
        }
    }

    private fun validateJob(job: JSONObject, serverId: String) {
        val config = JSONObject(requireNotNull(vault.load()) { "Importá el archivo de emparejamiento" })
        require(config.getString("serverId") == serverId && config.getString("mode") == "test") { "Servidor o modo inválido" }
        require(config.getDouble("expiresAt") * 1000 > System.currentTimeMillis()) { "El emparejamiento venció" }
        require(job.getString("mode") == "test") { "Solo se admiten pruebas" }
        require(job.getDouble("expires_at") * 1000 > System.currentTimeMillis()) { "La orden de envío venció" }
        val phone = job.getString("phone")
        val allowed = config.getJSONArray("allowedNumbers")
        require(allowed.length() in 1..3 && (0 until allowed.length()).any { allowed.getString(it) == phone }) { "Destinatario no autorizado" }
        require(Regex("^\\+549[0-9]{10}$").matches(phone)) { "Número inválido" }
        for (field in listOf("id", "batch_id", "ticket"))
            require(Regex("^[a-f0-9-]{36}$").matches(job.getString(field))) { "Identificador inválido" }
        val message = job.getString("message")
        require(message.length <= 160 && Regex("^PRUEBA - [A-Za-z0-9 .,;:()/_-]+$").matches(message)) { "Mensaje fuera del modo de prueba" }
        require(SmsMessage.calculateLength(message, false)[0] == 1) { "El mensaje ocupa más de un segmento" }
    }

    @Suppress("DEPRECATION")
    private fun sendPrepared(serverId: String, id: String, simId: Int) {
        check(resumed) { "Mantené el gateway abierto para enviar" }
        check(status().values.all { it }) { "Revisá los permisos de SMS y teléfono" }
        check(subscriptions().any { it["id"] == simId }) { "La SIM seleccionada ya no está activa" }
        val job = journal.job(serverId, id) ?: error("No existe el trabajo preparado")
        validateJob(job, serverId)
        val manager = if (Build.VERSION.SDK_INT >= 31)
            getSystemService(SmsManager::class.java).createForSubscriptionId(simId)
        else SmsManager.getSmsManagerForSubscriptionId(simId)
        require(manager.divideMessage(job.getString("message")).size == 1) { "El mensaje requiere varios segmentos" }
        // Commit UNKNOWN before crossing into the modem API. Never repeat this call for this job.
        if (!journal.beginSubmission(serverId, id)) return
        try {
            manager.sendTextMessage(job.getString("phone"), null, job.getString("message"),
                receipt(serverId, id, "SENT"), receipt(serverId, id, "DELIVERED"))
            journal.submitted(serverId, id)
        } catch (_: Exception) {
            journal.uncertain(serverId, id, "Android interrumpió el envío. Revisar sin reenviar automáticamente")
        }
    }

    private fun receipt(serverId: String, id: String, kind: String): PendingIntent {
        val intent = Intent(this, SmsResultReceiver::class.java).apply {
            action = "$packageName.$kind"
            data = Uri.parse("gateway://result/$serverId/$id/$kind")
            putExtra("serverId", serverId); putExtra("jobId", id); putExtra("kind", kind)
        }
        // Explicit receiver; mutable so Android can attach the status-report PDU.
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
        return PendingIntent.getBroadcast(this, 0, intent, flags)
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, grants: IntArray) {
        super.onRequestPermissionsResult(code, permissions, grants)
        if (code == 6201) { permissionResult?.success(status()); permissionResult = null }
    }

    @Deprecated("Activity result bridge for Flutter without third-party plugins")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 6202) return
        val result = importResult ?: return
        importResult = null
        if (resultCode != Activity.RESULT_OK || data?.data == null) { result.success(null); return }
        try {
            val bytes = contentResolver.openInputStream(data.data!!)?.use { stream ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(1024)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
                    require(output.size() + count <= 16384) { "El archivo supera 16 KB" }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            } ?: error("Archivo inaccesible")
            result.success(String(bytes, Charsets.UTF_8))
        } catch (_: Exception) { result.error("IMPORT", "No se pudo leer el archivo de emparejamiento (máximo 16 KB)", null) }
    }
}
