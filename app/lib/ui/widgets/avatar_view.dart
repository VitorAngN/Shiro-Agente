import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:webview_windows/webview_windows.dart';

import '../../app/tokens.dart';
import '../../core/models/mood.dart';
import '../../data/shiro_paths.dart';
import 'core_orb.dart';

/// Ela em 3D (SHIRO.vrm na pasta de dados), num WebView2 com as bibliotecas embutidas.
/// Sem o modelo ou sem WebView2, o núcleo animado fica no lugar.
class AvatarView extends StatefulWidget {
  const AvatarView({super.key, required this.mood, required this.paths});

  final Mood mood;
  final ShiroPaths paths;

  @override
  State<AvatarView> createState() => _AvatarViewState();
}

class _AvatarViewState extends State<AvatarView> {
  static const _assets = [
    'avatar.html',
    'three.module.js',
    'GLTFLoader.js',
    'BufferGeometryUtils.js',
    'three-vrm.module.js',
  ];

  final _web = WebviewController();
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final folder = widget.paths.avatar;
      final sep = Platform.pathSeparator;
      if (!await File('${folder.path}${sep}SHIRO.vrm').exists()) return;
      for (final name in _assets) {
        await File('${folder.path}$sep$name').writeAsString(await rootBundle.loadString('assets/$name'));
      }
      await _web.initialize();
      await _web.setBackgroundColor(Palette.surface);
      await _web.setPopupWindowPolicy(WebviewPopupWindowPolicy.deny);
      await _web.addVirtualHostNameMapping('shiro.avatar', folder.path, WebviewHostResourceAccessKind.allow);
      await _web.loadUrl('https://shiro.avatar/avatar.html');
      if (!mounted) return;
      setState(() => _ready = true);
      _push();
    } catch (_) {
      // sem WebView2: o núcleo continua no lugar
    }
  }

  void _push() {
    if (_ready) _web.executeScript("window.setMood && window.setMood('${widget.mood.name}')");
  }

  @override
  void didUpdateWidget(AvatarView old) {
    super.didUpdateWidget(old);
    if (old.mood != widget.mood) _push();
  }

  @override
  void dispose() {
    _web.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) return Center(child: CoreOrb(mood: widget.mood));
    return IgnorePointer(child: Webview(_web));
  }
}
