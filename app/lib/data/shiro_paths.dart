import 'dart:io';

/// Onde a SHIRO guarda os dados dela neste PC (a mesma pasta que o motor usa).
class ShiroPaths {
  const ShiroPaths(this.dataDir);

  factory ShiroPaths.fromEnvironment() {
    final custom = Platform.environment['SHIRO_DATA_DIR'];
    if (custom != null && custom.isNotEmpty) return ShiroPaths(custom);
    return ShiroPaths('${Platform.environment['LOCALAPPDATA']}${Platform.pathSeparator}SHIRO');
  }

  final String dataDir;

  String _join(String name) => '$dataDir${Platform.pathSeparator}$name';

  File get localToken => File(_join('local-client.token'));
  File get engineSpec => File(_join('engine.json'));
  File get preferences => File(_join('app.json'));
  Directory get avatar => Directory(_join('avatar'));
}
