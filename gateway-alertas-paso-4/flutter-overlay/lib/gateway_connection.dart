import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';

class GatewayConnection {
  GatewayConnection._(
    this.raw,
    this.url,
    this.serverId,
    this.token,
    this.certificatePem,
    this.recipientPolicy,
    this.expiresAt,
  );
  final String raw, serverId, token, certificatePem;
  final Uri url;
  final String recipientPolicy;
  final DateTime expiresAt;

  factory GatewayConnection.parse(String raw) {
    if (raw.length > 16384)
      throw const FormatException('Archivo demasiado grande');
    final data = Map<String, dynamic>.from(jsonDecode(raw) as Map);
    final uri = _privateGatewayUrl(data['url']);
    if (data['version'] != 2 ||
        data['mode'] != 'test' ||
        data['recipientPolicy'] != 'database') {
      throw const FormatException(
        'Se requiere una credencial de emparejamiento v2 válida',
      );
    }
    final token = data['token'] as String;
    final server = data['serverId'] as String;
    final pem = data['certificatePem'] as String;
    final expires = DateTime.fromMillisecondsSinceEpoch(
      ((data['expiresAt'] as num) * 1000).toInt(),
    );
    if (!RegExp(r'^[A-Za-z0-9_-]{40,100}$').hasMatch(token) ||
        !RegExp(r'^[a-f0-9-]{36}$').hasMatch(server) ||
        !pem.startsWith('-----BEGIN CERTIFICATE-----') ||
        !pem.contains('-----END CERTIFICATE-----')) {
      throw const FormatException(
        'La credencial de emparejamiento está incompleta o es inválida',
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
      data['recipientPolicy'] as String,
      expires,
    );
  }

  factory GatewayConnection.fromPairingResponse(
    String raw,
    GatewayPairingRequest pairing,
  ) {
    final connection = GatewayConnection.parse(raw);
    if (connection.url != pairing.url ||
        !_sameFingerprint(
          _certificatePemFingerprint(connection.certificatePem),
          pairing.certificateSha256,
        )) {
      throw const FormatException(
        'La credencial no coincide con el servidor del código QR',
      );
    }
    return connection;
  }
}

class GatewayPairingRequest {
  GatewayPairingRequest._(
    this.url,
    this.id,
    this.secret,
    this.certificateSha256,
    this.expiresAt,
  );

  final Uri url;
  final String id, secret, certificateSha256;
  final DateTime expiresAt;

  factory GatewayPairingRequest.parse(String raw) {
    if (raw.length > 4096) {
      throw const FormatException('El código QR es demasiado grande');
    }
    final data = Map<String, dynamic>.from(jsonDecode(raw) as Map);
    final url = _privateGatewayUrl(data['url']);
    final id = data['id'] as String;
    final secret = data['secret'] as String;
    final fingerprint = data['certificateSha256'] as String;
    final expires = DateTime.fromMillisecondsSinceEpoch(
      ((data['expiresAt'] as num) * 1000).toInt(),
    );
    if (data['version'] != 2 ||
        data['purpose'] != 'gateway-pair' ||
        !RegExp(r'^[a-f0-9-]{36}$').hasMatch(id) ||
        !RegExp(r'^[A-Za-z0-9_-]{40,100}$').hasMatch(secret) ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(fingerprint) ||
        !expires.isAfter(DateTime.now())) {
      throw const FormatException(
        'El código QR está incompleto, vencido o no es compatible',
      );
    }
    return GatewayPairingRequest._(url, id, secret, fingerprint, expires);
  }

  Future<GatewayConnection> redeem(String deviceId) async {
    if (!expiresAt.isAfter(DateTime.now())) {
      throw const FormatException('El código QR venció; generá otro en la PC');
    }
    if (!RegExp(r'^[a-f0-9-]{36}$').hasMatch(deviceId)) {
      throw const FormatException('Identificador de dispositivo inválido');
    }
    final client = HttpClient(
      context: SecurityContext(withTrustedRoots: false),
    );
    client.connectionTimeout = const Duration(seconds: 8);
    client.findProxy = (_) => 'DIRECT';
    client.badCertificateCallback =
        (X509Certificate certificate, String host, int port) {
          if (host != url.host || port != url.port) return false;
          return _sameFingerprint(
            sha256.convert(certificate.der).toString(),
            certificateSha256,
          );
        };
    try {
      final request = await client
          .postUrl(url.resolve('/api/gateway/pair'))
          .timeout(const Duration(seconds: 12));
      request.followRedirects = false;
      request.headers.contentType = ContentType.json;
      request.headers.set('X-Gateway-Device', deviceId);
      request.write(jsonEncode({'id': id, 'secret': secret}));
      final response = await request.close().timeout(
        const Duration(seconds: 12),
      );
      final bytes = <int>[];
      await for (final chunk in response.timeout(const Duration(seconds: 12))) {
        if (bytes.length + chunk.length > 16384) {
          throw const FormatException('Respuesta demasiado grande');
        }
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
              : 'La PC rechazó el emparejamiento',
        );
      }
      return GatewayConnection.fromPairingResponse(jsonEncode(data), this);
    } finally {
      client.close(force: true);
    }
  }
}

class GatewayApiError implements Exception {
  GatewayApiError(this.code, this.message);
  final int code;
  final String message;
  @override
  String toString() => message;
}

Uri _privateGatewayUrl(dynamic value) {
  if (value is! String) {
    throw const FormatException('La dirección del gateway no es válida');
  }
  final uri = Uri.parse(value);
  final parts = uri.host.split('.').map(int.tryParse).toList();
  final privateIp =
      parts.length == 4 &&
      parts.every((n) => n != null && n >= 0 && n <= 255) &&
      (parts[0] == 10 ||
          (parts[0] == 192 && parts[1] == 168) ||
          (parts[0] == 172 && parts[1]! >= 16 && parts[1]! <= 31));
  if (uri.scheme != 'https' ||
      !privateIp ||
      uri.port != 8443 ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path.isNotEmpty && uri.path != '/')) {
    throw const FormatException(
      'Se requiere una dirección privada de la PC con HTTPS:8443',
    );
  }
  return uri;
}

String _certificatePemFingerprint(String pem) {
  const begin = '-----BEGIN CERTIFICATE-----';
  const end = '-----END CERTIFICATE-----';
  if (!pem.startsWith(begin) || !pem.trimRight().endsWith(end)) {
    throw const FormatException('El certificado de la PC no es válido');
  }
  final encoded = pem
      .substring(begin.length, pem.lastIndexOf(end))
      .replaceAll(RegExp(r'\s'), '');
  if (encoded.isEmpty) {
    throw const FormatException('El certificado de la PC no es válido');
  }
  try {
    return sha256.convert(base64.decode(encoded)).toString();
  } on FormatException {
    throw const FormatException('El certificado de la PC no es válido');
  }
}

bool _sameFingerprint(String actual, String expected) {
  if (actual.length != expected.length) return false;
  var difference = 0;
  for (var index = 0; index < actual.length; index++) {
    difference |= actual.codeUnitAt(index) ^ expected.codeUnitAt(index);
  }
  return difference == 0;
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
