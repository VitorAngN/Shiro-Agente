import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/mood.dart';
import '../../state/station_controller.dart';
import '../widgets/confirm_banner.dart';
import '../widgets/pill_button.dart';
import '../widgets/turn_card.dart';

class ConversationScreen extends StatefulWidget {
  const ConversationScreen({super.key, required this.controller});

  final StationController controller;

  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  final _input = TextEditingController();
  final _focus = FocusNode();
  final _scroll = ScrollController();
  int _seen = 0;

  StationController get c => widget.controller;

  @override
  void dispose() {
    _input.dispose();
    _focus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _toEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  Future<void> _send([String? preset]) async {
    final text = preset ?? _input.text;
    _input.clear();
    await c.send(text);
    _focus.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    if (c.turns.length != _seen) {
      _seen = c.turns.length;
      _toEnd();
    }
    final listening = c.mood == Mood.listening;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: c.turns.isEmpty
            ? _EmptyConversation(onPick: _send)
            : ListView.builder(
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(32, 28, 32, 12),
                itemCount: c.turns.length,
                itemBuilder: (context, index) => TurnCard(turn: c.turns[index]),
              ),
      ),
      for (final item in c.pending)
        ConfirmBanner(
          prompt: item.prompt,
          onYes: () => c.answer(item, approve: true),
          onNo: () => c.answer(item, approve: false),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(32, 12, 32, 22),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _input,
              focusNode: _focus,
              autofocus: true,
              onSubmitted: (_) => _send(),
              style: const TextStyle(fontSize: 15, color: Palette.fg),
              decoration: const InputDecoration(
                hintText: 'Digite para ela',
                hintStyle: TextStyle(color: Palette.muted),
                filled: true,
                fillColor: Palette.surface,
                contentPadding: EdgeInsets.symmetric(horizontal: 18, vertical: 16),
                enabledBorder: OutlineInputBorder(borderRadius: Corners.pill, borderSide: BorderSide(color: Palette.line)),
                focusedBorder:
                    OutlineInputBorder(borderRadius: Corners.pill, borderSide: BorderSide(color: Palette.cyan, width: 2)),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Tooltip(
            message: listening ? 'Ouvindo…' : 'Falar',
            child: InkWell(
              onTap: c.listenOnce,
              customBorder: const CircleBorder(),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: listening ? Palette.red : Colors.transparent,
                  border: Border.all(color: listening ? Palette.red : Palette.line, width: 2),
                ),
                child: Icon(Icons.mic_none, size: 24, color: listening ? Palette.bg : Palette.fg),
              ),
            ),
          ),
          const SizedBox(width: 12),
          PillButton(
            label: c.mood == Mood.thinking ? 'Pensando…' : 'Enviar',
            onTap: c.busy ? null : _send,
            fill: c.busy ? null : Palette.fg,
          ),
        ]),
      ),
    ]);
  }
}

class _EmptyConversation extends StatelessWidget {
  const _EmptyConversation({required this.onPick});

  final ValueChanged<String> onPick;

  static const _ideas = ['Que horas são?', 'O que eu tenho hoje?', 'O que você aprendeu?', 'Aumenta o volume'];

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Text('Pode falar comigo.', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        const Text('Peça algo ou comece por um destes:', style: TextStyle(fontSize: 14, color: Palette.muted)),
        const SizedBox(height: 20),
        Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
          for (final idea in _ideas) PillButton(label: idea, onTap: () => onPick(idea)),
        ]),
      ]),
    );
  }
}
