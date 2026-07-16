# AI Master Pro — Release-Candidate MVP

AI Master Pro is a responsive Flet mobile/desktop application with AI chat,
image generation, multilingual voice generation, speech-to-text, and Gemini
analysis for images, documents, audio, and video.

## What is included

- Responsive premium light login, with a wider desktop hero and compact mobile card
- Firebase email/password authentication with email-verification links
- Firebase Google Sign-In for Windows development and official Flet OAuth on mobile
- Persistent refresh-token sessions; network errors do not delete the saved session
- SecureStorage on supported devices, with a desktop compatibility fallback
- Per-Firebase-UID SQLite chats, memory, credits, and rolling usage limits
- ChatGPT-style collapsible/searchable chat-history sidebar
- Cross-chat memory for names, stated preferences, and recent conversations
- Chat import/export using account-scoped JSON backups
- Friendly offline and provider-maintenance screens
- Central crash protection for Python, background threads, async tasks, and Flet events
- Redacted rotating on-device diagnostic logs (API keys and tokens are filtered)
- Automatic SQLite integrity check with recoverable corrupt-file backup and clean rebuild
- Settings: privacy, contact, feedback, sharing, theme, import/export, logout, deletion
- Local restricted-request screening with a professional refusal message
- Android AdMob rewarded ads with provider-verified completion callbacks
- Compact native ads in Image Studio, plus full-screen image viewing and saving

## Free usage rules

All free limits use a rolling 24-hour window beginning when the user's current
window was created. They do not reset at calendar midnight.

| Feature | Rule |
|---|---|
| Credits | 50 at the start of each rolling window |
| Requests | 20 per window across chat, analysis, and prompt enhancement |
| Reward pack | Complete all 5 verified rewarded ads to receive 50 credits |
| Request refill | The completed 5-ad pack also unlocks 20 extra request slots |
| Images | Maximum 5 per window; 10 credits each |
| Voice | Actual generated audio duration: 1 second = 1 credit; maximum 60 seconds |

No partial ad reward is granted. On Android/iOS, credits are recorded only after
the Google Mobile Ads SDK sends its verified reward event. Desktop preview uses
a simulator only when `APP_ENV=development`; production fails closed when a
verified mobile callback is unavailable.

## Windows: first run

Keep the supplied folder name exactly `AI_Master_Pro_Full_MVP` and use this
space-free path:

`D:\AMP\AI_Master_Pro_Full_MVP`

1. Extract the project so `D:\AMP\AI_Master_Pro_Full_MVP\main.py` exists.
2. Double-click `setup_windows.bat` once.
3. Open the new `.env` file and replace all placeholder values.
4. In Firebase Authentication, enable Email/Password and Google providers.
5. Add `localhost` to Firebase Authentication authorized domains.
6. For mobile Google sign-in, register
   `http://localhost:8550/oauth_callback` in the Google OAuth client and add its
   client ID/secret to `.env`.
7. Double-click `run_app.bat`.

You can double-click `test_project.bat` at any time to compile the source,
run the automated test suite, and check dependency compatibility. Android build
scripts run the same checks automatically before starting Flutter.

PowerShell alternative:

```powershell
cd D:\AMP\AI_Master_Pro_Full_MVP
.\setup_windows.bat
.\run_app.bat
```

The setup launcher does not require the optional Windows `py` command. It
automatically detects `py`, `python`, `python3`, Microsoft Store Python Core,
and normal python.org installations, then uses the first Python 3.11+ runtime.
It also installs the Windows-only Flet desktop runtime required by `run_app.bat`.

## Required `.env` values

```env
GROQ_API_KEY=
ELEVENLABS_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
FIREBASE_APP_ID=
GOOGLE_OAUTH_CLIENT_ID=
# Never put a Google OAuth client secret inside a mobile APK.
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URL=http://localhost:8550/oauth_callback

PRIVACY_POLICY_URL=https://your-real-public-page.example/privacy
APP_SHARE_URL=https://play.google.com/store/apps/details?id=com.aimasterpro.app
SUPPORT_EMAIL=support@your-real-domain.example
WHATSAPP_NUMBER=

APP_ENV=development
DEV_PREMIUM_MODE=false
ADMOB_TEST_MODE=true
ADMOB_APP_ID=ca-app-pub-3725379940334991~3875540091
ADMOB_REWARDED_UNIT_ID=ca-app-pub-3725379940334991/1504372099
ADMOB_NATIVE_UNIT_ID=ca-app-pub-3725379940334991/5200642743
```

Never reuse API keys that were pasted into chat, source code, screenshots, or a
public repository. Revoke them and create fresh keys before testing this build.

## Email verification and sessions

Firebase sends a secure verification link during sign-up. The account cannot
sign in until the email is verified. A saved refresh token is exchanged for a
new short-lived ID token whenever the app starts. The app only clears a session
when Firebase reports that it was revoked or invalid—not during an internet or
provider outage.

## Privacy policy and Play Console

- `privacy_policy.html` is the editable public-policy source.
- `delete_account.html` is the external account-deletion page source.
- Replace `support@your-domain.example` everywhere before publishing it.
- Follow `PRIVACY_POLICY_DEPLOY.md` to host it on a public HTTPS URL.
- Put the final public URL in `.env` and in Google Play Console.
- Review the Google Play Data safety form against the exact production SDKs.
- The in-app deletion path is **Settings → Delete Account & Local Data**.

## Android permissions

`pyproject.toml` allows only internet and microphone access. The microphone is
used only when the user taps speech-to-text. File import/export uses Android's
system file picker, so broad storage access is not requested. Camera and
location permissions are explicitly disabled.

## AdMob release checklist

- Keep `ADMOB_TEST_MODE=true` during development and emulator/device testing.
- Use Google test ads only while testing; do not click live ads yourself.
- Set `APP_ENV=production` and `ADMOB_TEST_MODE=false` only for the signed store build.
- The AdMob app ID is included in Android manifest metadata by `pyproject.toml`.
- Rewarded and native unit IDs are selected from environment configuration.
- The image screen requests a compact native ad when generation starts; image
  generation continues independently, so an ad-network failure cannot lose the result.
- Complete Google Play Data safety and any required consent flow for the countries
  where the app is distributed before release.

## Android builds

For a locally installable APK:

```text
build_android_apk.bat
```

The build script automatically:

- rejects a project path containing spaces before Flutter starts;
- discovers Flutter and copies it to a space-free DevTools path when required;
- discovers the Android SDK and copies it away from a spaced Windows username;
- moves Dart Pub, Gradle, and temporary build caches to space-free paths;
- configures Flutter with the verified SDK; and
- copies the final file to `release\AI_Master_Pro.apk`.

Use this exact PowerShell sequence after extracting the ZIP:

```powershell
cd D:\AMP\AI_Master_Pro_Full_MVP
.\setup_windows.bat
.\build_android_apk.bat
```

For Google Play, configure a private upload keystore and use:

```text
build_play_store_aab.bat
```

Google Play recommends an Android App Bundle (AAB). Keep the keystore and its
passwords outside the project and source control. The AAB script runs
`release_check.py` and stops if test ads, development mode, placeholder keys,
placeholder policy/contact text, or invalid production URLs are still present.

## GitHub Actions APK build

The repository includes `.github/workflows/build.yml`. A push to `main` or
`master` runs dependency installation, all automated tests, the Flet Android
build, and uploads `AI_Master_Pro.apk` as a GitHub Actions artifact.

Before pushing, open **Repository Settings → Secrets and variables → Actions**
and create these repository secrets:

- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `ELEVENLABS_API_KEY`
- `FIREBASE_API_KEY`
- `FIREBASE_AUTH_DOMAIN`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_APP_ID`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`

The workflow validates all nine entries, but intentionally does not copy
`GOOGLE_OAUTH_CLIENT_SECRET` into the Android build. A mobile APK is a public
OAuth client and cannot safely protect a client secret.

Under the **Variables** tab, optionally create `PRIVACY_POLICY_URL`,
`APP_SHARE_URL`, `SUPPORT_EMAIL`, and `WHATSAPP_NUMBER`. The workflow stops
before building when a required secret is missing, which prevents an APK that
always shows the maintenance message because Firebase was not configured.

After a successful run, open **Actions → Build Android APK → latest run →
Artifacts** and download the `AI-Master-Pro-APK-*` artifact.

The existing `requirements.txt` is intentionally curated and version-pinned.
Do not replace it with `pip freeze` from a large personal environment, because
that can add Windows-only or unrelated packages to the Linux Android runner.
GitHub Secrets keep values out of the repository and masked CI logs, but any
provider key shipped inside a client APK can still be extracted. Move AI API
calls behind an authenticated backend before a public production release.

## Production security boundaries

- An API key bundled inside an APK can be extracted. Route provider calls and
  authoritative quotas through your own authenticated backend before release.
- Local SQLite properly isolates accounts on one device, but global tamper-proof
  limits and cross-device sync require Firestore/backend enforcement.
- The image queue protects one running app process. A global queue across all
  users and devices requires a server-side worker.
- The Google desktop flow uses a local callback server. Native Android Google
  Sign-In needs the final package name and signing SHA fingerprints registered
  in Firebase.
- Gemini inline analysis is limited to supported files smaller than 18 MB in
  this MVP. Large video files require Gemini's resumable Files API or a backend.
- Google Play Billing and server-verified premium entitlements are not included
  in this MVP. Do not sell or advertise the premium plan until billing,
  purchase restoration, and server-side entitlement validation are implemented.
- AdMob callbacks and layout must be checked on at least one physical Android
  phone with Google test ad unit IDs before switching to live ads.
- The final AAB still needs your private Play upload key, public policy/deletion
  URLs, support address, Firebase/OAuth production registration, and Play Console
  Data safety/consent configuration.

## Verification

Run the local core test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The 36 automated tests cover per-user credit isolation, rolling reset,
request/ad rules, image queue serialization and retries, measured voice billing,
backups, memory, session fallback, attachment hardening, Google-to-Firebase token
exchange, provider error mapping, Android configuration, responsive Flet control
tree mounting, email validation, restricted requests, secret-safe crash logging,
async exception capture, and corrupt SQLite recovery.

All context-managed SQLite connections are explicitly closed after commit or
rollback. This is important on Windows, where an open database handle prevents
`TemporaryDirectory` cleanup and otherwise causes `PermissionError [WinError
32]` during the test suite.

## Crash protection and recovery

Unexpected errors are written to a small rotating log inside the app support
directory under `ai_master_pro/logs/ai_master_pro_crash.log`. The current file
is capped at about 500 KB and only three older copies are kept. Common Groq,
Gemini, ElevenLabs, OAuth, and refresh-token formats are redacted before text is
stored. The UI shows a stable English maintenance/offline message instead of a
raw provider traceback.

At startup SQLite runs an integrity check. If the local database is corrupt,
the original is preserved beside it with a `.corrupt-<UTC timestamp>.db` name
and a fresh database is created. If the normal app-data directory cannot be
used, the app starts with an emergency local directory and records the cause in
the diagnostic log. This improves recovery, but no client application can
guarantee that every operating-system, out-of-storage, or native SDK crash is
impossible; physical Android testing and Play Console crash monitoring remain
required before release.
