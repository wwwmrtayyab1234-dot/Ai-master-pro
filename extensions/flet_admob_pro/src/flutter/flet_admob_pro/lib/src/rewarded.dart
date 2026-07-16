import 'package:flet/flet.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../utils/ads.dart';

class RewardedAdService extends FletService {
  RewardedAdService({required super.control});

  RewardedAd? _rewardedAd;

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
    _load();
  }

  void _load() {
    RewardedAd.load(
      adUnitId: control.getString("unit_id")!,
      request: parseAdRequest(control.get("request")),
      rewardedAdLoadCallback: RewardedAdLoadCallback(
        onAdLoaded: (ad) {
          _rewardedAd = ad;
          ad.fullScreenContentCallback = FullScreenContentCallback(
            onAdShowedFullScreenContent: (_) => control.triggerEvent("open"),
            onAdImpression: (_) => control.triggerEvent("impression"),
            onAdClicked: (_) => control.triggerEvent("click"),
            onAdFailedToShowFullScreenContent: (ad, error) {
              control.triggerEvent("error", error.toString());
              ad.dispose();
              _rewardedAd = null;
            },
            onAdDismissedFullScreenContent: (ad) {
              control.triggerEvent("close");
              ad.dispose();
              _rewardedAd = null;
            },
          );
          control.triggerEvent("load");
        },
        onAdFailedToLoad: (error) {
          _rewardedAd = null;
          control.triggerEvent("error", error.toString());
        },
      ),
    );
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    if (name != "show") {
      throw Exception("Unknown RewardedAd method: $name");
    }
    final ad = _rewardedAd;
    if (ad == null) {
      control.triggerEvent("error", "The rewarded ad is not ready yet.");
      return null;
    }
    ad.show(onUserEarnedReward: (_, reward) {
      control.triggerEvent("reward", {
        "amount": reward.amount.toDouble(),
        "type": reward.type,
      });
    });
    return null;
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    _rewardedAd?.dispose();
    _rewardedAd = null;
    super.dispose();
  }
}
