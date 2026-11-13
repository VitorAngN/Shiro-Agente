import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import 'pill_button.dart';

/// "Abrir a Steam?" com Sim e Não: ações que pedem confirmação esperam aqui.
class ConfirmBanner extends StatelessWidget {
  const ConfirmBanner({super.key, required this.prompt, required this.onYes, required this.onNo});

  final String prompt;
  final VoidCallback onYes;
  final VoidCallback onNo;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(32, 0, 32, 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Palette.surface,
        borderRadius: Corners.large,
        border: Border.all(color: Palette.yellow),
      ),
      child: Row(children: [
        Expanded(
          child: Text(prompt, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Palette.yellow)),
        ),
        const SizedBox(width: 12),
        PillButton(label: 'Sim', onTap: onYes, fill: Palette.yellow),
        const SizedBox(width: 10),
        PillButton(label: 'Não', onTap: onNo),
      ]),
    );
  }
}
