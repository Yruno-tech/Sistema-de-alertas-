import 'dart:async';
import 'dart:convert';
import 'dart:io';

class GatewayConnection {
  GatewayConnection._(
    this.raw,
    this.url,
    this.serverId,
    this.token,
    this.certificatePem,
    this.allowedNumbers,
    this.expiresAt,
  );
  final String raw, serverId, token, certificatePem;
  final Uri url;
  final List<String> allowedNumbers;
  final DateTime expiresAt;

  factory GatewayConnection.parse(String raw) {
    if (raw.length > 16384)
      throw const FormatException('Archivo demasiado grande');
    final data = Map<String, dynamic>.from(jsonDecode(raw) as Map);
    final uri = Uri.parse(data['url'] as String);
    final parts = uri.host.split('.').map(int.tryParse).toList();
    final privateIp =
        parts.length == 4 &&
        parts.every((n) => n != null && n >= 0 && n <= 255) &&
        (parts[0] == 10 ||
            (parts[0] == 192 && parts[1] == 168) ||
            (parts[0] == 172 && parts[1]! >= 16 && parts[1]! <= 31));
    if (data['version'] != 1 ||
        data['mode'] != 'test' ||
        uri.scheme != 'https' ||
        !privateIp ||
        uri.port != 8443 ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw const FormatException(
        'Se requiere un emparejamiento de prueba con la IP privada de la PC y HTTPS:8443',
      );
    }
    final numbers = List<String>.from(data['allowedNumbers'] as List);
    final token = data['token'] as String;
    final server = data['serverId'] as String;
    final pem = data['certificatePem'] as String;
    final expires = DateTime.fromMillisecondsSinceEpoch(
      ((data['expiresAt'] as num) * 1000).toInt(),
    );
    if (numbers.isEmpty ||
        numbers.length > 3 ||
        numbers.toSet().length != numbers.length ||
        numbers.any((n) => !RegExp(r'^\+549[0-9]{10}$').hasMatch(n)) ||
        !RegExp(r'^[A-Za-z0-9_-]{40,100}$').hasMatch(token) ||
        !RegExp(r'^[a-f0-9-]{36}$').hasMatch(server) ||
        !pem.startsWith('-----BEGIN CERTIFICATE-----') ||
        !pem.contains('-----END CERTIFICATE-----')) {
      throw const FormatException(
        'El archivo de emparejamiento está incompleto o es inválido',
      );
    }
    if (!expires.isAfter(DateTime.now()))
      throw const FormatException(
        'El emparejamiento venció; renovalo en la PC',
      );
    return GatewayConnection._(
      raw,
      uri,
      server,
      token,
      pem,
      List.unmodifiable(numbers),
      expires,
    );
  }
}

class GatewayApiError implements Exception {
  GatewayApiError(this.code, this.message);
  final int code;
  final String message;
  @override
  String toString() => message;
}

abstract class GatewayTransport {
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body);
}

class GatewayHttp implements GatewayTransport {
  GatewayHttp(this.connection, this.deviceId) {
    context.setTrustedCertificatesBytes(utf8.encode(connection.certificatePem));
  }
  final GatewayConnection connection;
  final String deviceId;
  final SecurityContext context = SecurityContext(withTrustedRoots: false);

  @override
  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (!connection.expiresAt.isAfter(DateTime.now()))
      throw GatewayApiError(401, 'Emparejamiento vencido');
    if (!path.startsWith('/api/gateway/') || path.contains('..'))
      throw ArgumentError('Ruta inválida');
    final client = HttpClient(context: context)
      ..connectionTimeout = const Duration(seconds: 8)
      ..findProxy = (_) => 'DIRECT';
    try {
      return await _request(
        client,
        path,
        body,
      ).timeout(const Duration(seconds: 12));
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> _request(
    HttpClient client,
    String path,
    Map<String, dynamic> body,
  ) async {
    final request = await client.postUrl(connection.url.resolve(path));
    request.followRedirects = false;
    request.headers.contentType = ContentType.json;
    request.headers.set(
      HttpHeaders.authorizationHeader,
      'Bearer ${connection.token}',
    );
    request.headers.set('X-Gateway-Device', deviceId);
    request.write(jsonEncode(body));
    final response = await request.close();
    final bytes = <int>[];
    await for (final chunk in response) {
      if (bytes.length + chunk.length > 65536)
        throw const FormatException('Respuesta demasiado grande');
      bytes.addAll(chunk);
    }
    final data = Map<String, dynamic>.from(
      jsonDecode(utf8.decode(bytes)) as Map,
    );
    if (response.statusCode != 200) {
      throw GatewayApiError(
        response.statusCode,
        data['detail'] is String
            ? data['detail'] as String
            : 'El servidor rechazó la solicitud',
      );
    }
    return data;
  }
}
