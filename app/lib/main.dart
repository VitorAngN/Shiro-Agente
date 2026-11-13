// SHIRO · Estação: o programa do PC (ADR-0022).
//
// Camadas, de fora para dentro:
//   ui/     telas e componentes (só desenham o estado)
//   state/  StationController: o que o programa sabe e faz (ChangeNotifier)
//   data/   motor (HTTP), quem liga o motor, preferências em disco
//   core/   modelos e estruturas de dados, sem Flutter
import 'package:flutter/material.dart';

import 'app/shiro_app.dart';
import 'data/engine_client.dart';
import 'data/engine_launcher.dart';
import 'data/preferences.dart';
import 'data/shiro_paths.dart';
import 'state/station_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final paths = ShiroPaths.fromEnvironment();
  final controller = StationController(
    connect: () => HttpEngineClient.local(paths),
    launcher: EngineLauncher(paths),
    preferences: Preferences(paths),
  );
  runApp(ShiroApp(controller: controller));
  controller.boot();
}
