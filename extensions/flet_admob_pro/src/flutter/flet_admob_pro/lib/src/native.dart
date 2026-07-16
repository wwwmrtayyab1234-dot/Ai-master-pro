import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../utils/ads.dart';

class NativeAdControl extends StatefulWidget {
  final Control control;

  const NativeAdControl({super.key, required this.control});

  @override
  State<NativeAdControl> createState() => _NativeAdControlState();
}

class _NativeAdControlState extends State<NativeAdControl>
    with FletStoreMixin {
  NativeAd? _ad;
  bool _loaded = false;
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_started) {
      _started = true;
      _load();
    }
  }

  void _load() {
    final style = widget.control.get("template_style") ?? {};
    final templateName = style["template_type"]?.toString().toLowerCase();
    final templateType = templateName?.contains("medium") == true
        ? TemplateType.medium
        : TemplateType.small;
    final nativeStyle = NativeTemplateStyle(
      templateType: templateType,
      mainBackgroundColor:
          parseColor(style["main_bgcolor"], Theme.of(context)),
      cornerRadius: parseDouble(style["corner_radius"]) ?? 16,
    );
    final ad = NativeAd(
      adUnitId: widget.control.getString("unit_id")!,
      request: parseAdRequest(widget.control.get("request")),
      nativeTemplateStyle: nativeStyle,
      listener: NativeAdListener(
        onAdLoaded: (_) {
          if (!mounted) return;
          setState(() => _loaded = true);
          widget.control.triggerEvent("load");
        },
        onAdFailedToLoad: (ad, error) {
          widget.control.triggerEvent("error", error.toString());
          ad.dispose();
        },
        onAdClicked: (_) => widget.control.triggerEvent("click"),
        onAdImpression: (_) => widget.control.triggerEvent("impression"),
        onAdClosed: (_) => widget.control.triggerEvent("close"),
        onAdOpened: (_) => widget.control.triggerEvent("open"),
        onAdWillDismissScreen: (_) =>
            widget.control.triggerEvent("will_dismiss"),
      ),
    );
    _ad = ad;
    ad.load();
  }

  @override
  Widget build(BuildContext context) {
    final ad = _ad;
    if (!_loaded || ad == null) {
      return const SizedBox.shrink();
    }
    return LayoutControl(
      control: widget.control,
      child: AdWidget(ad: ad),
    );
  }

  @override
  void dispose() {
    _ad?.dispose();
    _ad = null;
    super.dispose();
  }
}
