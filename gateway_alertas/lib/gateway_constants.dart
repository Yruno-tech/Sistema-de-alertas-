const String testSmsMessage =
    'PRUEBA - Sistema de alertas institucional. No corresponde a una emergencia.';

const String methodChannelName = 'ar.gob.misiones.gateway_alertas/sms_methods';
const String eventChannelName = 'ar.gob.misiones.gateway_alertas/sms_events';

String normalizeArgentineMobile(String input) {
  final String trimmed = input.trim();
  if (!trimmed.startsWith('+')) {
    return trimmed.replaceAll(RegExp(r'[\s()\-]'), '');
  }

  final String digits = trimmed
      .substring(1)
      .replaceAll(RegExp(r'[\s()\-]'), '');
  return '+$digits';
}

bool isValidArgentineMobile(String input) {
  final String normalized = normalizeArgentineMobile(input);
  return RegExp(r'^\+549\d{10}$').hasMatch(normalized);
}

String maskPhone(String normalizedPhone) {
  if (normalizedPhone.length < 8) {
    return normalizedPhone;
  }
  return '${normalizedPhone.substring(0, 6)}••••${normalizedPhone.substring(normalizedPhone.length - 4)}';
}
