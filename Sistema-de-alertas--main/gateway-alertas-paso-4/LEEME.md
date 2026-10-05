# Programa de Alertas · PC + gateway Flutter · Paso 4

Esta actualización conecta la computadora con el teléfono Android que tiene la SIM institucional. Desde la PC elegís edificio y oficina, revisás el mensaje y los destinatarios y escribís CONFIRMAR. El teléfono recibe un trabajo por destinatario, envía con la SIM elegida y comunica el resultado.

El paquete contiene código fuente, un instalador de actualización con respaldo y pruebas que no envían SMS. Está preparado para el piloto con tus tres destinatarios autorizados. Los mensajes enviados desde **Enviar SMS desde PC** son SMS reales de prueba y consumen los servicios de la línea.

## 1. Qué necesitás

En la computadora:

- Tu proyecto `ProgramaAlertas` del Paso 3, con su `.env`, credenciales y base de datos.
- Python 3.11 o posterior. Comprobá con `py --version`.
- Flutter **3.35 o posterior**, incluido Dart. Comprobá con `flutter --version`.
- Android Studio, Android SDK Platform, Build-Tools, Platform-Tools y Command-line Tools. El proyecto generado por Flutter indica qué versión de SDK necesita.
- Acceso a Internet para instalar dependencias. Para el uso, PC y celular deben comunicarse en la misma red Wi-Fi.

En el teléfono:

- Android compatible con el `minSdk` de tu proyecto Flutter (este código requiere como mínimo API 23; Flutter puede requerir una superior).
- SIM institucional activa y un SMS manual ya comprobado. Se necesita un teléfono físico para enviar SMS reales.
- Depuración USB para instalar desde `flutter run` y permisos de SMS/teléfono para esta app.

Si falta Flutter o Android Studio, seguí la [instalación oficial de Flutter para Android](https://docs.flutter.dev/platform-integration/android/setup). Después ejecutá:

```bat
flutter doctor -v
flutter doctor --android-licenses
flutter devices
```

Leé y aceptá las licencias que correspondan en tu equipo. Corregí los problemas de **Android toolchain** antes de compilar. No hace falta configurar Chrome, Visual Studio de escritorio ni iOS para este gateway.

**Dependencias Flutter:** solamente `flutter` y `flutter_test`, incluidas en el SDK. No hay paquetes de SMS, HTTP, Firebase ni almacenamiento para instalar desde terceros. Se usa `dart:io` para HTTPS y un canal nativo Kotlin para Android. `flutter pub get` sigue siendo necesario.

**Dependencias Python:** `requirements.txt` declara FastAPI, Jinja2, python-multipart, python-dotenv, Google API Client, google-auth y cryptography. Se instalan explícitamente abajo.

## 2. Actualizar el servidor existente

Detené el servidor actual con Ctrl+C. Cerrá también una instancia previa del gateway si la hubiera.

Descomprimí este ZIP. Dentro de la carpeta que contiene este LEEME y `instalar_actualizacion.py`, abrí CMD o PowerShell. Adaptá la ruta a tu carpeta real:

```bat
py instalar_actualizacion.py --servidor "C:\Proyectos\ProgramaAlertas"
```

El instalador verifica que sea el proyecto del Paso 3, guarda un ZIP con el código que va a reemplazar y copia los archivos actualizados. Conserva tu `.env`, `credentials` y `data`. La carpeta `servidor` del paquete es la fuente de la actualización; no se coloca anidada dentro de tu proyecto.

Ahora entrá en tu proyecto:

```bat
cd C:\Proyectos\ProgramaAlertas
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Este comando utiliza directamente el entorno virtual; no necesita activar PowerShell. Si no existe `.venv`, crealo primero con `py -m venv .venv`.

Editá **solamente el rango** en tu `.env` existente para incluir la novena columna:

```dotenv
GOOGLE_SHEETS_RANGE=DESTINATARIOS!A1:I
APP_MODE=test
SMS_ENABLED=false
TEST_RECIPIENT_LIMIT=3
```

Conservá el nombre real de tu pestaña si no es `DESTINATARIOS`, el ID de la planilla y la ruta al JSON de Google. Si la pestaña tiene espacios, por ejemplo: `GOOGLE_SHEETS_RANGE='Personal activo'!A1:I`.

**No cambies SMS_ENABLED a true.** Esa opción sigue deshabilitando envíos desde las pantallas antiguas de simulación. El nuevo envío real de prueba tiene su habilitación propia y explícita en `/gateway`.

La fila de encabezados queda:

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| id | nombre | telefono | correo | edificio | activo | sms | correo_habilitado | oficina |

Ejemplos de oficina: `Mesa de entradas`, `Informática`, `Secretaría`. El filtro utiliza el valor de oficina **dentro del edificio elegido**. Espacios repetidos se normalizan; mantené una escritura uniforme para no crear dos oficinas distintas.

La migración agrega la columna a SQLite al iniciar y conserva los destinatarios, las alertas y las simulaciones existentes. Hasta la primera sincronización, los registros antiguos tendrán oficina vacía. “Todas las oficinas” también los incluye.

## 3. Configurar el acceso del teléfono

En la PC ejecutá:

```bat
ipconfig
.venv\Scripts\python.exe configurar_gateway.py
```

El asistente te pide:

1. La **IPv4 del adaptador Wi-Fi de la computadora**, por ejemplo `192.168.1.50`. No uses `127.0.0.1`, la IP del celular ni la de una VPN.
2. Entre uno y tres números autorizados, separados por coma, en formato `+549` seguido de diez dígitos. Deben coincidir con los destinatarios de prueba de Sheets. No ingreses el número de la SIM emisora salvo que también sea un destinatario de prueba.

El asistente crea un certificado local HTTPS válido durante 30 días, una credencial exclusiva del gateway y una copia de respaldo de la base existente. Genera estos archivos en **tu computadora**:

- `credentials/gateway-config.json`: configuración del servidor y hash de la credencial.
- `credentials/gateway-server.pem`: certificado público.
- `credentials/gateway-server.key`: clave privada; permanece en la PC.
- `emparejar-gateway.json`: contiene la dirección, certificado público, credencial y números autorizados del teléfono.

Copiá **solamente `emparejar-gateway.json` por USB al teléfono**. El archivo otorga acceso al gateway: mantenelo privado y quitá la copia de Descargas después de importarla en la app. Nunca copies `service-account.json` ni `gateway-server.key` al celular.

El certificado se confía dentro de la app. No tenés que instalarlo como certificado de todo Android ni desactivar la validación HTTPS.

## 4. Actualizar o crear el proyecto Flutter

Si ya usás la app del Paso 1, conservá ese proyecto y su identificador `ar.gob.misiones.gateway_alertas`. Desde la carpeta descomprimida ejecutá:

```bat
py instalar_actualizacion.py --flutter "C:\Proyectos\gateway_alertas"
```

El instalador guarda un respaldo y copia `lib`, las clases Kotlin, el manifiesto, `pubspec.yaml` y las pruebas. Conserva Gradle, los recursos e identificadores generados por Flutter. Si tu `applicationId` es distinto, el instalador se detiene antes de copiar: usá el proyecto del Paso 1 con el identificador indicado o creá un proyecto nuevo como se muestra abajo.

Si todavía **no tenés un proyecto Flutter**, desde `C:\Proyectos` ejecutá:

```bat
flutter create --platforms=android --org ar.gob.misiones --project-name gateway_alertas -a kotlin gateway_alertas
```

Después volvé a la carpeta descomprimida y aplicá el mismo comando `instalar_actualizacion.py --flutter ...`.

Con el teléfono conectado por USB, entrá en la carpeta Flutter:

```bat
cd C:\Proyectos\gateway_alertas
flutter pub get
flutter analyze
flutter test
flutter devices
flutter run -d IDENTIFICADOR_DEL_TELEFONO
```

Reemplazá `IDENTIFICADOR_DEL_TELEFONO` por el que muestra `flutter devices`. Si solamente hay un Android conectado, podés usar `flutter run` y seleccionarlo.

Los cambios Kotlin requieren **detener la ejecución anterior y recompilar**: hot reload no alcanza. La instalación sobre la app anterior necesita conservar el mismo applicationId y la misma firma de desarrollo. Si Android informa firmas incompatibles, no borres una app con envíos pendientes: detené primero la cola y revisá el estado en la PC.

Para generar un APK de desarrollo cuando la compilación funcione:

```bat
flutter build apk --debug
```

El resultado estará en `build\app\outputs\flutter-apk\app-debug.apk`. El ZIP entregado contiene las fuentes; la generación e instalación del APK se realiza con el SDK Android de tu equipo.

## 5. Encender el sistema

En la carpeta Python:

```bat
.venv\Scripts\python.exe iniciar_gateway.py
```

Este comando mantiene dos procesos:

| Componente | Dirección | Uso |
|---|---|---|
| Panel de la PC | `http://127.0.0.1:8000/gateway` | Operar desde esa computadora |
| API del teléfono | `https://IP_DE_LA_PC:8443` | Acceso autenticado de la app Flutter |

Si Windows pide acceso para Python, permitilo en tu red privada de confianza. El celular necesita acceder al puerto TCP 8443. No abras puertos del router a Internet. El puerto 8000 queda limitado a la misma PC. En redes Wi-Fi de invitados puede haber aislamiento entre dispositivos; en ese caso pedí una red que permita la comunicación PC–celular.

Abrí `http://127.0.0.1:8000/recipients` en la PC, pulsá **Sincronizar ahora** y comprobá que aparezca la columna Oficina con tus valores y que no haya filas rechazadas.

En la app Android:

1. Pulsá **Importar emparejar-gateway.json** y seleccioná el archivo copiado.
2. Pulsá **Solicitar permisos / actualizar SIM** y concedé SMS y teléfono.
3. Elegí la SIM institucional. En dual SIM, revisá cuidadosamente cuál seleccionás.
4. Pulsá **Activar gateway**. La app mantendrá la pantalla encendida mientras esté activa y visible.

## 6. Primera orden desde la PC

1. Abrí `/gateway`. Esperá que indique **Teléfono activo** y la SIM.
2. Pulsá **Habilitar envíos de prueba**.
3. Elegí un edificio y pulsá **Cargar oficinas de este edificio**.
4. Elegí una oficina con un solo destinatario autorizado para la primera prueba. Luego podés elegir una oficina o todas las oficinas que sumen hasta tres.
5. Elegí **Mantenimiento/Pruebas** y pulsá **Revisar mensaje y destinatarios**.
6. Revisá los nombres, teléfonos enmascarados, oficina y mensaje con prefijo PRUEBA.
7. Escribí **CONFIRMAR** y pulsá **Confirmar y poner SMS en cola**.

El teléfono consulta cada tres segundos mientras la pantalla está abierta. Inicia un SMS, informa su resultado y espera al menos 30 segundos antes del siguiente. La PC actualiza el seguimiento cada cuatro segundos.

| Estado | Qué significa |
|---|---|
| Vista previa | Todavía no está autorizado el envío |
| En cola | Pendiente de que lo tome el teléfono |
| Reservado | Asignado al teléfono; todavía puede cancelarse |
| Enviando | Se autorizó el inicio; puede estar en Android o en la red |
| Enviado | Android informó envío correcto |
| Entregado | La operadora confirmó la recepción en destino; no confirma lectura |
| Fallido | Android informó un error de envío |
| Desconocido | No se conoce con certeza el resultado; requiere revisión |
| Cancelado | Se detuvo antes de iniciar, venció o cambió el destinatario |

La entrega puede permanecer sin confirmar aunque el destinatario haya recibido el SMS. Un informe de entrega fallida se muestra en el detalle del mensaje enviado.

**Pausar gateway** frena el inicio de pendientes; **Habilitar envíos de prueba** permite continuarlos dentro de la ventana de diez minutos. **Detener envíos pendientes de esta prueba** los cancela definitivamente. Un SMS cuyo inicio ya se autorizó puede completarse después de pausar o detener.

Si un SMS falla o queda desconocido, la PC pausa la cola. Revisá el resultado y la línea antes de volver a habilitar los restantes. Los fallidos y desconocidos no vuelven automáticamente a la cola.

## 7. Qué cubre esta versión

- Usa los destinatarios sincronizados de Sheets y permite filtrar por edificio y oficina.
- Guarda una foto del mensaje y destinatarios de la vista previa. Repetir su confirmación no crea otro lote.
- Revisa nuevamente actividad, habilitación SMS, teléfono, edificio y oficina antes de iniciar cada trabajo.
- Un cambio de sincronización después de la vista previa obliga a revisarla de nuevo.
- Hasta tres números expresamente autorizados; rechaza listas mayores y números fuera de la autorización, sin recortar la lista.
- Mensajes PRUEBA con caracteres conservadores y un solo segmento, verificado también con Android.
- Cola y auditoría persistentes en SQLite; registro local de intentos e informes pendientes en el teléfono.
- Credencial y certificado de 30 días, HTTPS y vinculación al primer teléfono que presenta la credencial.
- Confirmación desde el panel local y rechazo de formularios enviados desde otros sitios.
- Las simulaciones y su historial siguen disponibles en las opciones antiguas.

Si la conexión se pierde, se vuelven a intentar las comunicaciones con el servidor. **No se repite automáticamente la llamada para enviar un mismo SMS.** El teléfono registra el inicio antes de llamar al módem; si se cierra justo en ese momento, puede quedar desconocido incluso si no llegó a enviar. Esto evita decidir a ciegas un segundo envío; no garantiza entrega ni “exactamente una vez” en la red de la operadora.

Al salir de la app o apagar la pantalla se pausa la toma de trabajos y hay que volver a activarla. Los resultados recibidos por Android se guardan y se informan al reabrir. El cierre forzado, el apagado o borrar datos pueden impedir que Android entregue callbacks; por eso existe el estado desconocido. El servicio en segundo plano, producción institucional sin límite de tres, correo y avisos FCM quedan para la siguiente etapa.

El servidor conserva la copia local de destinatarios si Google falla. Para este piloto de SMS reales, una sincronización fallida o con filas rechazadas bloquea nuevas preparaciones/inicios hasta corregirla y sincronizar. Las vistas de consulta y simulación siguen usando la copia conservada.

## 8. Problemas habituales

- **Teléfono esperando conexión:** verificá que `iniciar_gateway.py` siga abierto, la IP importada, misma red y firewall TCP 8443. No uses `localhost` en la configuración del teléfono.
- **Certificado no válido:** revisá fecha y hora del celular, fecha de vencimiento y archivo importado. La app no acepta certificados distintos del emparejamiento.
- **SIM no aparece:** habilitá teléfono en los ajustes de permisos, verificá la SIM y volvé a pulsar actualizar SIM.
- **No se puede confirmar:** activá la app, habilitá el gateway en la PC y generá otra vista previa si venció o sincronizaste nuevamente.
- **Hay destinatarios no autorizados o más de tres:** ajustá el edificio/oficina a tus destinatarios de prueba. No modifiques el límite para saltarte la etapa de prueba.
- **Fallido/desconocido:** revisá el detalle y comprobá señal, SIM, saldo y recepción con el destinatario. No generes otra alerta idéntica hasta aclarar el intento anterior.
- **Código HTTP 409 por otro teléfono:** la credencial está vinculada al primer dispositivo. No se permite cambiar de teléfono o borrar sus datos durante una cola activa.
- **La consola muestra “Sin resultados después de 2 minutos”:** no se reenvía el mismo trabajo. Los informes tardíos de envío o entrega aún pueden actualizarlo.

Si cambió la IP de la PC o vencieron los 30 días: detené los pendientes, dejá que se informen los resultados disponibles y cerrá ambos servidores. Mové los cuatro archivos de emparejamiento del apartado 3 a una carpeta privada de respaldo, conservando los archivos de Google. Ejecutá de nuevo `configurar_gateway.py`, importá el nuevo JSON en el **mismo teléfono** y reiniciá. Conviene reservar la IP local de la PC en el router para evitar cambios frecuentes. No se reenvían trabajos viejos como parte de la renovación.

## 9. Pruebas sin SMS

Desde `ProgramaAlertas`:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

Las pruebas usan números ficticios, una base temporal y clientes simulados; no consultan Sheets ni usan tu teléfono. Cubren migración, oficina, límite/autorización, confirmación repetida, reservas concurrentes, resultados repetidos/tardíos, expiración, detención, reinicio, errores de sincronización, HTTPS, credencial y protección del panel.

Desde el proyecto Flutter:

```bat
flutter analyze
flutter test
```

Las pruebas Flutter sustituyen Android y el servidor para comprobar pérdida de respuestas, cancelación, pausa al salir de la app y validación del emparejamiento. La comprobación final de envío y entrega se hace en tu teléfono y operadora con el procedimiento del apartado 6. Consultá `VERIFICACION.md` para los resultados comprobados al preparar el paquete.

Referencias de implementación: [SmsManager y resultados del envío](https://developer.android.com/reference/android/telephony/SmsManager), [estados de entrega de SmsMessage](https://developer.android.com/reference/android/telephony/SmsMessage#getStatus()), [certificados de confianza en Dart](https://api.dart.dev/dart-io/SecurityContext-class.html), [selección de archivos en Android](https://developer.android.com/training/data-storage/shared/documents-files).
