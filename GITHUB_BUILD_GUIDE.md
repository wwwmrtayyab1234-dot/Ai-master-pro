# GitHub Actions APK Build — Step by Step

## 1. Check the repository root

Upload the contents of `AI_Master_Pro_Full_MVP` so these files are directly at
the GitHub repository root:

```text
.github/workflows/build.yml
main.py
pyproject.toml
requirements.txt
services/
extensions/
assets/
```

Do not upload `.env`, `.venv`, `build`, or `release`.

## 2. Push the project

From the project folder:

```powershell
git init
git add .
git commit -m "Add AI Master Pro Android build"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

If the repository is already connected, only run `git add .`, `git commit`,
and `git push`.

## 3. Add required GitHub Secrets

Open:

**Repository → Settings → Secrets and variables → Actions → Secrets → New
repository secret**

Create every name exactly as written:

```text
GROQ_API_KEY
GEMINI_API_KEY
ELEVENLABS_API_KEY
FIREBASE_API_KEY
FIREBASE_AUTH_DOMAIN
FIREBASE_PROJECT_ID
FIREBASE_APP_ID
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
```

Use new rotated API keys. Never commit the local `.env` file.

`GOOGLE_OAUTH_CLIENT_SECRET` is validated as a repository secret but is
intentionally not copied into the Android APK. Mobile apps are public OAuth
clients, so a client secret inside an APK would not remain secret.

## 4. Add optional GitHub Variables

Open the **Variables** tab and add these when available:

```text
PRIVACY_POLICY_URL
APP_SHARE_URL
SUPPORT_EMAIL
WHATSAPP_NUMBER
```

## 5. Start the build

A push to `main` or `master` starts the workflow automatically. It can also be
started manually from:

**Actions → Build Android APK → Run workflow**

The workflow installs Python 3.12, Java 17, Android tools and the pinned Python
dependencies, runs all tests, creates the temporary build configuration, and
runs Flet's Android APK builder.

## 6. Download the APK

After the job turns green, open the latest workflow run. In **Artifacts**,
download:

```text
AI-Master-Pro-APK-<run number>
```

Unzip it to get `AI_Master_Pro.apk`.

## Maintenance message

If login displays “the app is currently under maintenance”, first verify all
Firebase Secrets above. Also enable Email/Password and Google providers in
Firebase Authentication and register the Android package/signing fingerprints.
The workflow blocks empty required Secrets, but it cannot prove that a supplied
Firebase value is valid.

## Security boundary

GitHub Secrets prevent keys from appearing in the repository and mask them in
Actions logs. They cannot make a key inside a distributed APK impossible to
extract. Before public release, route Groq, Gemini and ElevenLabs calls through
an authenticated backend and keep provider keys only on that backend.
