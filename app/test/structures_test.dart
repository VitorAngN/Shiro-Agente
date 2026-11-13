import 'package:flutter_test/flutter_test.dart';
import 'package:shiro_app/core/models/records.dart';
import 'package:shiro_app/core/structures/bounded_log.dart';
import 'package:shiro_app/core/structures/pending_set.dart';

void main() {
  test('BoundedLog guarda só os últimos itens', () {
    final log = BoundedLog<int>(3);
    for (var i = 1; i <= 5; i++) {
      log.add(i);
    }
    expect(log.toList(), [3, 4, 5]);
    expect(log[0], 3);
    expect(log.remove(4), isTrue);
    expect(log.toList(), [3, 5]);
  });

  test('PendingSet não repete perguntas e some com as respondidas', () {
    final set = PendingSet();
    const steam = PendingConfirmation(id: 'a', prompt: 'Abrir a Steam?');
    const chrome = PendingConfirmation(id: 'b', prompt: 'Abrir o Chrome?');
    expect(set.replaceWith([steam]), isTrue);
    expect(set.replaceWith([steam]), isFalse); // mesma pergunta, nada muda
    expect(set.replaceWith([steam, chrome]), isTrue);
    set.resolve('a');
    expect(set.map((p) => p.prompt).toList(), ['Abrir o Chrome?']);
  });

  test('Pairing conta o tempo que falta e monta o QR', () {
    final pairing = Pairing.fromJson({
      'code': 'xyz',
      'host': '127.0.0.1',
      'port': 8766,
      'expires_at': '2026-11-13T12:02:00.000-03:00',
    });
    final now = DateTime.parse('2026-11-13T12:00:30.000-03:00');
    expect(pairing.remaining(now), const Duration(seconds: 90));
    expect(pairing.onlyThisPc, isTrue);
    expect(pairing.qrPayload['code'], 'xyz');
  });
}
