# Verificación · actualización QR

Servidor 0.5.0 · Flutter 0.3.0 · Android protocol 2.

| Comprobación | Resultado |
|---|---|
| Python / pytest | 47 pruebas aprobadas |
| Flutter analyze | Sin problemas |
| Flutter test | 15 pruebas aprobadas |
| APK debug | Compilación aprobada con Flutter 3.47.2 y Dart 3.13.2 |
| Mensaje de situación controlada | Motivo obligatorio; longitud limitada según edificio para mantener el mensaje completo en 160 caracteres |
| Flujo del gateway | QR, destinatarios flexibles, confirmación idempotente, pausa y cancelación cubiertos por pruebas automatizadas |

Las pruebas del servidor usan una base temporal y no envían SMS ni consultan una planilla privada. Las pruebas Flutter verifican el flujo de la app sin un módem real. La validación automatizada no sustituye los procedimientos institucionales ni la comprobación del equipo y la operadora.

Las verificaciones no activan envíos. Los SMS del gateway son reales y llevan el prefijo PRUEBA; usá únicamente destinatarios autorizados para cualquier operación manual.
