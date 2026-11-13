/// Uma troca da conversa: o pedido e a resposta dela.
class Turn {
  Turn({required this.asked, required this.at, this.spoken = false});

  String asked;
  final DateTime at;
  final bool spoken;
  String? reply;
  String? tier;
  int? latencyMs;
  List<String> tools = const [];
  bool failed = false;

  bool get answered => reply != null;

  /// Preenche a resposta a partir do JSON do motor (`/v1/chat`, `/v1/voice`).
  void answer(Map<String, dynamic> json) {
    reply = json['text'] as String?;
    tier = json['tier'] as String?;
    latencyMs = json['latency_ms'] as int?;
    tools = [for (final tool in (json['tools'] as List<dynamic>? ?? const [])) tool as String];
  }

  void fail(String message) {
    failed = true;
    reply = message;
  }

  /// "regra", "local" ou "nuvem", como aparece na etiqueta da resposta.
  String? get tierLabel => switch (tier) {
        'T0' => 'regra',
        'T1' => 'local',
        'T2' => 'nuvem',
        _ => null,
      };
}
