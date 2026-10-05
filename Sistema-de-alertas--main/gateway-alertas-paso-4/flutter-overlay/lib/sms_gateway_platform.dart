import 'package:flutter/services.dart';

class SmsGatewayPlatform {
  static const channel = MethodChannel(
    'ar.gob.misiones.gateway_alertas/gateway',
  );
  Future<T?> call<T>(String method, [Map<String, dynamic>? arguments]) =>
      channel.invokeMethod<T>(method, arguments);
  Future<Map<String, dynamic>> status() async =>
      Map<String, dynamic>.from((await call<Map<Object?, Object?>>('status'))!);
  Future<List<Map<String, dynamic>>> rows(
    String method, [
    String? serverId,
  ]) async {
    final values = await call<List<Object?>>(
      method,
      serverId == null ? null : {'serverId': serverId},
    );
    return (values ?? [])
        .map((row) => Map<String, dynamic>.from(row! as Map))
        .toList();
  }
}
