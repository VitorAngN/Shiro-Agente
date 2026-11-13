import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/turn.dart';

/// Uma troca: o pedido em destaque e a resposta dela num cartão.
class TurnCard extends StatelessWidget {
  const TurnCard({super.key, required this.turn});

  final Turn turn;

  @override
  Widget build(BuildContext context) {
    final time = '${turn.at.hour.toString().padLeft(2, '0')}:${turn.at.minute.toString().padLeft(2, '0')}';
    final label = turn.tierLabel;
    final seconds = turn.latencyMs == null
        ? ''
        : ' · ${(turn.latencyMs! / 1000).toStringAsFixed(2).replaceAll('.', ',')} s';
    final chipColor = turn.tier == 'T0' ? Palette.fg : Palette.cyan;
    return Padding(
      padding: const EdgeInsets.only(bottom: 22),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 800),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(turn.spoken ? '$time  você, por voz' : '$time  você',
              style: const TextStyle(fontSize: 12, color: Palette.muted, fontFamily: Fonts.mono)),
          const SizedBox(height: 6),
          SelectableText(turn.asked, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            decoration: const BoxDecoration(color: Palette.surface, borderRadius: Corners.large),
            child: !turn.answered
                ? const Text('…', style: TextStyle(fontSize: 16, color: Palette.cyan))
                : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SelectableText(turn.reply!,
                        style: TextStyle(fontSize: 16, height: 1.55, color: turn.failed ? Palette.red : Palette.fg)),
                    if (label != null) ...[
                      const SizedBox(height: 8),
                      Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                        for (final tool in turn.tools)
                          Text(tool, style: const TextStyle(fontSize: 12, fontFamily: Fonts.mono)),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                          decoration: BoxDecoration(border: Border.all(color: chipColor), borderRadius: Corners.pill),
                          child: Text('$label$seconds', style: TextStyle(fontSize: 12, color: chipColor)),
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
