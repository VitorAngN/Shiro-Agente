import 'package:flutter/material.dart';

import '../state/station_controller.dart';
import '../ui/station_page.dart';
import 'tokens.dart';

class ShiroApp extends StatelessWidget {
  const ShiroApp({super.key, required this.controller});

  final StationController controller;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SHIRO',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: Palette.bg,
        fontFamily: Fonts.display,
        fontFamilyFallback: Fonts.fallback,
        colorScheme: const ColorScheme.dark(
          primary: Palette.cyan,
          surface: Palette.surface,
          error: Palette.red,
        ),
        textSelectionTheme: const TextSelectionThemeData(cursorColor: Palette.cyan),
        tooltipTheme: const TooltipThemeData(
          decoration: BoxDecoration(color: Palette.raised, borderRadius: Corners.small),
          textStyle: TextStyle(color: Palette.fg, fontSize: 12),
        ),
      ),
      home: StationPage(controller: controller),
    );
  }
}
