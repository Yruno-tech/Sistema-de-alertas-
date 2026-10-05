import 'package:flutter_test/flutter_test.dart';
import 'package:gateway_alertas/main.dart';

void main() {
  testWidgets('Explains the Android SIM requirement on other platforms', (
    tester,
  ) async {
    await tester.pumpWidget(const GatewayApp());
    expect(
      find.text('Esta aplicación requiere un teléfono Android con SIM.'),
      findsOneWidget,
    );
  });
}
