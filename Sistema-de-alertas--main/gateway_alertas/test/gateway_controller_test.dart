import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_alertas/gateway_connection.dart';
import 'package:gateway_alertas/gateway_controller.dart';
import 'package:gateway_alertas/sms_gateway_platform.dart';
import 'gateway_connection_test.dart' show pairing;

class FakePhone extends SmsGatewayPlatform {
  final Map<String, Map<String, dynamic>> jobs = {};
  final List<Map<String, dynamic>> outbox = [];
  int physicalSends = 0;
  @override
  Future<T?> call<T>(String method, [Map<String, dynamic>? arguments]) async {
    Object? value;
    switch (method) {
      case 'status':
        value = {
          'sendSmsGranted': true,
          'readPhoneStateGranted': true,
          'hasTelephonyMessaging': true,
        };
      case 'subscriptions':
        value = [
          {'id': 1, 'label': 'SIM TEST'},
        ];
      case 'loadConnection':
        value = jsonEncode(pairing());
      case 'deviceId':
        value = '22222222-2222-4222-8222-222222222222';
      case 'prepared':
        value = jobs.values
            .where((j) => j['state'] == 'PREPARED')
            .map((j) => jsonEncode(j['payload']))
            .toList();
      case 'prepare':
        final job =
            jsonDecode(arguments!['job'] as String) as Map<String, dynamic>;
        jobs.putIfAbsent(
          job['id'] as String,
          () => {'payload': job, 'state': 'PREPARED'},
        );
      case 'sendPrepared':
        final entry = jobs[arguments!['id']]!;
        if (entry['state'] == 'PREPARED') {
          entry['state'] = 'SENT';
          physicalSends++;
          final payload = entry['payload'] as Map<String, dynamic>;
          outbox.add({
            'id': payload['id'],
            'ticket': payload['ticket'],
            'state': 'SENT',
            'delivery': 'WAITING',
            'detail': 'Simulated modem',
            'revision': 2,
          });
        }
      case 'reports':
        value = outbox.map((r) => Map<String, dynamic>.from(r)).toList();
      case 'ack':
        outbox.removeWhere((r) => r['id'] == arguments!['id']);
      case 'recent':
        value = <Map<String, dynamic>>[];
      case 'abandon':
        jobs[arguments!['id']]!['state'] = 'CANCELLED';
    }
    return value as T?;
  }
}

class FakeServer extends GatewayTransport {
  bool loseStartResponse = false,
      loseReportResponse = false,
      cancelled = false,
      reserved = false,
      reported = false;
  int reportRequests = 0;
  @override
  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path.endsWith('/heartbeat'))
      return {'enabled': true, 'mode': 'test', 'max_recipients': 3};
    if (path.endsWith('/next')) {
      if (reported) return {'job': null};
      reserved = true;
      return {
        'job': {
          'id': '33333333-3333-4333-8333-333333333333',
          'ticket': '44444444-4444-4444-8444-444444444444',
          'batch_id': '55555555-5555-4555-8555-555555555555',
          'mode': 'test',
          'phone': '+5493764000001',
          'message': 'PRUEBA - Simulada',
          'expires_at':
              DateTime.now()
                  .add(const Duration(minutes: 10))
                  .millisecondsSinceEpoch /
              1000,
        },
      };
    }
    if (path.endsWith('/start')) {
      if (loseStartResponse) {
        loseStartResponse = false;
        throw TimeoutException('Simulated response loss');
      }
      return {
        'allowed': !cancelled,
        'status': cancelled ? 'CANCELLED' : 'STARTED',
      };
    }
    if (path.endsWith('/report')) {
      reported = true;
      reportRequests++;
      if (loseReportResponse) {
        loseReportResponse = false;
        throw TimeoutException('Simulated response loss');
      }
      return {'ack': body['revision']};
    }
    throw StateError('Unexpected route');
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'Lost report response repeats the report without a second SMS',
    () async {
      final phone = FakePhone(),
          server = FakeServer()..loseReportResponse = true;
      final controller = GatewayController(
        platform: phone,
        transportFactory: (_, _) => server,
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      await controller.activate();
      await controller.tick();
      await controller.tick();
      expect(phone.physicalSends, 1);
      expect(server.reportRequests, 2);
      expect(phone.outbox, isEmpty);
    },
  );
  test(
    'Lost start response recovers prepared job after controller restart',
    () async {
      final phone = FakePhone(),
          server = FakeServer()..loseStartResponse = true;
      final first = GatewayController(
        platform: phone,
        transportFactory: (_, _) => server,
      );
      await first.initialize();
      await first.activate();
      await first.tick();
      expect(phone.physicalSends, 0);
      first.dispose();
      final recovered = GatewayController(
        platform: phone,
        transportFactory: (_, _) => server,
      );
      addTearDown(recovered.dispose);
      await recovered.initialize();
      await recovered.activate();
      await recovered.tick();
      expect(phone.physicalSends, 1);
    },
  );
  test('Cancellation before start prevents any SMS', () async {
    final phone = FakePhone(), server = FakeServer()..cancelled = true;
    final controller = GatewayController(
      platform: phone,
      transportFactory: (_, _) => server,
    );
    addTearDown(controller.dispose);
    await controller.initialize();
    await controller.activate();
    await controller.tick();
    expect(phone.physicalSends, 0);
    expect(phone.jobs.values.single['state'], 'CANCELLED');
  });
  test('Backgrounding pauses sending even when PC enables the queue', () async {
    final phone = FakePhone(), server = FakeServer();
    final controller = GatewayController(
      platform: phone,
      transportFactory: (_, _) => server,
    );
    addTearDown(controller.dispose);
    await controller.initialize();
    await controller.activate();
    controller.foreground(false);
    await controller.tick();
    expect(controller.active, isFalse);
    expect(phone.physicalSends, 0);
    expect(server.reserved, isFalse);
  });
}
