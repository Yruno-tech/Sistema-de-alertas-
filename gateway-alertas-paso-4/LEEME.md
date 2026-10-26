# Gateway de alertas · actualización QR

Servidor 0.5.0 · app Flutter 0.3.0 · protocolo 2.

Desde la PC elegís edificio, oficina y aviso. La misma pantalla muestra el mensaje y cuántas personas lo recibirán; **Enviar ahora** pone los SMS en cola con un solo clic. El celular usa su SIM institucional.

Esta versión incorpora QR, elimina el límite fijo de tres personas y acepta `sms=NO` como una exclusión normal. Conserva el prefijo **PRUEBA**: los SMS del gateway son reales y consumen los servicios de la línea. No se enviaron mensajes durante la preparación del paquete.

## 1. Actualizar la computadora

Detené los pendientes del gateway anterior, esperá los resultados disponibles y cerrá el programa de la PC con Ctrl+C. Cerrá también la app del celular antes de actualizar. Conservá una copia de tu proyecto actual.

Descomprimí el ZIP. Abrí CMD o PowerShell dentro de la carpeta que contiene este LEEME y `instalar_actualizacion.py`. Ejecutá, reemplazando la ruta por la de tu proyecto:

```bat
py instalar_actualizacion.py --servidor "C:\ruta\ProgramaAlertas"
```

El instalador respalda el código reemplazado y conserva `.env`, `credentials`, `data` y `.venv`. **No borres la base ni las credenciales de Google.**

Entrá en tu proyecto e instalá las dependencias, incluso si la versión anterior funcionaba:

```bat
cd /d "C:\ruta\ProgramaAlertas"
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`cd /d` corresponde a CMD; en PowerShell usá `cd "C:\ruta\ProgramaAlertas"`.

Si no existe `.venv`, crealo primero con `py -m venv .venv`. Requiere Python 3.11 o posterior. Las dependencias incluyen FastAPI, Jinja2, formularios, dotenv, cliente de Google, criptografía y **qrcode con Pillow**, que genera la imagen QR.

En tu `.env`, verificá que el rango incluya la columna I, donde está `oficina`:

```text
GOOGLE_SHEETS_RANGE=DESTINATARIOS!A1:I
SHEETS_SYNC_SECONDS=15
```

Mantené el nombre real de tu pestaña si es distinto de DESTINATARIOS. El valor 15 es el intervalo predeterminado aunque no agregues la segunda línea. La variable antigua `TEST_RECIPIENT_LIMIT=3` ya no se utiliza; podés quitarla.

Conservá `APP_MODE=test` y `SMS_ENABLED=false`: esas opciones pertenecen a las pantallas de simulación. El botón **Enviar ahora** de `/gateway` autoriza por separado SMS reales de prueba.

## 2. Actualizar la app Flutter

Comprobá que tengas Flutter, Android Studio y las herramientas Android:

```bat
flutter --version
flutter doctor -v
flutter doctor --android-licenses
flutter devices
```

Este código fue verificado con Flutter 3.35.7 y Dart 3.9.2; requiere Flutter 3.35/Dart 3.9 o superiores. Si falta el entorno Android, seguí https://docs.flutter.dev/platform-integration/android/setup. Deben estar instalados Android SDK, Build-Tools, Platform-Tools y Command-line Tools en las versiones que solicite tu proyecto.

Si ya tenés el proyecto `gateway_alertas` de la entrega anterior, usalo. Si todavía no existe, crealo en tu carpeta de trabajo:

```bat
flutter create --platforms=android --android-language=kotlin --org ar.gob.misiones gateway_alertas
```

Desde la carpeta descomprimida del ZIP, aplicá la actualización:

```bat
py instalar_actualizacion.py --flutter "C:\ruta\gateway_alertas"
```

El instalador exige conservar `applicationId = ar.gob.misiones.gateway_alertas`. No modifica Gradle ni reemplaza la configuración local del SDK. Si tu proyecto tiene otro identificador, usá el proyecto creado con el comando anterior o adaptá las clases y el manifiesto de manera consistente.

Dentro del proyecto Flutter, ejecutá:

```bat
flutter pub get
flutter analyze
flutter test
flutter run
```

`pub get` instala las dependencias declaradas: **mobile_scanner 7.4.2** para leer QR y **crypto** para verificar la identidad del servidor. El envío SMS sigue usando Kotlin nativo, y HTTPS usa `dart:io`.

Conectá el Android físico por USB para instalar y aceptá la depuración USB. Elegí el teléfono cuando Flutter lo solicite. Después de instalar, la comunicación con la PC usa Wi-Fi; no necesitás USB para emparejar ni para operar. Debés recompilar la aplicación completa: **hot reload no actualiza Kotlin, permisos ni plugins**.

Para generar un APK en tu equipo:

```bat
flutter build apk --debug
```

Queda en `build\app\outputs\flutter-apk\app-debug.apk`. Este ZIP contiene fuentes, no un APK compilado. Para actualizar sobre la app anterior conservá la misma firma. No desinstales una app con resultados pendientes: podría perderse su registro local.

## 3. Conectar por QR una vez

1. Poné PC y celular en la misma red Wi-Fi que permita comunicación entre dispositivos.
2. En `ProgramaAlertas`, hacé doble clic en **INICIAR.bat**. Se abre el panel automáticamente. También podés ejecutar `.venv\Scripts\python.exe iniciar_gateway.py`.
3. En el panel, pulsá **Conectar celular (QR)**.
4. En la app, pulsá **Escanear QR** y concedé permiso de cámara. Apuntá al QR de la PC.
5. Concedé los permisos SMS/teléfono, seleccioná la SIM institucional y pulsá **Activar gateway**.

El panel debe mostrar **Celular listo para recibir avisos**. La conexión y la SIM elegida quedan guardadas; no necesitás volver a escanear en cada inicio. El QR vence en cinco minutos y vincula un teléfono. Generá otro si vence. No hace falta copiar archivos JSON ni escribir tokens.

Al iniciar la PC se detecta la IP local y se actualiza automáticamente la configuración anterior. Si Windows pregunta por el firewall, permití a Python comunicarse en tu red privada. El teléfono necesita acceder al puerto TCP 8443; el panel 8000 se abre solo desde la PC. No se requiere abrir puertos en el router.

Si la PC tiene VPN o varios adaptadores y elige otra IP, ejecutá:

```bat
.venv\Scripts\python.exe iniciar_gateway.py --ip 192.168.1.20
```

Reemplazá la IP por la IPv4 real de tu adaptador Wi-Fi, visible con `ipconfig`. Si cambia la IP, reiniciá el programa y escaneá el nuevo QR. También se puede renovar el emparejamiento con otro QR si vence su credencial. El QR protege la conexión mediante la huella del certificado; no se desactiva la verificación de identidad del servidor.

## 4. Uso diario y envío

1. Abrí **INICIAR.bat** en la PC. En el celular, abrí la app y pulsá **Activar gateway**.
2. Elegí edificio, oficina —o todas— y tipo de aviso. El mensaje y el número de destinatarios se actualizan en esa misma pantalla.
3. Pulsá **Enviar ahora a N personas**.

No hay que habilitar otro interruptor, escribir CONFIRMAR ni pasar por otra página. El botón autoriza el envío real del mensaje visible. Para la primera comprobación física elegí una oficina con un número propio/autorizado.

El tipo **Alarma de Situación Controlada** requiere indicar el motivo por el que finaliza la alerta. El límite del motivo se calcula según el edificio para que el SMS completo, incluido el prefijo PRUEBA, no supere 160 caracteres.

En Seguimiento aparecen los estados por destinatario y los botones **Pausar pendientes**, **Continuar pendientes** y **Detener pendientes de este aviso**. Solo se procesa un lote a la vez. Un SMS cuyo inicio ya fue autorizado puede completarse aunque se detenga el resto.

La app consulta al servidor aproximadamente cada segundo mientras está activa. El intervalo mínimo inicial entre SMS es de **2 segundos**, configurable entre 1 y 60 en Ajustes del envío. Se espera también el resultado del envío anterior: la velocidad real depende de Android, señal y operadora, y no equivale a entrega instantánea a todos.

## 5. Destinatarios flexibles

Primera fila de Sheets:

```text
id | nombre | telefono | correo | edificio | activo | sms | correo_habilitado | oficina
```

- `activo=SI` y `sms=SI`: recibe SMS si coincide con edificio y oficina seleccionados.
- `sms=NO`: se conserva la persona y se excluye del SMS. No es un error; puede incluso no tener teléfono.
- `activo=NO`: se excluye del envío.
- Las casillas FALSE o desmarcadas también se interpretan como NO.
- Una nueva persona habilitada entra en el próximo aviso después de sincronizar; no requiere configurar nuevamente el celular ni autorizar una lista fija.
- No hay máximo fijo de tres en PC ni en la app. El plan de la operadora y el teléfono siguen teniendo sus propias condiciones y capacidades.

La sincronización se ejecuta al iniciar y luego cada 15 segundos, más el tiempo de respuesta de Google. Podés forzarla desde Destinatarios → Sincronizar ahora. La cantidad visible en el panel corresponde a la copia local sincronizada, no a cambios que Google todavía no respondió.

Cada aviso guarda sus destinatarios al pulsar Enviar. Las personas agregadas después entran en el siguiente aviso; no se agregan silenciosamente a uno que ya empezó. Si la lista cambia entre lo que ves y el clic, se actualiza y permite enviar de nuevo. Si una baja o `sms=NO` ya se sincronizó antes de iniciar el SMS de esa persona, ese pendiente se cancela.

Los errores reales —por ejemplo, teléfono inválido cuando SMS está habilitado— se muestran por fila y excluyen las filas afectadas. Las filas válidas pueden seguir utilizándose. Si toda la lectura falla, se conserva la copia anterior y se bloquean nuevos inicios hasta recuperar una sincronización válida. Esto no ocurre por poner `sms=NO`.

## 6. Estados y alcance

| Estado | Significado |
|---|---|
| En cola | Pendiente de tomar por el celular |
| Reservado | Asignado, todavía sin iniciar el SMS |
| Enviando | Inicio autorizado; puede estar en Android o la red |
| Enviado | Android informó envío correcto |
| Entregado | La operadora confirmó entrega; no implica lectura |
| Fallido | Android informó un error |
| Desconocido | No se puede confirmar el resultado |
| Cancelado | Se detuvo antes de iniciar, venció o cambió la habilitación |

Una entrega puede quedar sin confirmar aunque el SMS haya llegado. Ante fallo o resultado desconocido, la cola se pausa; revisá el detalle, la línea y el destinatario antes de continuar pendientes. **No se repite automáticamente un SMS de resultado incierto.** Los reintentos de comunicación repiten la misma solicitud, no crean otro lote.

Mantené la app abierta; mientras esté activa mantiene encendida la pantalla. Al salir o apagarla se pausa la toma de nuevos trabajos y hay que volver a activarla. Esta entrega no incluye servicio de segundo plano, FCM, correo ni modo de producción para emergencias reales. Primero falta comprobar QR, permisos, SIM, envío y tiempos con tu teléfono y operadora.

## 7. Verificación y ayuda

Resultados de las pruebas de esta entrega: `VERIFICACION.md`.

Para repetir pruebas de servidor sin enviar SMS:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

En Flutter: `flutter analyze` y `flutter test`.

Si no conecta, comprobá que INICIAR siga abierto, PC y teléfono tengan comunicación por Wi-Fi, el puerto 8443 esté permitido y el QR muestre la IP correcta. Si el QR venció, generá otro. Si no aparece la SIM, revisá los permisos SMS/teléfono y volvé a actualizar SIM. Una app anterior al protocolo 2 debe actualizarse y emparejarse por QR.

Las pantallas antiguas de simulación siguen disponibles desde el menú y no envían SMS. Para ordenar envíos reales de prueba usá `/gateway`, que abre INICIAR.

Referencias: https://pub.dev/packages/mobile_scanner · https://pub.dev/packages/crypto · https://developer.android.com/reference/android/telephony/SmsManager
