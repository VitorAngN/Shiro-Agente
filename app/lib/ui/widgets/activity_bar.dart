import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/records.dart';

/// Barra acima do campo de texto: o que a SHIRO está fazendo e há quanto tempo.
///
/// O motor diz a etapa (ouvindo, pensando, rodando uma ação, esperando você,
/// respondendo); a barra conta os segundos entre uma consulta e outra.
class ActivityBar extends StatelessWidget {
  const ActivityBar({super.key, required this.activity, required this.sending});

  final Activity activity;
  final bool sending; // pedido digitado ainda sem resposta do motor

  static const _labels = {
    'listening': 'Ouvindo',
    'thinking': 'Pensando',
    'tool': 'Fazendo',
    'confirming': 'Esperando você',
    'speaking': 'Respondendo',
  };

  Color get _color => switch (activity.stage) {
        'confirming' => Palette.yellow,
        'tool' => Palette.red,
        _ => Palette.cyan,
      };

  @override
  Widget build(BuildContext context) {
    final shown = activity.active || sending;
    final label = _labels[activity.stage] ?? 'Enviando';
    final detail = activity.active ? activity.detail : 'mandando o pedido';
    final total = activity.totalSeconds;
    return AnimatedSize(
      duration: const Duration(milliseconds: 180),
      child: !shown
          ? const SizedBox(width: double.infinity)
          : Padding(
              padding: const EdgeInsets.fromLTRB(32, 6, 32, 0),
              child: Container(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
                decoration: BoxDecoration(
                  color: Palette.surface,
                  borderRadius: Corners.medium,
                  border: Border.all(color: _color.withValues(alpha: 0.45)),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: _color)),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        detail,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 13, color: Palette.fg),
                      ),
                    ),
                    if (total > 0)
                      Text(
                        '${total.toStringAsFixed(0)} s',
                        style: const TextStyle(fontSize: 12, fontFamily: Fonts.mono, color: Palette.muted),
                      ),
                  ]),
                  const SizedBox(height: 10),
                  ClipRRect(
                    borderRadius: Corners.pill,
                    child: LinearProgressIndicator(
                      minHeight: 3,
                      color: _color,
                      backgroundColor: Palette.line,
                    ),
                  ),
                ]),
              ),
            ),
    );
  }
}
