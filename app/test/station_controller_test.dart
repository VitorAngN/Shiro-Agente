import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shiro_app/core/models/mood.dart';
import 'package:shiro_app/core/models/records.dart';
import 'package:shiro_app/data/engine_client.dart';
import 'package:shiro_app/data/engine_launcher.dart';
import 'package:shiro_app/data/preferences.dart';
import 'package:shiro_app/data/shiro_paths.dart';
import 'package:shiro_app/state/station_controller.dart';

/// Motor de mentira: responde na hora e conta o que pediram.
class FakeEngine implements EngineApi {
  final asked = <String>[];
  bool listening = false;

  @override
  Future<void> me() async {}

  @override
  Future<Map<String, dynamic>> chat(String text) async {
    asked.add(text);
    return {'text': 'ok: $text', 'tier': 'T0', 'latency_ms': 3, 'tools': ['get_time']};
  }

  @override
  Future<Map<String, dynamic>?> voice() async => null;

  @override
  Future<List<PendingConfirmation>> confirmations() async => const [];

  @override
  Future<void> answer(String id, {required bool approve}) async {}

  @override
  Future<List<Lesson>> lessons() async => const [Lesson(trigger: 'modo jogo', meaning: 'abra a steam')];

  @override
  Future<List<LinkedDevice>> devices() async => const [LinkedDevice(id: '1', name: 'Este PC')];

  @override
  Future<void> revoke(String deviceId) async {}

  @override
  Future<Pairing> pairing() => throw UnimplementedError();

  @override
  Future<({bool listening, String problem, List<VoiceEntry> items})> voiceHistory(int after) async =>
      (listening: listening, problem: '', items: const <VoiceEntry>[]);

  @override
  Future<({bool listening, String problem})> setListening(bool on) async {
    listening = on;
    return (listening: on, problem: '');
  }
}

void main() {
  late Directory folder;
  late ShiroPaths paths;

  setUp(() async {
    folder = await Directory.systemTemp.createTemp('shiro');
    paths = ShiroPaths(folder.path);
  });

  tearDown(() => folder.delete(recursive: true));

  test('abre direto quando o motor já está rodando e lembra da escuta do nome', () async {
    await paths.preferences.writeAsString('{"listen_for_name": true}');
    final engine = FakeEngine();
    final controller = StationController(
      connect: () async => engine,
      launcher: EngineLauncher(paths),
      preferences: Preferences(paths),
    );
    await controller.boot();

    expect(controller.step, BootStep.ready);
    expect(controller.mood, Mood.idle);
    expect(controller.lessons.single.trigger, 'modo jogo');
    expect(engine.listening, isTrue); // ligada sozinha, como estava
    controller.dispose();
  });

  test('sem motor e sem engine.json, explica o que fazer', () async {
    final controller = StationController(
      connect: () async => null,
      launcher: EngineLauncher(paths),
      preferences: Preferences(paths),
    );
    await controller.boot();

    expect(controller.step, BootStep.failed);
    expect(controller.problem, contains('uv run shiro serve'));
    controller.dispose();
  });

  test('uma mensagem vira uma troca respondida', () async {
    final engine = FakeEngine();
    final controller = StationController(
      connect: () async => engine,
      launcher: EngineLauncher(paths),
      preferences: Preferences(paths),
    );
    await controller.boot();
    await controller.send('que horas são?');

    expect(engine.asked, ['que horas são?']);
    expect(controller.turns.single.reply, 'ok: que horas são?');
    expect(controller.turns.single.tierLabel, 'regra');
    controller.dispose();
  });
}
