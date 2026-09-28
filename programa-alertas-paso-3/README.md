# Documentación de las pantallas de simulación del Paso 3

> Actualización instalada: Paso 4, versión 0.4.0. El nuevo panel `/gateway` sí puede enviar SMS reales de prueba mediante el teléfono. Para instalarlo y utilizarlo, seguí `LEEME.md` en el paquete PC + Flutter. El texto siguiente documenta exclusivamente las pantallas antiguas de sincronización y simulación, que siguen disponibles.

En esta etapa el sistema:

- lee destinatarios de Google Sheets en modo **solo lectura**;
- valida nombres, teléfonos, edificios y opciones SI/NO;
- guarda una copia local en SQLite;
- muestra qué filas fueron aceptadas o rechazadas;
- permite registrar una simulación por destinatario;
- **no envía SMS ni correos electrónicos**.

## 1. Reemplazar los archivos del Paso 2

Descomprima este paquete y copie su contenido dentro de la carpeta `ProgramaAlertas`.
Puede reemplazar `main.py`, `message_builder.py`, `templates` y `static`.

La estructura principal quedará así:

```text
ProgramaAlertas/
├── .venv/
├── main.py
├── config.py
├── database.py
├── message_builder.py
├── recipient_validation.py
├── sheets_service.py
├── requirements.txt
├── .env.example
├── credentials/
├── data/
├── static/
├── templates/
└── tests/
```

## 2. Instalar dependencias

Con el entorno virtual activo:

```bat
pip install -r requirements.txt
```

## 3. Revisar la planilla

La primera fila debe incluir, preferentemente, estos encabezados:

```text
id | nombre | telefono | correo | edificio | activo | sms | correo_habilitado
```

Reglas:

- `id`: recomendado y único.
- `nombre`: obligatorio.
- `telefono`: obligatorio y en formato móvil argentino internacional.
- `correo`: puede quedar vacío.
- `edificio`: uno de los tres edificios admitidos.
- `activo`, `sms` y `correo_habilitado`: usar `SI` o `NO`.

Ejemplo de teléfono:

```text
+5493764XXXXXX
```

No use `0` antes del código de área ni `15`. Configure la columna como **Texto sin formato** para conservar el signo `+`.

Edificios aceptados:

```text
Tribunal Electoral de la Provincia de Misiones
Edificio Histórico
Edificio Anexo
```

También se aceptan las formas abreviadas `Tribunal Electoral`, `Histórico` y `Anexo`.

## 4. Crear acceso de solo lectura en Google Cloud

1. Cree o seleccione un proyecto en Google Cloud.
2. Habilite **Google Sheets API**.
3. Abra `IAM y administración > Cuentas de servicio`.
4. Cree una cuenta de servicio, por ejemplo `programa-alertas`.
5. Entre en la cuenta, abra `Claves` y cree una clave nueva de tipo JSON.
6. Cambie el nombre del archivo descargado a:

```text
service-account.json
```

7. Guárdelo dentro de:

```text
ProgramaAlertas/credentials/service-account.json
```

8. Abra el JSON solamente para localizar el valor `client_email`.
9. Comparta su Google Sheets con ese correo como **Lector**.

No comparta el archivo JSON con otras personas ni lo suba a GitHub.

## 5. Crear el archivo `.env`

En CMD:

```bat
copy .env.example .env
```

Abra `.env` y complete:

```text
GOOGLE_SHEETS_ID=ID_O_URL_DE_SU_PLANILLA
GOOGLE_SHEETS_RANGE=DESTINATARIOS!A1:H
```

Puede pegar la URL completa. Si la pestaña no se llama `DESTINATARIOS`, cambie solamente ese nombre.

Mantenga obligatoriamente:

```text
APP_MODE=test
SMS_ENABLED=false
TEST_RECIPIENT_LIMIT=3
```

## 6. Ejecutar

```bat
fastapi dev main.py
```

Abra:

```text
http://127.0.0.1:8000/recipients
```

Presione **Sincronizar ahora**.

Para sus tres filas, el resultado esperado es:

```text
Filas leídas: 3
Aceptadas: 3
Rechazadas: 0
SMS activos: 3
```

La cantidad por edificio dependerá de la asociación realizada en la planilla.

## 7. Registrar la primera simulación

1. Abra `http://127.0.0.1:8000/`.
2. Seleccione un edificio que tenga al menos un destinatario.
3. Seleccione una alerta.
4. Genere la vista previa.
5. Revise la lista enmascarada.
6. Marque la casilla de confirmación.
7. Presione **Registrar simulación**.

El sistema creará:

- una alerta con estado `SIMULATED`;
- una entrega SMS simulada por destinatario;
- un registro visible en `/history`.

No se contactará al teléfono.

## 8. Archivos sensibles y datos locales

No comparta:

```text
.env
credentials/service-account.json
data/alerts.db
```

El archivo `.gitignore` ya excluye esos elementos.

## Problemas frecuentes

### Error 403

La planilla no fue compartida con el `client_email` de la cuenta de servicio, o Google Sheets API no está habilitada.

### Error 404

Revise el ID de la planilla y el nombre de la pestaña en `GOOGLE_SHEETS_RANGE`.

### Falta una columna

La fila 1 debe contener como mínimo:

```text
nombre | telefono | edificio | activo | sms
```

### Teléfono rechazado

Use un celular argentino en formato:

```text
+549XXXXXXXXXX
```

El sistema no intenta convertir números domésticos con `0` o `15`, porque podría asociarlos incorrectamente.

### La planilla tiene más de tres destinatarios para un edificio

La sincronización funciona, pero la simulación de ese edificio se bloquea. Durante esta etapa, el máximo por alerta es tres.
