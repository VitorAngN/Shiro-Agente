import 'package:flutter/material.dart';

import '../../app/tokens.dart';

/// Botão da SHIRO: contorno discreto, ou cheio para a ação principal.
class PillButton extends StatelessWidget {
  const PillButton({super.key, required this.label, required this.onTap, this.fill, this.icon});

  final String label;
  final VoidCallback? onTap;
  final Color? fill;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final style = TextButton.styleFrom(
      minimumSize: const Size(0, 48),
      padding: const EdgeInsets.symmetric(horizontal: 20),
      backgroundColor: fill,
      foregroundColor: fill == null ? Palette.fg : Palette.bg,
      disabledForegroundColor: Palette.muted,
      shape: RoundedRectangleBorder(
        borderRadius: Corners.pill,
        side: BorderSide(color: fill ?? Palette.line),
      ),
      textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, fontFamily: Fonts.display),
    );
    if (icon == null) return TextButton(onPressed: onTap, style: style, child: Text(label));
    return TextButton.icon(onPressed: onTap, style: style, icon: Icon(icon, size: 18), label: Text(label));
  }
}
