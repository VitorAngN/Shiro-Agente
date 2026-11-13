import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/mood.dart';

/// Núcleo animado: fica no lugar dela enquanto o modelo 3D não carrega.
class CoreOrb extends StatefulWidget {
  const CoreOrb({super.key, required this.mood});

  final Mood mood;

  @override
  State<CoreOrb> createState() => _CoreOrbState();
}

class _CoreOrbState extends State<CoreOrb> with SingleTickerProviderStateMixin {
  late final AnimationController _spin = AnimationController(vsync: this, duration: const Duration(seconds: 6))
    ..repeat();

  @override
  void dispose() {
    _spin.dispose();
    super.dispose();
  }

  Color get _color => switch (widget.mood) {
        Mood.offline || Mood.starting => Palette.line,
        Mood.idle => Palette.fg,
        Mood.listening => Palette.red,
        Mood.thinking || Mood.speaking => Palette.cyan,
      };

  @override
  Widget build(BuildContext context) {
    final still = MediaQuery.of(context).disableAnimations || widget.mood == Mood.offline;
    final color = _color;
    return AnimatedBuilder(
      animation: _spin,
      builder: (context, _) {
        final speed = widget.mood == Mood.thinking || widget.mood == Mood.starting ? 4.0 : 1.0;
        final turn = still ? 0.0 : _spin.value * speed;
        return SizedBox(
          width: 150,
          height: 150,
          child: Stack(alignment: Alignment.center, children: [
            RotationTransition(
              turns: AlwaysStoppedAnimation(turn),
              child: Container(
                width: 130,
                height: 130,
                decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: color, width: 1.5)),
              ),
            ),
            RotationTransition(
              turns: AlwaysStoppedAnimation(-turn * 1.5 + 0.125),
              child: Container(
                width: 92,
                height: 92,
                decoration: BoxDecoration(
                  borderRadius: const BorderRadius.all(Radius.circular(28)),
                  border: Border.all(color: color.withValues(alpha: 0.6), width: 1.5),
                ),
              ),
            ),
            const Text('白', style: TextStyle(fontSize: 44, fontWeight: FontWeight.w300, height: 1)),
          ]),
        );
      },
    );
  }
}
