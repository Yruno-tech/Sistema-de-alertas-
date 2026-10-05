# Verificación del paquete · Paso 4

Comprobado al preparar esta entrega:

| Comprobación | Resultado |
|---|---|
| Pruebas Python con pytest | 22 aprobadas |
| Análisis de Flutter (`flutter analyze --no-pub`) | Sin problemas |
| Pruebas Flutter (`flutter test --no-pub`) | 13 aprobadas |
| Compilación de las cuatro clases Kotlin | Aprobada con advertencias tratadas como errores (`-Werror`) |
| Certificado HTTPS generado | Conexión local validada; IP distinta y certificado no confiable rechazados |
| Instalador de actualización | Conservó `.env`, credenciales, base y Gradle; creó respaldos del código reemplazado |
| Rutas antiguas `/health`, `/`, `/recipients`, `/history` | Respuesta 200 en comprobación con base temporal |

Entorno: Python 3.12.14, FastAPI 0.141.1, pytest 8.4.2, Flutter 3.35.7, Dart 3.9.2, Kotlin 2.1.0 y Java 17. Las clases nativas se compilaron contra Android API 36, Flutter embedding de la misma versión y AndroidX Lifecycle 2.7.0.

Se comprobaron tanto los seis casos previos del servidor como las nuevas validaciones y la cola. Las pruebas Flutter incluyen pérdida de respuestas de inicio y de informe, recuperación del trabajo preparado, cancelación antes del envío y pausa al pasar a segundo plano. El módem se sustituye por un simulador en esas pruebas.

No se enviaron SMS reales, no se consultó la planilla privada ni se utilizaron credenciales o teléfonos del usuario. No se generó ni instaló un APK completo en un dispositivo: la verificación Kotlin valida las clases, y la compilación de Flutter/Gradle e instalación en tu Android se realiza con los pasos del LEEME. Falta la prueba física de permisos, SIM, envío e informe de entrega con tu operadora.

Durante la instalación del SDK para verificar esta entrega, una revisión automática bloqueó la detección de infraestructura de Flutter que intentaba consultar metadatos del entorno. Se inspeccionó su implementación y se utilizó el modo CI estándar de Flutter, que evita esa consulta. Las verificaciones listadas se completaron con ese modo; no se accedió a los metadatos.

Los comandos para repetir las pruebas y las dependencias necesarias están en `LEEME.md`. Las pruebas del servidor usan una base temporal y no llaman a Android. El primer SMS real debe iniciarse mediante la vista previa y confirmación de `/gateway`.
