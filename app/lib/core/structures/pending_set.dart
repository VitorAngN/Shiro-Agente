import 'dart:collection';

import '../models/records.dart';

/// Perguntas de confirmação abertas, sem repetir e na ordem em que chegaram.
///
/// O motor é consultado a cada segundo; o mapa por id evita mostrar a mesma
/// pergunta duas vezes e some com as que já foram respondidas ou venceram.
class PendingSet extends IterableBase<PendingConfirmation> {
  final LinkedHashMap<String, PendingConfirmation> _byId = LinkedHashMap();

  /// Troca pelo que o motor tem agora; `true` se algo mudou.
  bool replaceWith(Iterable<PendingConfirmation> current) {
    final fresh = {for (final item in current) item.id: item};
    final changed = fresh.length != _byId.length || !fresh.keys.every(_byId.containsKey);
    if (changed) {
      _byId
        ..clear()
        ..addAll(fresh);
    }
    return changed;
  }

  void resolve(String id) => _byId.remove(id);

  void clear() => _byId.clear();

  @override
  int get length => _byId.length;

  @override
  Iterator<PendingConfirmation> get iterator => _byId.values.iterator;
}
