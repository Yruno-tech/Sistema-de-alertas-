# Programa de Alertas · servidor 0.5.0

Esta versión incluye el panel `/gateway` con emparejamiento QR, selección de edificio/oficina, destinatarios de Sheets y envío mediante una app Android Flutter. La guía completa de instalación y actualización es `LEEME.md`, en la raíz del ZIP PC + Flutter.

Para iniciar después de instalar dependencias, abrí `INICIAR.bat` o ejecutá `.venv\Scripts\python.exe iniciar_gateway.py`.

El instalador conserva `.env`, `credentials`, `data` y `.venv`. El rango de Sheets debe incluir `oficina`, por ejemplo `DESTINATARIOS!A1:I`. `sms=NO` es una exclusión válida. No existe el límite fijo de tres destinatarios. La sincronización es automática cada 15 segundos; se configura con `SHEETS_SYNC_SECONDS`.

`/gateway` envía SMS reales con prefijo PRUEBA cuando pulsás Enviar ahora y el celular está activo. Las rutas antiguas `/`, `/history` y las simulaciones siguen sin enviar SMS ni correo. `/recipients` muestra la copia local y permite sincronización manual. Se mantiene `APP_MODE=test` y `SMS_ENABLED=false` para esas pantallas antiguas.

Antes de habilitar Enviar ahora, el panel comprueba que exista la cuenta de servicio, esté configurado el ID/rango de Sheets, haya una sincronización válida y el celular esté conectado. Si falta algo, muestra el problema y el acceso para corregirlo; el servidor también rechaza el envío hasta que los requisitos estén listos.

Al primer acceso se crea una cuenta administradora. Esa cuenta agrega operadores desde **Cuentas**; hace falta iniciar sesión para acceder a cualquier pantalla, incluidas Simular, Destinatarios e Historial. Sin sesión, se ocultan las opciones y se redirige al inicio de sesión. Cada envío conserva el nombre y usuario que lo inició. Las contraseñas se guardan como hash y las sesiones vencen a las 12 horas. El panel continúa limitado a la computadora local.

La administradora puede importar desde **Cuentas** el JSON de la cuenta de servicio de Google. Se valida antes de reemplazar la clave actual y se guarda en la ruta `GOOGLE_SERVICE_ACCOUNT_FILE` (por defecto `credentials/service-account.json`). Después, compartí la hoja con el `client_email` de esa cuenta como Lector. No pegues ni envíes el contenido de la clave por chat, y no la copies al celular.

El tipo **Alarma de Situación Controlada** requiere un motivo y limita su longitud según el edificio para que el mensaje completo no supere los 160 caracteres de un SMS.

No almacenes las credenciales de Google en el teléfono. El QR ya entrega a la app su propio emparejamiento, sin transferir archivos manualmente.
