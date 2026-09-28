package ar.gob.misiones.gateway_alertas

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.SmsMessage

/** Explicit manifest receiver: results survive Activity destruction and ordinary process recreation. */
class SmsResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val server = intent.getStringExtra("serverId") ?: return
        val id = intent.getStringExtra("jobId") ?: return
        SmsJournal(context).use { journal ->
            when (intent.getStringExtra("kind")) {
                "SENT" -> journal.sent(server, id, resultCode == Activity.RESULT_OK,
                    if (resultCode == Activity.RESULT_OK) "Enviado; entrega aún sin confirmar"
                    else "Falló el envío (código Android $resultCode); revisar SIM, señal y saldo")
                "DELIVERED" -> {
                    val pdu = intent.getByteArrayExtra("pdu")
                    val format = intent.getStringExtra("format")
                    val sms = try { if (pdu != null && format in listOf("3gpp", "3gpp2"))
                        SmsMessage.createFromPdu(pdu, format) else null } catch (_: Exception) { null }
                    val status = sms?.status
                    val delivered = sms?.isStatusReportMessage == true &&
                        ((format == "3gpp" && status == 0) || (format == "3gpp2" && status == (2 shl 16)))
                    val failed = sms?.isStatusReportMessage == true && status != null &&
                        ((format == "3gpp" && status in 0x40..0x7f) ||
                         (format == "3gpp2" && (status ushr 24 and 3) == 3))
                    val delivery = if (delivered) "DELIVERED" else if (failed) "FAILED" else "UNKNOWN"
                    val detail = if (delivered) "Entrega confirmada por la operadora"
                        else if (failed) "La operadora informó una entrega fallida"
                        else "Llegó un informe de estado sin confirmación final de entrega"
                    journal.delivered(server, id, delivery, detail)
                }
            }
        }
    }
}
