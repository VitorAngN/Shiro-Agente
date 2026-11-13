import 'package:flutter/material.dart';

import '../../app/tokens.dart';
import '../../core/models/mood.dart';

class Sidebar extends StatelessWidget {
  const Sidebar({super.key, required this.section, required this.onSelect});

  final Section section;
  final ValueChanged<Section> onSelect;

  static const _items = [
    (Section.conversa, 'Conversa', Icons.chat_bubble_outline),
    (Section.ensinar, 'Ensinar', Icons.school_outlined),
    (Section.dispositivos, 'Dispositivos', Icons.devices_outlined),
  ];

  @override
  Widget build(BuildContext context) {
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
              Text('SHIRO',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, letterSpacing: 4, color: Palette.red)),
            ]),
          ),
          const SizedBox(height: 28),
          for (final (value, label, icon) in _items) _item(value, label, icon),
          const Spacer(),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 8),
            child: Text('Diga "Shiro" com a escuta ligada, ou use o microfone da conversa.',
                style: TextStyle(fontSize: 12, height: 1.4, color: Palette.muted)),
          ),
        ]),
      ),
    );
  }

  Widget _item(Section value, String label, IconData icon) {
    final on = section == value;
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: InkWell(
        onTap: () => onSelect(value),
        borderRadius: Corners.medium,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(color: on ? Palette.raised : null, borderRadius: Corners.medium),
          child: Row(children: [
            Icon(icon, size: 18, color: on ? Palette.fg : Palette.muted),
            const SizedBox(width: 12),
            Text(label,
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: on ? Palette.fg : Palette.muted)),
          ]),
        ),
      ),
    );
  }
}
