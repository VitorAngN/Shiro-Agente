// Identidade visual da SHIRO (ADR-0012): cores, cantos e tipografia num lugar só.
import 'package:flutter/material.dart';

abstract final class Palette {
  static const bg = Color(0xFF0B0D12);
  static const surface = Color(0xFF11141B);
  static const raised = Color(0xFF161A23);
  static const line = Color(0xFF262C38);
  static const fg = Color(0xFFEEF1F6);
  static const muted = Color(0xFF9AA3B2);
  static const red = Color(0xFFFF2E4D);
  static const cyan = Color(0xFF34E4F0);
  static const yellow = Color(0xFFFFD23F);
}

abstract final class Corners {
  static const small = BorderRadius.all(Radius.circular(10));
  static const medium = BorderRadius.all(Radius.circular(14));
  static const large = BorderRadius.all(Radius.circular(20));
  static const pill = BorderRadius.all(Radius.circular(999));
}

abstract final class Fonts {
  static const display = 'Chakra Petch';
  static const mono = 'JetBrains Mono';
  static const fallback = ['Segoe UI', 'Yu Gothic UI'];
}
