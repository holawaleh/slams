# Phones, tablets, PWA and the Android app

The dashboard is one React app that runs three ways:

| How | What the user does | Built by |
|---|---|---|
| Website | opens the Vercel address | `npm run build` (Vercel does this) |
| Installed PWA | Chrome/Edge: account menu → **Install app**; iPhone Safari: Share → **Add to Home Screen** | same build: `vite-plugin-pwa` adds the manifest and service worker |
| Android app (APK) | installs the APK | Capacitor, from the same build |

The service worker keeps only the app itself (HTML, JS, CSS, icons) for
offline start. API responses are never cached: attendance is always live.

## Building the APK

Needs Android Studio's SDK and **Java 21** (Capacitor 8's Gradle cannot
run on Java 25, which Android Studio bundles).

```powershell
cd frontend
$env:JAVA_HOME = "<path to a JDK 21>"   # e.g. %USERPROFILE%\.gradle\jdks\eclipse_adoptium-21-...
npm run apk
# -> android\app\build\outputs\apk\debug\app-debug.apk
```

`npm run apk` builds the web app with `.env.android` (the live backend
address), copies it into the Android project, and runs Gradle. Open
`android/` in Android Studio to run it on a phone or make a signed
release build for the Play Store.

The backend must allow the app's origin `https://localhost`; this is in
`config/settings.py`, so it only needs deploying.

## Icons

`npm run icons` renders every icon (PWA, Apple, Android launcher) from
one design in `scripts/make-icons.mjs`, using the Chrome or Edge on the
machine.

## Checking phones and touch screens

```powershell
# backend with demo data, on a throwaway database
$env:DATABASE_URL=""; $env:SQLITE_PATH="$env:TEMP\ui.sqlite3"; $env:CORS_ORIGINS="http://127.0.0.1:4173"
python manage.py migrate; python manage.py seed_demo --password Demo-pass1
python manage.py runserver 127.0.0.1:8000
# frontend
npm run build; npx vite preview --port 4173
node scripts/ui-check.mjs http://127.0.0.1:4173 ui-shots
```

Checks every page on an Android phone, iPhone, small phone, tablet in
both orientations (all with touch) and a desktop: nothing may overflow
sideways, form fields must be 16px or larger on phones (smaller makes
iPhones zoom), touch targets must be finger-sized, the menu drawer and
bottom-sheet dialogs must work by tap, and the PWA must install and open
offline. Screenshots land in `ui-shots/`.
