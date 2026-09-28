import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_alertas/gateway_constants.dart';

void main() {
  group('número celular argentino', () {
    test('acepta el formato internacional esperado', () {
      expect(isValidArgentineMobile('+5493764123456'), isTrue);
    });

    test('normaliza espacios, guiones y paréntesis', () {
      expect(
        normalizeArgentineMobile('+54 9 (3764) 12-3456'),
        '+5493764123456',
      );
      expect(isValidArgentineMobile('+54 9 (3764) 12-3456'), isTrue);
    });

    test('rechaza un número sin signo más', () {
      expect(isValidArgentineMobile('5493764123456'), isFalse);
    });

    test('rechaza un teléfono fijo sin el 9 móvil', () {
      expect(isValidArgentineMobile('+543764123456'), isFalse);
    });
  });

  test('el texto de prueba es inequívoco y cabe en un SMS GSM simple', () {
    expect(testSmsMessage, startsWith('PRUEBA -'));
    expect(testSmsMessage, contains('No corresponde a una emergencia.'));
    expect(testSmsMessage.length, lessThanOrEqualTo(160));
    expect(RegExp(r'^[\x20-\x7E]+$').hasMatch(testSmsMessage), isTrue);
  });
}
