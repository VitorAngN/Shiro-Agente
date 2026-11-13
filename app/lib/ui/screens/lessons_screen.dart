import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/mood.dart';
import '../../state/station_controller.dart';
import '../widgets/pill_button.dart';

class LessonsScreen extends StatelessWidget {
  const LessonsScreen({super.key, required this.controller});

  final StationController controller;

  void _say(String text) {
    controller.open(Section.conversa);
    controller.send(text);
  }

  @override
  Widget build(BuildContext context) {
    final lessons = controller.lessons;
    return ListView(padding: const EdgeInsets.fromLTRB(32, 28, 32, 28), children: [
      const Text('Ensinar', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      const Text('Na conversa, diga: "quando eu disser modo jogo, feche o Discord e abra a Steam".',
          style: TextStyle(fontSize: 14, color: Palette.muted)),
      const SizedBox(height: 24),
      if (lessons.isEmpty)
        const Text('Você ainda não ensinou nenhuma expressão.', style: TextStyle(fontSize: 15, color: Palette.muted)),
      for (final lesson in lessons)
        Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.fromLTRB(18, 12, 12, 12),
          decoration: const BoxDecoration(color: Palette.surface, borderRadius: Corners.large),
          child: Row(children: [
            SizedBox(
              width: 220,
              child: Text(lesson.trigger,
                  style: const TextStyle(fontSize: 15, fontFamily: Fonts.mono, color: Palette.cyan)),
            ),
            Expanded(child: Text(lesson.meaning, style: const TextStyle(fontSize: 15))),
            PillButton(label: 'Testar', onTap: () => _say(lesson.trigger)),
            const SizedBox(width: 8),
            PillButton(label: 'Esquecer', onTap: () => _say('desaprende ${lesson.trigger}')),
          ]),
        ),
    ]);
  }
}
