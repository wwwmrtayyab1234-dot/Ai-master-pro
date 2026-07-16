import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import 'native.dart';
import 'rewarded.dart';

class Extension extends FletExtension {
  @override
  void ensureInitialized() {
    if (isMobilePlatform()) {
      MobileAds.instance.initialize();
    }
  }

  @override
  FletService? createService(Control control) {
    if (control.type == "RewardedAd") {
      return RewardedAdService(control: control);
    }
    return null;
  }

  @override
  Widget? createWidget(Key? key, Control control) {
    if (control.type == "NativeAd") {
      return NativeAdControl(key: key, control: control);
    }
    return null;
  }
}
