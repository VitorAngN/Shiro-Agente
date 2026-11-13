import 'dart:convert';

import 'shiro_paths.dart';

/// Escolhas do usuário que valem entre uma abertura e outra do programa.
class Preferences {
  Preferences(this._paths);

  final ShiroPaths _paths;
  Map<String, Object?> _values = {};

  bool get listenForName => _values['listen_for_name'] as bool? ?? false;

  Future<void> load() async {
    try {
      _values = (jsonDecode(await _paths.preferences.readAsString()) as Map<String, dynamic>).cast();
    } catch (_) {
      _values = {};
    }
  }

  Future<void> setListenForName(bool on) async {
    _values['listen_for_name'] = on;
    try {
      await _paths.preferences.parent.create(recursive: true);
      await _paths.preferences.writeAsString(jsonEncode(_values));
    } catch (_) {
      // preferência é conveniência: se não gravar, só vale nesta abertura
    }
  }
}
