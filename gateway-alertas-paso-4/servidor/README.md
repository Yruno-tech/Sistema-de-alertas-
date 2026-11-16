# Programa de Alertas · servidor 0.5.0

Esta versión incluye el panel `/gateway` con emparejamiento QR, selección de edificio/oficina, destinatarios de Sheets y envío mediante una app Android Flutter. La guía completa de instalación y actualización es `LEEME.md`, en la raíz del ZIP PC + Flutter.

## Instalar en otra PC Windows

Desde una PC Windows de 64 bits, instalá las herramientas de desarrollo y construí el instalador:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe build_installer.py
```

Se genera `dist\Instalar Gateway de alertas.exe`. Compartí únicamente ese ejecutable.

En cada PC nueva, abrí el instalador con conexión a Internet. Descarga Python 3.14.10 desde python.org, verifica su SHA-256, instala las dependencias y crea un acceso directo en el Escritorio. No requiere permisos de administrador. Cada instalación conserva su propia configuración, base y credenciales; no incluyas ni compartas `.env`, `credentials`, `data` ni `.venv`. El ejecutable no está firmado digitalmente, por lo que Windows puede mostrar una advertencia de SmartScreen.

La app Android se instala y empareja por separado mediante QR. Para usar Google Sheets, cada servidor debe configurarse con el ID de la planilla y su propia cuenta de servicio. Los envíos SMS siguen requiriendo un teléfono Android emparejado con ese servidor.

Para iniciar después de instalar dependencias, abrí `INICIAR.bat` o ejecutá `.venv\Scripts\python.exe iniciar_gateway.py`.

El instalador conserva `.env`, `credentials`, `data` y `.venv`. El rango de Sheets debe incluir `oficina`, por ejemplo `DESTINATARIOS!A1:I`. `sms=NO` es una exclusión válida. No existe el límite fijo de tres destinatarios. La sincronización es automática cada 15 segundos; se configura con `SHEETS_SYNC_SECONDS`.

`/gateway` envía SMS reales con prefijo PRUEBA cuando pulsás Enviar ahora y el celular está activo. Las rutas antiguas `/`, `/history` y las simulaciones siguen sin enviar SMS ni correo. `/recipients` muestra la copia local y permite sincronización manual. Se mantiene `APP_MODE=test` y `SMS_ENABLED=false` para esas pantallas antiguas.

Antes de habilitar Enviar ahora, el panel comprueba que exista la cuenta de servicio, esté configurado el ID/rango de Sheets, haya una sincronización válida y el celular esté conectado. Si falta algo, muestra el problema y el acceso para corregirlo; el servidor también rechaza el envío hasta que los requisitos estén listos.

Al primer acceso se crea una cuenta administradora. Esa cuenta agrega operadores desde **Cuentas**; hace falta iniciar sesión para acceder a cualquier pantalla, incluidas Simular, Destinatarios e Historial. Sin sesión, se ocultan las opciones y se redirige al inicio de sesión. Cada envío conserva el nombre y usuario que lo inició. Las contraseñas se guardan como hash y las sesiones vencen a las 12 horas. El panel continúa limitado a la computadora local.

Desde **Configuración**, la administradora puede guardar el ID o URL y el rango A1 de Google Sheets, e importar el JSON de la cuenta de servicio. Al guardar los datos o la credencial, el programa intenta sincronizar en el momento y muestra el resultado. La clave se valida antes de reemplazar la anterior y se guarda en `GOOGLE_SERVICE_ACCOUNT_FILE` (por defecto `credentials/service-account.json`). Compartí la hoja con el `client_email` de esa cuenta como Lector. No pegues ni envíes el contenido de la clave por chat, y no la copies al celular.

El tipo **Alarma de Situación Controlada** requiere un motivo y limita su longitud según el edificio para que el mensaje completo no supere los 160 caracteres de un SMS.

No almacenes las credenciales de Google en el teléfono. El QR ya entrega a la app su propio emparejamiento, sin transferir archivos manualmente.
