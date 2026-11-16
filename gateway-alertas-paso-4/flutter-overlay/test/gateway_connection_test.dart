import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_alertas/gateway_connection.dart';

const certificatePem =
    '-----BEGIN CERTIFICATE-----\nAQIDBA==\n-----END CERTIFICATE-----\n';

Map<String, dynamic> pairing() => {
  'version': 2,
  'mode': 'test',
  'url': 'https://192.168.1.5:8443',
  'serverId': '11111111-1111-4111-8111-111111111111',
  'token': List.filled(43, 'a').join(),
  'certificatePem': certificatePem,
  'recipientPolicy': 'database',
  'expiresAt':
      DateTime.now().add(const Duration(days: 1)).millisecondsSinceEpoch / 1000,
};

Map<String, dynamic> pairingQr() => {
  'version': 2,
  'purpose': 'gateway-pair',
  'url': 'https://192.168.1.5:8443',
  'id': '22222222-2222-4222-8222-222222222222',
  'secret': List.filled(43, 'b').join(),
  'certificateSha256': sha256.convert([1, 2, 3, 4]).toString(),
  'expiresAt':
      DateTime.now().add(const Duration(minutes: 5)).millisecondsSinceEpoch /
      1000,
};

void main() {
  test('Accepts a v2 credential using the database recipient policy', () {
    final config = GatewayConnection.parse(jsonEncode(pairing()));
    expect(config.url.host, '192.168.1.5');
    expect(config.recipientPolicy, 'database');
  });
  test(
    'Rejects invalid destinations, old credentials, and unknown policies',
    () {
      for (final changed in [
        pairing()..['url'] = 'http://192.168.1.5:8443',
        pairing()..['url'] = 'https://8.8.8.8:8443',
        pairing()..['url'] = 'https://user@192.168.1.5:8443',
        pairing()..['url'] = 'https://192.168.1.5:8443/redirect',
        pairing()..['url'] = 'https://192.168.1.5:8443?url=x',
        pairing()..['version'] = 1,
        pairing()..['recipientPolicy'] = 'static',
      ]) {
        expect(
          () => GatewayConnection.parse(jsonEncode(changed)),
          throwsFormatException,
        );
      }
    },
  );

  test('Parses a short-lived v2 QR pairing request', () {
    final request = GatewayPairingRequest.parse(jsonEncode(pairingQr()));
    expect(request.id, pairingQr()['id']);
    expect(request.certificateSha256, pairingQr()['certificateSha256']);
  });

  test('Rejects an invalid or expired QR pairing request', () {
    for (final changed in [
      pairingQr()..['purpose'] = 'credential',
      pairingQr()..['url'] = 'https://8.8.8.8:8443',
      pairingQr()..['certificateSha256'] = 'invalid',
      pairingQr()..['expiresAt'] = 0,
    ]) {
      expect(
        () => GatewayPairingRequest.parse(jsonEncode(changed)),
        throwsFormatException,
      );
    }
  });

  test('Binds the redeemed credential to the QR certificate fingerprint', () {
    final request = GatewayPairingRequest.parse(jsonEncode(pairingQr()));
    final connection = GatewayConnection.fromPairingResponse(
      jsonEncode(pairing()),
      request,
    );
    expect(connection.recipientPolicy, 'database');

    final changed = pairing()
      ..['certificatePem'] =
          '-----BEGIN CERTIFICATE-----\nAQIDBQ==\n-----END CERTIFICATE-----\n';
    expect(
      () => GatewayConnection.fromPairingResponse(
        jsonEncode(changed),
        request,
      ),
      throwsFormatException,
    );
  });
}
