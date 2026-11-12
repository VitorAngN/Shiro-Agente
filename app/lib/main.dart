// SHIRO · Estação: o programa do PC. Fala com o motor (`shiro serve`) pela API dos
// aparelhos (ADR-0022) usando a chave do aparelho "Este PC".
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

const bg = Color(0xFF0B0D12);
const surface = Color(0xFF11141B);
const line = Color(0xFF262C38);
const fg = Color(0xFFEEF1F6);
const muted = Color(0xFF9AA3B2);
const red = Color(0xFFFF2E4D);
const cyan = Color(0xFF34E4F0);
const yellow = Color(0xFFFFD23F);

void main() => runApp(const ShiroApp());

class ShiroApp extends StatelessWidget {
  const ShiroApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SHIRO',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: bg,
        fontFamily: 'Segoe UI',
        colorScheme: const ColorScheme.dark(primary: cyan, surface: surface, error: red),
        textSelectionTheme: const TextSelectionThemeData(cursorColor: cyan),
      ),
      home: const Station(),
    );
  }
}

/// Cliente da API dos aparelhos.
class Engine {
  Engine(this.base, this.token);

  final Uri base;
  final String token;
  final HttpClient _http = HttpClient()..connectionTimeout = const Duration(seconds: 3);

  static String dataDir() {
    final custom = Platform.environment['SHIRO_DATA_DIR'];
    if (custom != null && custom.isNotEmpty) return custom;
    return '${Platform.environment['LOCALAPPDATA']}\\SHIRO';
  }

  static Future<Engine?> local() async {
    final file = File('${dataDir()}\\local-client.token');
    if (!await file.exists()) return null;
    final token = (await file.readAsString()).trim();
    if (token.isEmpty) return null;
    return Engine(Uri.parse('http://127.0.0.1:8766'), token);
  }

  Future<dynamic> _send(String method, String path, [Object? body]) async {
    final request = await _http.openUrl(method, base.resolve(path));
    request.headers.set('Authorization', 'Bearer $token');
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.add(utf8.encode(jsonEncode(body)));
    }
    final response = await request.close();
    final text = await utf8.decodeStream(response);
    if (response.statusCode >= 400) {
      throw HttpException('${response.statusCode}: $text');
    }
    return text.isEmpty ? null : jsonDecode(text);
  }

  Future<Map<String, dynamic>> me() async => (await _send('GET', '/v1/me')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> chat(String text) async =>
      (await _send('POST', '/v1/chat', {'text': text})) as Map<String, dynamic>;
  Future<List<dynamic>> confirmations() async => (await _send('GET', '/v1/confirmations')) as List<dynamic>;
  Future<void> answer(String id, bool approve) => _send('POST', '/v1/confirmations/$id', {'approve': approve});
  Future<List<dynamic>> lessons() async => (await _send('GET', '/v1/lessons')) as List<dynamic>;
  Future<List<dynamic>> devices() async => (await _send('GET', '/v1/devices')) as List<dynamic>;
}

class Turn {
  Turn(this.asked, this.at);
  final String asked;
  final DateTime at;
  String? reply;
  String? tier;
  int? latencyMs;
  List<String> tools = const [];
  bool failed = false;
}

enum Mood { idle, thinking, speaking, offline }

enum Section { conversa, ensinar, dispositivos }

class Station extends StatefulWidget {
  const Station({super.key});

  @override
  State<Station> createState() => _StationState();
}

class _StationState extends State<Station> {
  Engine? engine;
  Mood mood = Mood.offline;
  Section section = Section.conversa;
  final turns = <Turn>[];
  final input = TextEditingController();
  final focus = FocusNode();
  final scroll = ScrollController();
  List<dynamic> pending = const [];
  List<dynamic> lessons = const [];
  List<dynamic> devices = const [];
  Process? _engineProcess;
  Timer? _poll;
  String problem = 'Procurando o motor da SHIRO…';

  @override
  void initState() {
    super.initState();
    _connect();
    _poll = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _connect() async {
    try {
      final found = await Engine.local();
      if (found == null) throw const HttpException('sem chave');
      await found.me();
      if (!mounted) return;
      setState(() {
        engine = found;
        mood = Mood.idle;
        problem = '';
      });
      _refreshLists();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        engine = null;
        mood = Mood.offline;
        problem = 'O motor não está rodando.';
      });
    }
  }

  /// O motor grava em `engine.json` como foi iniciado da última vez; o programa repete.
  Future<void> _startEngine() async {
    setState(() => problem = 'Ligando o motor…');
    const help = 'Na pasta do projeto, rode uma vez: uv run shiro serve';
    try {
      final spec = jsonDecode(await File('${Engine.dataDir()}\\engine.json').readAsString()) as Map<String, dynamic>;
      final args = [for (final a in spec['args'] as List<dynamic>) a as String];
      _engineProcess = await Process.start(spec['exe'] as String, args, mode: ProcessStartMode.detached);
    } catch (_) {
      setState(() => problem = 'Ainda não sei onde o motor está instalado. $help');
      return;
    }
    for (var i = 0; i < 60 && engine == null; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 750));
      await _connect();
    }
    if (engine == null && mounted) setState(() => problem = 'O motor não respondeu. $help');
  }

  Future<void> _tick() async {
    final current = engine;
    if (current == null) {
      if (_engineProcess == null) _connect();
      return;
    }
    if (mood != Mood.thinking) return;
    try {
      final waiting = await current.confirmations();
      if (mounted) setState(() => pending = waiting);
    } catch (_) {}
  }

  Future<void> _refreshLists() async {
    final current = engine;
    if (current == null) return;
    try {
      final learned = await current.lessons();
      final linked = await current.devices();
      if (mounted) {
        setState(() {
          lessons = learned;
          devices = linked;
        });
      }
    } catch (_) {}
  }

  Future<void> _send([String? preset]) async {
    final current = engine;
    final text = (preset ?? input.text).trim();
    if (current == null || text.isEmpty || mood == Mood.thinking) return;
    final turn = Turn(text, DateTime.now());
    setState(() {
      turns.add(turn);
      mood = Mood.thinking;
      input.clear();
    });
    _toEnd();
    try {
      final result = await current.chat(text);
      turn
        ..reply = result['text'] as String?
        ..tier = result['tier'] as String?
        ..latencyMs = result['latency_ms'] as int?
        ..tools = [for (final t in result['tools'] as List<dynamic>) t as String];
    } catch (error) {
      turn
        ..failed = true
        ..reply = 'Não consegui falar com o motor. Confira se ele continua rodando.';
      _connect();
    }
    if (!mounted) return;
    setState(() {
      pending = const [];
      mood = engine == null ? Mood.offline : Mood.speaking;
    });
    _toEnd();
    _refreshLists();
    focus.requestFocus();
    Timer(const Duration(seconds: 2), () {
      if (mounted && mood == Mood.speaking) setState(() => mood = Mood.idle);
    });
  }

  void _toEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (scroll.hasClients) {
        scroll.animateTo(scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  Future<void> _answer(String id, bool approve) async {
    try {
      await engine?.answer(id, approve);
    } catch (_) {}
    if (mounted) setState(() => pending = const []);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: LayoutBuilder(builder: (context, box) {
        final wide = box.maxWidth >= 1000;
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Sidebar(section: section, onSelect: (s) => setState(() => section = s)),
            const VerticalDivider(width: 1, color: line),
            Expanded(child: _main()),
            if (wide) ...[
              const VerticalDivider(width: 1, color: line),
              SizedBox(width: 320, child: _Presence(mood: mood, lessons: lessons.length, devices: devices.length)),
            ],
          ],
        );
      }),
    );
  }

  Widget _main() {
    if (engine == null) return _Offline(problem: problem, onStart: _startEngine, onRetry: _connect);
    switch (section) {
      case Section.ensinar:
        return _Lessons(lessons: lessons, onTry: (text) {
          setState(() => section = Section.conversa);
          _send(text);
        });
      case Section.dispositivos:
        return _Devices(devices: devices);
      case Section.conversa:
        return _conversation();
    }
  }

  Widget _conversation() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(
          child: turns.isEmpty
              ? _Empty(onPick: _send)
              : ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.fromLTRB(32, 28, 32, 12),
                  itemCount: turns.length,
                  itemBuilder: (context, index) => _TurnView(turn: turns[index]),
                ),
        ),
        for (final item in pending)
          _Confirm(
            prompt: (item as Map<String, dynamic>)['prompt'] as String,
            onYes: () => _answer(item['id'] as String, true),
            onNo: () => _answer(item['id'] as String, false),
          ),
        const Divider(height: 1, color: line),
        Padding(
          padding: const EdgeInsets.fromLTRB(32, 16, 32, 22),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: input,
                focusNode: focus,
                autofocus: true,
                onSubmitted: (_) => _send(),
                style: const TextStyle(fontSize: 15, color: fg),
                decoration: const InputDecoration(
                  hintText: 'Digite para ela',
                  hintStyle: TextStyle(color: muted),
                  filled: true,
                  fillColor: surface,
                  contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 16),
                  enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: line)),
                  focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: cyan, width: 2)),
                ),
              ),
            ),
            const SizedBox(width: 12),
            _Button(label: mood == Mood.thinking ? 'Pensando…' : 'Enviar', onTap: mood == Mood.thinking ? null : _send),
          ]),
        ),
      ],
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.section, required this.onSelect});
  final Section section;
  final ValueChanged<Section> onSelect;

  @override
  Widget build(BuildContext context) {
    Widget item(Section value, String label, IconData icon) {
      final on = section == value;
      return InkWell(
        onTap: () => onSelect(value),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(
            color: on ? surface : null,
            border: Border(left: BorderSide(color: on ? fg : Colors.transparent, width: 2)),
          ),
          child: Row(children: [
            Icon(icon, size: 18, color: on ? fg : muted),
            const SizedBox(width: 12),
            Text(label, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: on ? fg : muted)),
          ]),
        ),
      );
    }

    return SizedBox(
      width: 216,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 24, 16, 20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 8),
            child: Row(children: [
              Text('白', style: TextStyle(fontSize: 32, fontWeight: FontWeight.w300, height: 1)),
              SizedBox(width: 10),
              Text('SHIRO', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, letterSpacing: 4, color: red)),
            ]),
          ),
          const SizedBox(height: 28),
          item(Section.conversa, 'Conversa', Icons.chat_bubble_outline),
          item(Section.ensinar, 'Ensinar', Icons.school_outlined),
          item(Section.dispositivos, 'Dispositivos', Icons.devices_outlined),
          const Spacer(),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 8),
            child: Text('Voz: Ctrl+Alt+Espaço, com a SHIRO na bandeja', style: TextStyle(fontSize: 12, color: muted)),
          ),
        ]),
      ),
    );
  }
}

class _TurnView extends StatelessWidget {
  const _TurnView({required this.turn});
  final Turn turn;

  @override
  Widget build(BuildContext context) {
    final time = '${turn.at.hour.toString().padLeft(2, '0')}:${turn.at.minute.toString().padLeft(2, '0')}';
    final tierLabel = switch (turn.tier) {
      'T0' => 'regra',
      'T1' => 'local',
      'T2' => 'nuvem',
      _ => null,
    };
    final seconds = turn.latencyMs == null ? '' : ' · ${(turn.latencyMs! / 1000).toStringAsFixed(2).replaceAll('.', ',')} s';
    return Padding(
      padding: const EdgeInsets.only(bottom: 22),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 800),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$time  você', style: const TextStyle(fontSize: 12, color: muted, fontFamily: 'Consolas')),
          const SizedBox(height: 6),
          SelectableText(turn.asked, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.only(left: 16),
            decoration: const BoxDecoration(border: Border(left: BorderSide(color: line, width: 2))),
            child: turn.reply == null
                ? const Text('…', style: TextStyle(fontSize: 16, color: cyan))
                : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SelectableText(turn.reply!,
                        style: TextStyle(fontSize: 16, height: 1.55, color: turn.failed ? red : fg)),
                    if (tierLabel != null) ...[
                      const SizedBox(height: 8),
                      Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                        for (final tool in turn.tools)
                          Text(tool, style: const TextStyle(fontSize: 12, fontFamily: 'Consolas')),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
                          decoration: BoxDecoration(border: Border.all(color: turn.tier == 'T0' ? fg : cyan)),
                          child: Text('$tierLabel$seconds',
                              style: TextStyle(fontSize: 12, color: turn.tier == 'T0' ? fg : cyan)),
                        ),
                      ]),
                    ],
                  ]),
          ),
        ]),
      ),
    );
  }
}

class _Confirm extends StatelessWidget {
  const _Confirm({required this.prompt, required this.onYes, required this.onNo});
  final String prompt;
  final VoidCallback onYes;
  final VoidCallback onNo;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(32, 0, 32, 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: surface, border: Border.all(color: yellow)),
      child: Row(children: [
        Expanded(
          child: Text(prompt, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: yellow)),
        ),
        const SizedBox(width: 12),
        _Button(label: 'Sim', onTap: onYes, fill: yellow),
        const SizedBox(width: 10),
        _Button(label: 'Não', onTap: onNo),
      ]),
    );
  }
}

class _Button extends StatelessWidget {
  const _Button({required this.label, required this.onTap, this.fill});
  final String label;
  final VoidCallback? onTap;
  final Color? fill;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
        minimumSize: const Size(0, 50),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        backgroundColor: fill,
        foregroundColor: fill == null ? fg : bg,
        disabledForegroundColor: muted,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.zero, side: BorderSide(color: fill ?? line)),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, fontFamily: 'Segoe UI'),
      ),
      child: Text(label),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.onPick});
  final ValueChanged<String> onPick;

  @override
  Widget build(BuildContext context) {
    const ideas = ['Que horas são?', 'O que eu tenho hoje?', 'O que você aprendeu?', 'Aumenta o volume'];
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Text('Pode falar comigo.', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        const Text('Peça algo ou comece por um destes:', style: TextStyle(fontSize: 14, color: muted)),
        const SizedBox(height: 20),
        Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
          for (final idea in ideas) _Button(label: idea, onTap: () => onPick(idea)),
        ]),
      ]),
    );
  }
}

class _Offline extends StatelessWidget {
  const _Offline({required this.problem, required this.onStart, required this.onRetry});
  final String problem;
  final VoidCallback onStart;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('A SHIRO está desligada', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
          const SizedBox(height: 10),
          Text(problem, style: const TextStyle(fontSize: 15, color: muted, height: 1.5)),
          const SizedBox(height: 22),
          Row(children: [
            _Button(label: 'Ligar o motor', onTap: onStart, fill: fg),
            const SizedBox(width: 10),
            _Button(label: 'Tentar de novo', onTap: onRetry),
          ]),
        ]),
      ),
    );
  }
}

class _Lessons extends StatelessWidget {
  const _Lessons({required this.lessons, required this.onTry});
  final List<dynamic> lessons;
  final ValueChanged<String> onTry;

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.fromLTRB(32, 28, 32, 28), children: [
      const Text('Ensinar', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      const Text('Na conversa, diga: "quando eu disser modo jogo, feche o Discord e abra a Steam".',
          style: TextStyle(fontSize: 14, color: muted)),
      const SizedBox(height: 24),
      if (lessons.isEmpty)
        const Text('Você ainda não ensinou nenhuma expressão.', style: TextStyle(fontSize: 15, color: muted)),
      for (final item in lessons)
        Container(
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: line))),
          child: Row(children: [
            SizedBox(
              width: 220,
              child: Text((item as Map<String, dynamic>)['trigger'] as String,
                  style: const TextStyle(fontSize: 15, fontFamily: 'Consolas', color: cyan)),
            ),
            Expanded(child: Text(item['meaning'] as String, style: const TextStyle(fontSize: 15))),
            _Button(label: 'Testar', onTap: () => onTry(item['trigger'] as String)),
            const SizedBox(width: 8),
            _Button(label: 'Esquecer', onTap: () => onTry('desaprende ${item['trigger']}')),
          ]),
        ),
    ]);
  }
}

class _Devices extends StatelessWidget {
  const _Devices({required this.devices});
  final List<dynamic> devices;

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.fromLTRB(32, 28, 32, 28), children: [
      const Text('Dispositivos', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      const Text('Cada aparelho tem a própria chave. O pareamento do celular por QR vem a seguir.',
          style: TextStyle(fontSize: 14, color: muted)),
      const SizedBox(height: 24),
      for (final item in devices)
        Container(
          padding: const EdgeInsets.symmetric(vertical: 16),
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: line))),
          child: Row(children: [
            Container(width: 8, height: 8, decoration: const BoxDecoration(color: cyan, shape: BoxShape.circle)),
            const SizedBox(width: 12),
            Text((item as Map<String, dynamic>)['name'] as String,
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          ]),
        ),
    ]);
  }
}

class _Presence extends StatelessWidget {
  const _Presence({required this.mood, required this.lessons, required this.devices});
  final Mood mood;
  final int lessons;
  final int devices;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (mood) {
      Mood.idle => ('Na escuta', line),
      Mood.thinking => ('Pensando', cyan),
      Mood.speaking => ('Respondeu', cyan),
      Mood.offline => ('Desligada', red),
    };
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        AspectRatio(
          aspectRatio: 52 / 64,
          child: Container(
            decoration: BoxDecoration(color: surface, border: Border.all(color: color, width: 2)),
            child: Stack(children: [
              Center(child: _Core(mood: mood)),
              Positioned(
                top: 12,
                right: 12,
                child: Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              ),
            ]),
          ),
        ),
        const SizedBox(height: 14),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          const Text('SHIRO', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
            decoration: BoxDecoration(border: Border.all(color: color)),
            child: Text(label, style: TextStyle(fontSize: 13, color: mood == Mood.idle ? muted : color)),
          ),
        ]),
        const SizedBox(height: 24),
        _fact('Expressões aprendidas', '$lessons'),
        _fact('Aparelhos ligados', '$devices'),
      ]),
    );
  }

  Widget _fact(String label, String value) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: line))),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: const TextStyle(fontSize: 14)),
        Text(value, style: const TextStyle(fontSize: 14, fontFamily: 'Consolas', color: muted)),
      ]),
    );
  }
}

/// Núcleo que fica no lugar dela até o modelo 3D entrar: pulsa quando ela pensa.
class _Core extends StatefulWidget {
  const _Core({required this.mood});
  final Mood mood;

  @override
  State<_Core> createState() => _CoreState();
}

class _CoreState extends State<_Core> with SingleTickerProviderStateMixin {
  late final AnimationController spin =
      AnimationController(vsync: this, duration: const Duration(seconds: 6))..repeat();

  @override
  void dispose() {
    spin.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final still = MediaQuery.of(context).disableAnimations || widget.mood == Mood.offline;
    final color = widget.mood == Mood.offline ? line : (widget.mood == Mood.idle ? fg : cyan);
    return AnimatedBuilder(
      animation: spin,
      builder: (context, _) {
        final speed = widget.mood == Mood.thinking ? 4.0 : 1.0;
        final turn = still ? 0.0 : spin.value * speed;
        return SizedBox(
          width: 150,
          height: 150,
          child: Stack(alignment: Alignment.center, children: [
            RotationTransition(
              turns: AlwaysStoppedAnimation(turn),
              child: Container(
                width: 130,
                height: 130,
                decoration: BoxDecoration(border: Border.all(color: color, width: 1.5)),
              ),
            ),
            RotationTransition(
              turns: AlwaysStoppedAnimation(-turn * 1.5 + 0.125),
              child: Container(
                width: 92,
                height: 92,
                decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: 0.6), width: 1.5)),
              ),
            ),
            const Text('白', style: TextStyle(fontSize: 44, fontWeight: FontWeight.w300, height: 1)),
          ]),
        );
      },
    );
  }
}
