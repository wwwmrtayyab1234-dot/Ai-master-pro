import 'package:google_mobile_ads/google_mobile_ads.dart';

AdRequest parseAdRequest(dynamic value) {
  if (value == null) return const AdRequest();
  return AdRequest(
    keywords: value["keywords"]?.cast<String>(),
    contentUrl: value["content_url"],
    nonPersonalizedAds: value["non_personalized_ads"],
    neighboringContentUrls: value["neighboring_content_urls"]?.cast<String>(),
    httpTimeoutMillis: value["http_timeout"],
    extras: value["extras"]?.cast<String, String>(),
  );
}
