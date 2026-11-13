/// Registros que o motor devolve, já tipados (em vez de Map soltos pela tela).
class Lesson {
  const Lesson({required this.trigger, required this.meaning});

  factory Lesson.fromJson(Map<String, dynamic> json) =>
      Lesson(trigger: json['trigger'] as String, meaning: json['meaning'] as String);

  final String trigger;
  final String meaning;
}

class LinkedDevice {
  const LinkedDevice({required this.id, required this.name});

  factory LinkedDevice.fromJson(Map<String, dynamic> json) =>
      LinkedDevice(id: json['id'] as String, name: json['name'] as String);

  final String id;
  final String name;

  bool get isThisPc => name == 'Este PC';
}

class PendingConfirmation {
  const PendingConfirmation({required this.id, required this.prompt});

  factory PendingConfirmation.fromJson(Map<String, dynamic> json) =>
      PendingConfirmation(id: json['id'] as String, prompt: json['prompt'] as String);

  final String id;
  final String prompt;
}

class Pairing {
  const Pairing({required this.code, required this.host, required this.port, required this.expiresAt});

  factory Pairing.fromJson(Map<String, dynamic> json) => Pairing(
        code: json['code'] as String,
        host: json['host'] as String,
        port: json['port'] as int,
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  final String code;
  final String host;
  final int port;
  final DateTime expiresAt;

  /// O que vai no QR: o celular lê e já sabe onde e com que código entrar.
  Map<String, Object> get qrPayload => {'shiro': 1, 'host': host, 'port': port, 'code': code};

  bool get onlyThisPc => host.startsWith('127.') || host == '::1';

  Duration remaining(DateTime now) {
    final left = expiresAt.difference(now);
    return left.isNegative ? Duration.zero : left;
  }
}

/// Uma conversa por voz que o motor registrou (`/v1/voice/history`).
class VoiceEntry {
  const VoiceEntry({required this.id, required this.source, required this.heard, required this.json});

  factory VoiceEntry.fromJson(Map<String, dynamic> json) => VoiceEntry(
        id: json['id'] as int,
        source: json['source'] as String,
        heard: json['heard'] as String,
        json: json,
      );

  final int id;
  final String source; // "nome" (chamada pelo nome) ou "botão"
  final String heard;
  final Map<String, dynamic> json;

  bool get calledByName => source == 'nome';
}
