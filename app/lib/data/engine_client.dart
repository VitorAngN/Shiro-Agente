import 'dart:convert';
import 'dart:io';

import '../core/models/records.dart';
import 'shiro_paths.dart';

/// Falha devolvida pelo motor, já com a explicação dele.
class EngineError implements Exception {
  const EngineError(this.message, {this.status});

  final String message;
  final int? status;

  @override
  String toString() => message;
}

/// O que o programa pede ao motor. A tela depende desta interface, não do HTTP:
/// nos testes entra um motor de mentira.
abstract interface class EngineApi {
  Future<void> me();
  Future<Map<String, dynamic>> chat(String text);
  Future<Map<String, dynamic>?> voice();
  Future<List<PendingConfirmation>> confirmations();
  Future<void> answer(String id, {required bool approve});
  Future<List<Lesson>> lessons();
  Future<List<LinkedDevice>> devices();
  Future<void> revoke(String deviceId);
  Future<Pairing> pairing();
  Future<({bool listening, String problem, List<VoiceEntry> items, Activity activity})> voiceHistory(int after);
  Future<({bool listening, String problem})> setListening(bool on);
}

/// Cliente da API dos aparelhos (ADR-0022), com a chave do aparelho "Este PC".
class HttpEngineClient implements EngineApi {
  HttpEngineClient(this.base, this._token)
      : _http = HttpClient()..connectionTimeout = const Duration(seconds: 3);

  final Uri base;
  final String _token;
  final HttpClient _http;

  /// O cliente do motor deste PC, se ele já gravou a chave do programa.
  static Future<EngineApi?> local(ShiroPaths paths) async {
    final file = paths.localToken;
    if (!await file.exists()) return null;
    final token = (await file.readAsString()).trim();
    if (token.isEmpty) return null;
    return HttpEngineClient(Uri.parse('http://127.0.0.1:8766'), token);
  }

  Future<dynamic> _send(String method, String path, [Object? body]) async {
    final request = await _http.openUrl(method, base.resolve(path));
    request.headers.set('Authorization', 'Bearer $_token');
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.add(utf8.encode(jsonEncode(body)));
    }
    final response = await request.close();
    final text = await utf8.decodeStream(response);
    if (response.statusCode >= 400) {
      var detail = text;
      try {
        detail = (jsonDecode(text) as Map<String, dynamic>)['detail'].toString();
      } catch (_) {}
      throw EngineError(detail, status: response.statusCode);
    }
    return text.isEmpty ? null : jsonDecode(text);
  }

  Future<Map<String, dynamic>> _object(String method, String path, [Object? body]) async =>
      (await _send(method, path, body)) as Map<String, dynamic>;

  Future<List<Map<String, dynamic>>> _list(String path) async =>
      [for (final item in (await _send('GET', path)) as List<dynamic>) item as Map<String, dynamic>];

  @override
  Future<void> me() => _send('GET', '/v1/me');

  @override
  Future<Map<String, dynamic>> chat(String text) => _object('POST', '/v1/chat', {'text': text});

  @override
  Future<Map<String, dynamic>?> voice() async {
    final result = await _object('POST', '/v1/voice');
    return result['heard'] == null ? null : result;
  }

  @override
  Future<List<PendingConfirmation>> confirmations() async =>
      [for (final item in await _list('/v1/confirmations')) PendingConfirmation.fromJson(item)];

  @override
  Future<void> answer(String id, {required bool approve}) =>
      _send('POST', '/v1/confirmations/$id', {'approve': approve});

  @override
  Future<List<Lesson>> lessons() async => [for (final item in await _list('/v1/lessons')) Lesson.fromJson(item)];

  @override
  Future<List<LinkedDevice>> devices() async =>
      [for (final item in await _list('/v1/devices')) LinkedDevice.fromJson(item)];

  @override
  Future<void> revoke(String deviceId) => _send('DELETE', '/v1/devices/$deviceId');

  @override
  Future<Pairing> pairing() async => Pairing.fromJson(await _object('POST', '/v1/pairing'));

  @override
  Future<({bool listening, String problem, List<VoiceEntry> items, Activity activity})> voiceHistory(
      int after) async {
    final json = await _object('GET', '/v1/voice/history?after=$after');
    return (
      listening: json['listening'] as bool? ?? false,
      problem: json['problem'] as String? ?? '',
      activity: Activity.fromJson(json['activity'] as Map<String, dynamic>?),
      items: [for (final item in json['items'] as List<dynamic>) VoiceEntry.fromJson(item as Map<String, dynamic>)],
    );
  }

  @override
  Future<({bool listening, String problem})> setListening(bool on) async {
    final json = await _object('POST', '/v1/voice/listening', {'enabled': on});
    return (listening: json['listening'] as bool? ?? false, problem: json['problem'] as String? ?? '');
  }
}
