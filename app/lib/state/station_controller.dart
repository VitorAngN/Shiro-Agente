import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/models/mood.dart';
import '../core/models/records.dart';
import '../core/models/turn.dart';
import '../core/structures/bounded_log.dart';
import '../core/structures/pending_set.dart';
import '../data/engine_client.dart';
import '../data/engine_launcher.dart';
import '../data/preferences.dart';

/// Etapas da abertura, mostradas na tela enquanto o programa sobe tudo sozinho.
enum BootStep { lookingForEngine, startingEngine, waitingForEngine, ready, failed }

/// Tudo o que o programa sabe e faz. A tela só lê este estado e chama os métodos.
class StationController extends ChangeNotifier {
  StationController({
    required Future<EngineApi?> Function() connect,
    required EngineLauncher launcher,
    required Preferences preferences,
    Duration pollEvery = const Duration(seconds: 1),
    Duration engineWait = const Duration(seconds: 90),
  })  : _connect = connect,
        _launcher = launcher,
        _preferences = preferences,
        _pollEvery = pollEvery,
        _engineWait = engineWait;

  final Future<EngineApi?> Function() _connect;
  final EngineLauncher _launcher;
  final Preferences _preferences;
  final Duration _pollEvery;
  final Duration _engineWait;

  EngineApi? engine;
  Mood mood = Mood.starting;
  Section section = Section.conversa;
  BootStep step = BootStep.lookingForEngine;
  String problem = '';

  final BoundedLog<Turn> turns = BoundedLog(200);
  final PendingSet pending = PendingSet();
  List<Lesson> lessons = const [];
  List<LinkedDevice> devices = const [];

  bool listeningForName = false;
  bool switchingName = false;
  String voiceProblem = '';
  Activity activity = Activity.idle;

  int _voiceCursor = -1;
  Timer? _poll;
  bool _polling = false;
  bool _disposed = false;

  bool get busy => mood == Mood.thinking || mood == Mood.listening;

  // ---------------------------------------------------------------- abertura

  /// Abre tudo de que o programa depende: motor (que liga o Ollama), listas e
  /// a escuta do nome, se ela estava ligada da última vez.
  Future<void> boot() async {
    await _preferences.load();
    _set(() {
      step = BootStep.lookingForEngine;
      mood = Mood.starting;
      problem = '';
    });
    if (!await _tryConnect()) {
      _set(() => step = BootStep.startingEngine);
      final failure = await _launcher.start();
      if (failure != null) return _fail(failure);
      _set(() => step = BootStep.waitingForEngine);
      final deadline = DateTime.now().add(_engineWait);
      while (DateTime.now().isBefore(deadline) && !_disposed) {
        await Future<void>.delayed(const Duration(milliseconds: 750));
        if (await _tryConnect()) break;
      }
      if (engine == null) {
        return _fail('O motor não respondeu. Rode na pasta do projeto: uv run shiro serve');
      }
    }
    _set(() {
      step = BootStep.ready;
      mood = Mood.idle;
    });
    await refreshLists();
    if (_preferences.listenForName) await setListening(true, remember: false);
    _poll ??= Timer.periodic(_pollEvery, (_) => _tick());
  }

  Future<bool> _tryConnect() async {
    try {
      final candidate = await _connect();
      if (candidate == null) return false;
      await candidate.me();
      engine = candidate;
      return true;
    } catch (_) {
      return false;
    }
  }

  void _fail(String message) {
    _set(() {
      step = BootStep.failed;
      mood = Mood.offline;
      problem = message;
    });
  }

  // --------------------------------------------------------------- conversa

  Future<void> send(String text) async {
    final current = engine;
    final asked = text.trim();
    if (current == null || asked.isEmpty || busy) return;
    final turn = Turn(asked: asked, at: DateTime.now());
    _set(() {
      turns.add(turn);
      mood = Mood.thinking;
    });
    try {
      turn.answer(await current.chat(asked));
    } catch (error) {
      turn.fail('Não consegui falar com o motor: $error');
      _lostEngine();
    }
    _finishTurn();
  }

  /// Botão do microfone: o motor dá o bipe, ouve, responde em voz alta.
  Future<void> listenOnce() async {
    final current = engine;
    if (current == null || busy) return;
    final turn = Turn(asked: '…', at: DateTime.now(), spoken: true);
    _set(() {
      turns.add(turn);
      mood = Mood.listening;
    });
    try {
      final result = await current.voice();
      if (result == null) {
        turns.remove(turn);
      } else {
        turn
          ..asked = result['heard'] as String
          ..answer(result);
      }
    } catch (error) {
      turn
        ..asked = '(voz)'
        ..fail('A voz não funcionou: $error');
    }
    _finishTurn();
  }

  void _finishTurn() {
    _set(() {
      pending.clear();
      mood = engine == null ? Mood.offline : Mood.speaking;
    });
    refreshLists();
    Timer(const Duration(seconds: 2), () {
      if (mood == Mood.speaking) _set(() => mood = Mood.idle);
    });
  }

  Future<void> answer(PendingConfirmation item, {required bool approve}) async {
    _set(() => pending.resolve(item.id));
    try {
      await engine?.answer(item.id, approve: approve);
    } catch (_) {}
  }

  void open(Section value) => _set(() => section = value);

  // ------------------------------------------------------- escuta do nome

  Future<void> setListening(bool on, {bool remember = true}) async {
    final current = engine;
    if (current == null) return;
    _set(() {
      switchingName = true;
      voiceProblem = '';
    });
    try {
      final state = await current.setListening(on);
      listeningForName = state.listening;
      voiceProblem = state.problem;
    } catch (error) {
      voiceProblem = '$error';
    }
    if (remember) await _preferences.setListenForName(on);
    _set(() => switchingName = false);
  }

  // ----------------------------------------------------------- dispositivos

  Future<Pairing> openPairing() => engine!.pairing();

  Future<void> revoke(LinkedDevice device) async {
    try {
      await engine?.revoke(device.id);
    } catch (_) {}
    await refreshLists();
  }

  Future<void> refreshLists() async {
    final current = engine;
    if (current == null) return;
    try {
      final learned = await current.lessons();
      final linked = await current.devices();
      _set(() {
        lessons = learned;
        devices = linked;
      });
    } catch (_) {}
  }

  // ------------------------------------------------------------- vigília

  /// A cada segundo: conversas puxadas pelo nome e perguntas de confirmação.
  Future<void> _tick() async {
    final current = engine;
    if (current == null || _polling) return;
    _polling = true;
    try {
      final voice = await current.voiceHistory(_voiceCursor < 0 ? 0 : _voiceCursor);
      final firstLook = _voiceCursor < 0;
      _voiceCursor = voice.items.fold<int>(
        _voiceCursor < 0 ? 0 : _voiceCursor,
        (last, item) => item.id > last ? item.id : last,
      );
      final waiting = await current.confirmations();
      _set(() {
        activity = voice.activity;
        listeningForName = voice.listening;
        if (!switchingName) voiceProblem = voice.problem;
        for (final item in voice.items) {
          // o que aconteceu antes de o programa abrir fica de fora
          if (firstLook || !item.calledByName) continue;
          turns.add(Turn(asked: item.heard, at: DateTime.now(), spoken: true)..answer(item.json));
        }
        pending.replaceWith(waiting);
      });
    } on EngineError catch (error) {
      // o motor respondeu: só a chave recusada pede reconexão; o resto é um aviso
      if (error.status == null || error.status == 401 || error.status == 403) {
        _lostEngine();
      } else {
        _set(() => voiceProblem = error.message);
      }
    } catch (_) {
      _lostEngine();
    } finally {
      _polling = false;
    }
  }

  void _lostEngine() {
    _poll?.cancel();
    _poll = null;
    engine = null;
    _voiceCursor = -1;
    _set(() {
      mood = Mood.offline;
      step = BootStep.lookingForEngine;
    });
    // tenta voltar sozinho: o motor pode ter sido reiniciado
    Timer(const Duration(seconds: 3), () {
      if (!_disposed && engine == null) boot();
    });
  }

  void _set(VoidCallback change) {
    if (_disposed) return;
    change();
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    super.dispose();
  }
}
