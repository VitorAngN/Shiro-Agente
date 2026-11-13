import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../app/tokens.dart';
import '../../core/models/records.dart';
import '../../state/station_controller.dart';
import '../widgets/pill_button.dart';

class DevicesScreen extends StatefulWidget {
  const DevicesScreen({super.key, required this.controller});

  final StationController controller;

  @override
  State<DevicesScreen> createState() => _DevicesScreenState();
}

class _DevicesScreenState extends State<DevicesScreen> {
  Pairing? _pairing;
  Timer? _clock;
  String _note = '';

  @override
  void dispose() {
    _clock?.cancel();
    super.dispose();
  }

  Future<void> _open() async {
    try {
      final pairing = await widget.controller.openPairing();
      setState(() {
        _pairing = pairing;
        _note = '';
      });
      _clock?.cancel();
      _clock = Timer.periodic(const Duration(seconds: 1), (_) {
        widget.controller.refreshLists(); // o aparelho novo aparece assim que parear
        if (mounted) setState(() {});
      });
    } catch (error) {
      setState(() => _note = 'Não consegui gerar o código: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final pairing = _pairing;
    final left = pairing?.remaining(DateTime.now()) ?? Duration.zero;
    final live = pairing != null && left > Duration.zero;
    return ListView(padding: const EdgeInsets.fromLTRB(32, 28, 32, 28), children: [
      const Text('Dispositivos', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      const Text('Cada aparelho tem a própria chave e pode ser desligado daqui.',
          style: TextStyle(fontSize: 14, color: Palette.muted)),
      const SizedBox(height: 24),
      for (final device in widget.controller.devices)
        Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.fromLTRB(18, 10, 10, 10),
          decoration: const BoxDecoration(color: Palette.surface, borderRadius: Corners.large),
          child: Row(children: [
            Container(width: 8, height: 8, decoration: const BoxDecoration(color: Palette.cyan, shape: BoxShape.circle)),
            const SizedBox(width: 12),
            Expanded(child: Text(device.name, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600))),
            if (!device.isThisPc) PillButton(label: 'Desligar', onTap: () => widget.controller.revoke(device)),
            if (device.isThisPc)
              const Padding(
                padding: EdgeInsets.all(12),
                child: Text('é aqui que ela roda', style: TextStyle(fontSize: 13, color: Palette.muted)),
              ),
          ]),
        ),
      const SizedBox(height: 22),
      const Text('Ligar outro aparelho', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
      const SizedBox(height: 14),
      if (live)
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Palette.fg,
              borderRadius: Corners.large,
              border: Border.all(color: Palette.cyan, width: 2),
            ),
            child: QrImageView(data: jsonEncode(pairing.qrPayload), size: 220, backgroundColor: Palette.fg),
          ),
          const SizedBox(width: 24),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${left.inMinutes}:${(left.inSeconds % 60).toString().padLeft(2, '0')}',
                  style: const TextStyle(fontSize: 40, fontFamily: Fonts.mono, color: Palette.cyan)),
              const Text('O código vale uma vez só.', style: TextStyle(fontSize: 14, color: Palette.muted)),
              const SizedBox(height: 14),
              const Text('No app da SHIRO no celular, toque em "Ligar a um PC" e aponte para o código.',
                  style: TextStyle(fontSize: 14, height: 1.5)),
              if (pairing.onlyThisPc) ...[
                const SizedBox(height: 14),
                const Text(
                    'O motor está escutando só neste PC. Para o celular alcançar, ponha o endereço do '
                    'Tailscale em [devices] host no shiro.toml.',
                    style: TextStyle(fontSize: 13, color: Palette.yellow, height: 1.5)),
              ],
            ]),
          ),
        ])
      else
        Row(children: [
          PillButton(label: pairing == null ? 'Gerar o código' : 'Gerar outro código', onTap: _open, fill: Palette.fg),
          const SizedBox(width: 14),
          if (_note.isNotEmpty) Expanded(child: Text(_note, style: const TextStyle(fontSize: 14, color: Palette.red))),
        ]),
    ]);
  }
}
