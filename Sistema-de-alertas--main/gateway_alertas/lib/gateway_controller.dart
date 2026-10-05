import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'gateway_connection.dart';
import 'sms_gateway_platform.dart';

class GatewayController extends ChangeNotifier {
  GatewayController({
    SmsGatewayPlatform? platform,
    GatewayTransport Function(GatewayConnection, String)? transportFactory,
  }) : platform = platform ?? SmsGatewayPlatform(),
       transportFactory = transportFactory ?? GatewayHttp.new;
  final SmsGatewayPlatform platform;
  final GatewayTransport Function(GatewayConnection, String) transportFactory;
  GatewayConnection? connection;
  GatewayTransport? _api;
  bool active = false, connected = false, remoteEnabled = false, busy = false;
  bool _foreground = true, _disposed = false;
  String message = 'Importá el archivo generado en la computadora.';
  Map<String, dynamic> permissions = {};
  List<Map<String, dynamic>> sims = [], recent = [];
  int? simId;
  Timer? _timer;
  bool get ready =>
      permissions['sendSmsGranted'] == true &&
      permissions['readPhoneStateGranted'] == true &&
      permissions['hasTelephonyMessaging'] == true &&
      simId != null;
  String get simLabel =>
      sims
          .where((s) => s['id'] == simId)
          .map((s) => s['label'] as String)
          .firstOrNull ??
      'SIM sin seleccionar';

  void changed() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize() async {
    busy = true;
    changed();
    try {
      await refreshHardware();
      final raw = await platform.call<String>('loadConnection');
      if (raw != null) await _connect(GatewayConnection.parse(raw));
    } catch (error) {
      message = describe(error);
    } finally {
      busy = false;
      changed();
      _schedule();
    }
  }

  Future<void> _connect(GatewayConnection config) async {
    final device = (await platform.call<String>('deviceId'))!;
    final api = transportFactory(
      config,
      device,
    ); // Validate the imported certificate before saving.
    await platform.call<void>('saveConnection', {'json': config.raw});
    connection = config;
    _api = api;
    connected = false;
    message = 'Emparejamiento cargado. Elegí la SIM y activá el gateway.';
  }

  Future<void> importConnection() async {
    if (busy || active) return;
    busy = true;
    changed();
    try {
      final raw = await platform.call<String>('importConnection');
      if (raw != null) await _connect(GatewayConnection.parse(raw));
    } catch (error) {
      message = describe(error);
    } finally {
      busy = false;
      changed();
      _schedule();
    }
  }

  Future<void> requestPermissions() async {
    if (busy || active) return;
    busy = true;
    changed();
    try {
      await platform.call<void>('requestPermissions');
      await refreshHardware();
    } catch (error) {
      message = describe(error);
    } finally {
      busy = false;
      changed();
      _schedule();
    }
  }

  Future<void> refreshHardware() async {
    permissions = await platform.status();
    sims =
        permissions['readPhoneStateGranted'] == true &&
            permissions['hasTelephonyMessaging'] == true
        ? await platform.rows('subscriptions')
        : [];
    if (!sims.any((s) => s['id'] == simId))
      simId = sims.length == 1 ? sims.single['id'] as int : null;
  }

  void selectSim(int? id) {
    if (!active && !busy) {
      simId = id;
      changed();
    }
  }

  Future<void> activate() async {
    if (busy || connection == null || !_foreground) return;
    busy = true;
    changed();
    try {
      await refreshHardware();
      if (!ready)
        throw StateError('Concedé los permisos y seleccioná una SIM activa');
      if (!connection!.expiresAt.isAfter(DateTime.now()))
        throw StateError('Emparejamiento vencido');
      active = true;
      await platform.call<void>('keepAwake', {'active': true});
      message =
          'Gateway activo. La confirmación del envío se realiza en la PC.';
    } catch (error) {
      active = false;
      message = describe(error);
    } finally {
      busy = false;
      changed();
      _schedule(Duration.zero);
    }
  }

  void pause({String? reason}) {
    active = false;
    if (reason != null) message = reason;
    unawaited(
      platform
          .call<void>('keepAwake', {'active': false})
          .catchError((Object _) {}),
    );
    changed();
    _schedule(Duration.zero);
  }

  void foreground(bool value) {
    _foreground = value;
    if (!value) {
      pause(
        reason:
            'Pausado al salir de la aplicación. Volvé a activar para continuar.',
      );
      _timer?.cancel();
    } else {
      _schedule(Duration.zero);
    }
  }

  void _schedule([Duration delay = const Duration(seconds: 3)]) {
    _timer?.cancel();
    if (!_disposed && _foreground && connection != null)
      _timer = Timer(delay, () => unawaited(tick()));
  }

  /// Repeats only API acknowledgements. Native code owns the durable one-attempt SMS rule.
  Future<void> tick() async {
    if (_disposed || !_foreground || connection == null || _api == null) return;
    if (busy) {
      _schedule();
      return;
    }
    busy = true;
    changed();
    final config = connection!, api = _api!;
    try {
      await _flushReports(api, config.serverId);
      final heartbeat = await api.post('/api/gateway/heartbeat', {
        'active': active,
        'sim_label': simLabel,
      });
      connected = true;
      remoteEnabled = heartbeat['enabled'] == true;
      if (heartbeat['mode'] != 'test' || heartbeat['max_recipients'] != 3)
        throw StateError('El servidor no está en modo de prueba compatible');
      if (active && _foreground && remoteEnabled) {
        final pending =
            await platform.call<List<Object?>>('prepared', {
              'serverId': config.serverId,
            }) ??
            [];
        Map<String, dynamic>? job;
        if (pending.isNotEmpty)
          job = Map<String, dynamic>.from(
            jsonDecode(pending.first! as String) as Map,
          );
        else {
          final response = await api.post('/api/gateway/jobs/next', {});
          if (response['job'] != null) {
            job = Map<String, dynamic>.from(response['job'] as Map);
            await platform.call<void>('prepare', {
              'serverId': config.serverId,
              'job': jsonEncode(job),
            });
          }
        }
        if (job != null && active && _foreground)
          await _start(api, config.serverId, job);
        await _flushReports(api, config.serverId);
      }
      recent = await platform.rows('recent', config.serverId);
      if (active)
        message = remoteEnabled
            ? 'Conectado. Esperando órdenes de la PC.'
            : 'Conectado. Los envíos están pausados desde la PC.';
    } catch (error) {
      connected = false;
      message = describe(error);
      if (error is PlatformException ||
          error is StateError ||
          error is FormatException ||
          (error is GatewayApiError && error.code != 409 && error.code < 500)) {
        pause(reason: message);
      }
    } finally {
      busy = false;
      changed();
      _schedule();
    }
  }

  Future<void> _start(
    GatewayTransport api,
    String server,
    Map<String, dynamic> job,
  ) async {
    final id = job['id'] as String;
    if ((job['expires_at'] as num) * 1000 <=
        DateTime.now().millisecondsSinceEpoch) {
      await platform.call<void>('abandon', {'serverId': server, 'id': id});
      return;
    }
    final response = await api.post('/api/gateway/jobs/$id/start', {
      'ticket': job['ticket'],
    });
    if (response['allowed'] == true && active && _foreground) {
      await platform.call<void>('sendPrepared', {
        'serverId': server,
        'id': id,
        'simId': simId,
      });
    } else if ([
      'CANCELLED',
      'UNKNOWN',
      'SENT',
      'DELIVERED',
      'FAILED',
    ].contains(response['status'])) {
      await platform.call<void>('abandon', {'serverId': server, 'id': id});
    }
  }

  Future<void> _flushReports(GatewayTransport api, String server) async {
    for (final report in await platform.rows('reports', server)) {
      final payload = Map<String, dynamic>.from(report)..remove('id');
      final response = await api.post(
        '/api/gateway/jobs/${report['id']}/report',
        payload,
      );
      if (response['ack'] != report['revision'])
        throw const FormatException('Confirmación de informe inválida');
      await platform.call<void>('ack', {
        'serverId': server,
        'id': report['id'],
        'revision': report['revision'],
      });
    }
  }

  static String describe(Object error) {
    if (error is PlatformException)
      return error.message ?? 'Android rechazó la operación';
    if (error is HandshakeException)
      return 'No se pudo verificar el certificado de la PC. Revisá el archivo importado y la fecha del teléfono.';
    if (error is SocketException || error is TimeoutException)
      return 'Sin conexión con la PC. Revisá Wi-Fi, servidor y firewall. Los SMS iniciados no se reenvían.';
    if (error is GatewayApiError) return error.message;
    if (error is FormatException) return error.message;
    if (error is StateError) return error.message;
    return 'No se pudo completar la operación. Revisá la configuración.';
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}
