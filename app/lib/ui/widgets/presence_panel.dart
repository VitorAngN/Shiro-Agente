import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/mood.dart';
import '../../data/shiro_paths.dart';
import '../../state/station_controller.dart';
import 'avatar_view.dart';

/// Painel da direita: ela, o estado dela e a chave da escuta do nome.
class PresencePanel extends StatelessWidget {
  const PresencePanel({super.key, required this.controller, required this.paths});

  final StationController controller;
  final ShiroPaths paths;

  (String, Color) get _state => switch (controller.mood) {
        Mood.starting => ('Acordando', Palette.cyan),
        Mood.idle => ('Na escuta', Palette.line),
        Mood.listening => ('Ouvindo', Palette.red),
        Mood.thinking => ('Pensando', Palette.cyan),
        Mood.speaking => ('Respondeu', Palette.cyan),
        Mood.offline => ('Desligada', Palette.red),
      };

  @override
  Widget build(BuildContext context) {
    final (label, color) = _state;
    final c = controller;
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        AspectRatio(
          aspectRatio: 52 / 64,
          child: Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: Palette.surface,
              borderRadius: const BorderRadius.all(Radius.circular(24)),
              border: Border.all(color: color, width: 2),
            ),
            child: Stack(children: [
              Positioned.fill(child: AvatarView(mood: c.mood, paths: paths)),
              Positioned(
                top: 14,
                right: 14,
                child: Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              ),
            ]),
          ),
        ),
        const SizedBox(height: 14),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          const Text('SHIRO', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
            decoration: BoxDecoration(border: Border.all(color: color), borderRadius: Corners.pill),
            child: Text(label, style: TextStyle(fontSize: 13, color: c.mood == Mood.idle ? Palette.muted : color)),
          ),
        ]),
        const SizedBox(height: 18),
        _NameSwitch(controller: c),
        const SizedBox(height: 18),
        _fact('Expressões aprendidas', '${c.lessons.length}'),
        _fact('Aparelhos ligados', '${c.devices.length}'),
      ]),
    );
  }

  Widget _fact(String label, String value) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.line))),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: const TextStyle(fontSize: 14)),
        Text(value, style: const TextStyle(fontSize: 14, fontFamily: Fonts.mono, color: Palette.muted)),
      ]),
    );
  }
}

class _NameSwitch extends StatelessWidget {
  const _NameSwitch({required this.controller});

  final StationController controller;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final on = c.listeningForName;
    final note = c.voiceProblem.isNotEmpty
        ? c.voiceProblem
        : on
            ? 'Microfone aberto. Diga "Shiro" e o pedido.'
            : 'Desligado: use o microfone da conversa.';
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 12),
      decoration: BoxDecoration(
        color: Palette.surface,
        borderRadius: Corners.large,
        border: Border.all(color: on ? Palette.red : Palette.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
            child: Text('Atender quando chamarem "Shiro"', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          ),
          if (c.switchingName)
            const Padding(
              padding: EdgeInsets.all(12),
              child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Palette.cyan)),
            )
          else
            Switch(
              value: on,
              onChanged: c.engine == null ? null : (value) => c.setListening(value),
              activeThumbColor: Palette.red,
            ),
        ]),
        Text(note,
            style: TextStyle(
                fontSize: 12, height: 1.4, color: c.voiceProblem.isNotEmpty ? Palette.red : Palette.muted)),
      ]),
    );
  }
}
