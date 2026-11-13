import 'dart:convert';
import 'dart:io';

import 'shiro_paths.dart';

/// Liga o motor sozinho quando o programa abre e ele não está rodando.
///
/// Na primeira vez que roda (`uv run shiro serve`), o motor grava em `engine.json`
/// como ser iniciado de novo (o Python do projeto, sem janela de terminal). O
/// motor, ao subir, também liga o Ollama e aquece o modelo.
class EngineLauncher {
  EngineLauncher(this._paths);

  final ShiroPaths _paths;
  bool _started = false;

  bool get started => _started;

  /// `null` se ligou; senão, a explicação para mostrar na tela.
  Future<String?> start() async {
    if (_started) return null;
    final Map<String, dynamic> spec;
    try {
      spec = jsonDecode(await _paths.engineSpec.readAsString()) as Map<String, dynamic>;
    } catch (_) {
      return 'Ainda não sei onde o motor está instalado. Na pasta do projeto, rode uma vez: uv run shiro serve';
    }
    try {
      await Process.start(
        spec['exe'] as String,
        [for (final arg in spec['args'] as List<dynamic>) arg as String],
        mode: ProcessStartMode.detached,
      );
      _started = true;
      return null;
    } catch (error) {
      return 'Não consegui ligar o motor ($error). Rode na pasta do projeto: uv run shiro serve';
    }
  }
}
