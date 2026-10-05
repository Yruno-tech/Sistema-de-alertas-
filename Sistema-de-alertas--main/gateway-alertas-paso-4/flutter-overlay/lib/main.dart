import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'gateway_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const GatewayApp());
}

class GatewayApp extends StatelessWidget {
  const GatewayApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Gateway de alertas',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff12615b)),
      useMaterial3: true,
    ),
    home: const GatewayPage(),
  );
}

class GatewayPage extends StatefulWidget {
  const GatewayPage({super.key});
  @override
  State<GatewayPage> createState() => _GatewayPageState();
}

class _GatewayPageState extends State<GatewayPage> with WidgetsBindingObserver {
  final gateway = GatewayController();
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (Platform.isAndroid) unawaited(gateway.initialize());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) =>
      gateway.foreground(state == AppLifecycleState.resumed);
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    gateway.dispose();
    super.dispose();
  }

  Widget card(String title, List<Widget> children) => Card(
    margin: const EdgeInsets.only(bottom: 16),
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          ...children,
        ],
      ),
    ),
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Gateway de alertas')),
    body: !Platform.isAndroid
        ? const Center(
            child: Text(
              'Esta aplicación requiere un teléfono Android con SIM.',
            ),
          )
        : AnimatedBuilder(
            animation: gateway,
            builder: (context, _) => ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text(
                  'PRUEBA · HASTA 3 DESTINATARIOS',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),
                card(gateway.active ? 'Gateway activo' : 'Gateway pausado', [
                  Semantics(liveRegion: true, child: Text(gateway.message)),
                  const SizedBox(height: 12),
                  Text(
                    gateway.connected
                        ? 'Conexión con la PC disponible'
                        : 'Esperando conexión con la PC',
                  ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed: gateway.active
                        ? () => gateway.pause(
                            reason: 'Gateway pausado en el teléfono.',
                          )
                        : (!gateway.busy &&
                                  gateway.connection != null &&
                                  gateway.ready
                              ? gateway.activate
                              : null),
                    icon: Icon(gateway.active ? Icons.pause : Icons.play_arrow),
                    label: Text(
                      gateway.active ? 'Pausar gateway' : 'Activar gateway',
                    ),
                  ),
                  const Text(
                    'La PC elige edificio y oficina, muestra los destinatarios y confirma el envío. Mantené esta pantalla abierta.',
                  ),
                ]),
                card('1. Emparejar con la computadora', [
                  Text(
                    gateway.connection?.url.toString() ??
                        'Todavía no hay un servidor configurado.',
                  ),
                  if (gateway.connection != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      'Números autorizados: ${gateway.connection!.allowedNumbers.map((n) => '…${n.substring(n.length - 4)}').join(', ')}',
                    ),
                    Text(
                      'Vence: ${gateway.connection!.expiresAt.toLocal().toString().split('.').first}',
                    ),
                  ],
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: gateway.active || gateway.busy
                        ? null
                        : gateway.importConnection,
                    icon: const Icon(Icons.file_open_outlined),
                    label: const Text('Importar emparejar-gateway.json'),
                  ),
                ]),
                card('2. Permisos y SIM institucional', [
                  Text(
                    'SMS: ${gateway.permissions['sendSmsGranted'] == true ? 'permitido' : 'pendiente'} · '
                    'Teléfono: ${gateway.permissions['readPhoneStateGranted'] == true ? 'permitido' : 'pendiente'}',
                  ),
                  OutlinedButton(
                    onPressed: gateway.active || gateway.busy
                        ? null
                        : gateway.requestPermissions,
                    child: const Text('Solicitar permisos / actualizar SIM'),
                  ),
                  TextButton(
                    onPressed: gateway.active || gateway.busy
                        ? null
                        : () async {
                            await gateway.platform.call<void>('openSettings');
                          },
                    child: const Text('Abrir permisos en ajustes de Android'),
                  ),
                  if (gateway.sims.isNotEmpty)
                    DropdownButtonFormField<int>(
                      initialValue: gateway.simId,
                      key: ValueKey(gateway.simId),
                      decoration: const InputDecoration(
                        labelText: 'SIM que enviará los SMS',
                      ),
                      items: gateway.sims
                          .map(
                            (s) => DropdownMenuItem<int>(
                              value: s['id'] as int,
                              child: Text(
                                s['label'] as String,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          )
                          .toList(),
                      onChanged: gateway.active || gateway.busy
                          ? null
                          : gateway.selectSim,
                    )
                  else
                    const Text(
                      'No hay una SIM disponible. Revisá los permisos y la línea.',
                    ),
                ]),
                card('Últimos resultados del teléfono', [
                  if (gateway.recent.isEmpty)
                    const Text('Todavía no hay intentos de envío registrados.'),
                  for (final result in gateway.recent)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${result['phone']} · ${stateLabel(result['state'] as String)}',
                            style: const TextStyle(fontWeight: FontWeight.bold),
                          ),
                          Text(result['detail'] as String),
                        ],
                      ),
                    ),
                ]),
                const Text(
                  'Cada mensaje usa la SIM y puede consumir saldo. Entregado depende del informe de la operadora y no confirma lectura.',
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
  );
}

String stateLabel(String state) =>
    const {
      'PREPARED': 'Preparado',
      'SUBMITTED': 'Enviando',
      'SENT': 'Enviado',
      'FAILED': 'Fallido',
      'UNKNOWN': 'Resultado desconocido',
      'CANCELLED': 'Cancelado',
    }[state] ??
    state;
