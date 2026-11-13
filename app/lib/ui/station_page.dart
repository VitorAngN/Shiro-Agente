import 'package:flutter/material.dart';

import '../app/tokens.dart';
import '../core/models/mood.dart';
import '../data/shiro_paths.dart';
import '../state/station_controller.dart';
import 'screens/boot_screen.dart';
import 'screens/conversation_screen.dart';
import 'screens/devices_screen.dart';
import 'screens/lessons_screen.dart';
import 'widgets/presence_panel.dart';
import 'widgets/sidebar.dart';

/// A Estação: menu à esquerda, a seção no meio, ela à direita.
class StationPage extends StatelessWidget {
  const StationPage({super.key, required this.controller});

  final StationController controller;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: ListenableBuilder(
        listenable: controller,
        builder: (context, _) => LayoutBuilder(builder: (context, box) {
          final wide = box.maxWidth >= 1000;
          return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Sidebar(section: controller.section, onSelect: controller.open),
            const VerticalDivider(width: 1, color: Palette.line),
            Expanded(child: _section()),
            if (wide) ...[
              const VerticalDivider(width: 1, color: Palette.line),
              SizedBox(width: 320, child: PresencePanel(controller: controller, paths: ShiroPaths.fromEnvironment())),
            ],
          ]);
        }),
      ),
    );
  }

  Widget _section() {
    if (controller.engine == null) return BootScreen(controller: controller);
    return switch (controller.section) {
      Section.conversa => ConversationScreen(controller: controller),
      Section.ensinar => LessonsScreen(controller: controller),
      Section.dispositivos => DevicesScreen(controller: controller),
    };
  }
}
