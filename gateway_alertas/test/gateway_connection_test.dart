import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_alertas/gateway_connection.dart';

Map<String, dynamic> pairing() => {
  'version': 1,
  'mode': 'test',
  'url': 'https://192.168.1.5:8443',
  'serverId': '11111111-1111-4111-8111-111111111111',
  'token': List.filled(43, 'a').join(),
  'certificatePem':
      '-----BEGIN CERTIFICATE-----\nTEST_ONLY\n-----END CERTIFICATE-----\n',
  'allowedNumbers': ['+5493764000001'],
  'expiresAt':
      DateTime.now().add(const Duration(days: 1)).millisecondsSinceEpoch / 1000,
};

void main() {
  test('Accepts private HTTPS pilot configuration', () {
    final config = GatewayConnection.parse(jsonEncode(pairing()));
    expect(config.url.host, '192.168.1.5');
    expect(config.allowedNumbers, ['+5493764000001']);
  });
  test(
    'Rejects HTTP, public destinations, embedded credentials and redirects in URL',
    () {
      for (final url in [
        'http://192.168.1.5:8443',
        'https://8.8.8.8:8443',
        'https://user@192.168.1.5:8443',
        'https://192.168.1.5:8443/redirect',
        'https://192.168.1.5:8443?url=x',
      ]) {
        expect(
          () => GatewayConnection.parse(jsonEncode(pairing()..['url'] = url)),
          throwsFormatException,
        );
      }
    },
  );
  test(
    'Rejects duplicates, more than three recipients, expired and production files',
    () {
      for (final changed in [
        pairing()..['allowedNumbers'] = ['+5493764000001', '+5493764000001'],
        pairing()
          ..['allowedNumbers'] = List.generate(
            4,
            (i) => '+549376400000${i + 1}',
          ),
        pairing()..['expiresAt'] = 0,
        pairing()..['mode'] = 'production',
      ]) {
        expect(
          () => GatewayConnection.parse(jsonEncode(changed)),
          throwsFormatException,
        );
      }
    },
  );
}
