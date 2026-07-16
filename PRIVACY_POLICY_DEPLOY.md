# Publish the Privacy Policy

Google Play requires an active, publicly accessible, non-geofenced HTTPS URL.
The local `privacy_policy.html` file is the policy source, but its local file path
cannot be submitted to Play Console.

Before release:

1. Replace every `support@your-domain.example` occurrence with your real email.
2. Review the provider list and data practices against the final production app.
3. Upload both `privacy_policy.html` and `delete_account.html` to your website,
   Firebase Hosting, GitHub Pages, Cloudflare Pages, or another public HTTPS host.
4. Open the public page in a private browser window and confirm it works without
   signing in.
5. Put that exact URL in `.env` as `PRIVACY_POLICY_URL=...`.
6. Use the privacy URL and the separate deletion-page URL in Google Play Console,
   then complete the Data safety form.

The in-app deletion path is **Settings → Delete Account & Local Data**. If your
Play listing allows account creation, also publish an external account-deletion
request page or clearly documented support workflow.
