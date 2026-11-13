import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../state/station_controller.dart';
import '../widgets/core_orb.dart';
import '../widgets/pill_button.dart';

/// Enquanto o programa liga o motor (e o motor liga o Ollama), ou quando algo falhou.
class BootScreen extends StatelessWidget {
  const BootScreen({super.key, required this.controller});

  final StationController controller;

  static const _steps = {
    BootStep.lookingForEngine: 'Procurando o motor',
    BootStep.startingEngine: 'Ligando o motor',
    BootStep.waitingForEngine: 'Carregando o modelo e a memória',
  };

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final failed = c.step == BootStep.failed;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          CoreOrb(mood: c.mood),
          const SizedBox(height: 28),
          Text(failed ? 'A SHIRO não conseguiu acordar' : 'A SHIRO está acordando',
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
          const SizedBox(height: 18),
          if (!failed) ...[
            for (final entry in _steps.entries) _StepLine(label: entry.value, state: _stateOf(entry.key, c.step)),
          ] else ...[
            Text(c.problem, textAlign: TextAlign.center, style: const TextStyle(fontSize: 15, color: Palette.muted, height: 1.5)),
            const SizedBox(height: 22),
            PillButton(label: 'Tentar de novo', onTap: c.boot, fill: Palette.fg),
          ],
        ]),
      ),
    );
  }

  static int _stateOf(BootStep line, BootStep current) {
    final order = BootStep.values;
    if (order.indexOf(current) > order.indexOf(line)) return 2; // feito
    return current == line ? 1 : 0; // agora : depois
  }
}

class _StepLine extends StatelessWidget {
  const _StepLine({required this.label, required this.state});

  final String label;
  final int state;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) { 2 => Palette.cyan, 1 => Palette.fg, _ => Palette.muted };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        SizedBox(
          width: 18,
          height: 18,
          child: state == 1
              ? const CircularProgressIndicator(strokeWidth: 2, color: Palette.cyan)
              : Icon(state == 2 ? Icons.check : Icons.circle_outlined, size: 16, color: color),
        ),
        const SizedBox(width: 12),
        Text(label, style: TextStyle(fontSize: 15, color: color)),
      ]),
    );
  }
}
