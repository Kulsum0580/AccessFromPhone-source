# AccessFromPhone

Ask your PC to do something from your phone. Every change waits for your approval, can be undone, and is logged.

## Run it

```powershell
cd C:\Users\UllaAfza\AccessFromPhone
.\run.ps1
```

If PowerShell blocks the script, run `.\.venv\Scripts\python -m handoff` instead.

The server prints a link (and a QR code), and a line saying whether an AI model is connected. Open the link on your phone while it is on the **same Wi-Fi** as this PC.

## Use it

**Without an AI model**, type one of these:

| Command | What happens |
|---|---|
| `list` or `list <folder>` | Shows files. Runs at once. |
| `read <file>` | Shows the file. Runs at once. |
| `find <pattern> [in <folder>]` | Finds files by name in every sub-folder, e.g. `find *.bak in C:\PageLogin`. Runs at once. |
| `download <file> [from <folder>]` | Plans "send <file> to your phone". Tap **Approve**, then **Download**. Works for read-only folders too. With an AI model, this is instant (no model call). |
| `move <file> to <path>` / `copy <file> to <path>` | One file at a time. Needs **Approve**, can be undone. A copy may come from a read-only folder. Never overwrites. |
| `run <command>` | Only if `commands.enabled: true`. Shows the exact command, needs **Approve**, cannot be undone. |
| `create <file> with <text>` | Shows a plan. Waits for **Approve**. |
| `delete <file>` | Shows a plan. Waits for **Approve**. |

**With an AI model**, write plain sentences ("add milk to my shopping list", "what files do I have?"). The model looks at files, then proposes changes. Nothing is written or deleted until you tap **Approve**.

After a change you can **Download** the file or **Undo** it.

## The PC's window

The window on the PC (the page with the connect code) is a small dashboard: a menu on the left and one section at a time.

- **Overview:** a greeting, four live readings (processor, memory, disk free, battery), your phones, whether unlocking is set up, how phones reach this PC, the latest activity in plain words, and a compact QR code and pairing code to connect another phone.
- **Phones:** the full connect card (Same Wi-Fi or Anywhere), and every phone with Rename, Block and Remove.
- **Unlock:** set up, switch off or on, start trying again, or remove the saved sign-in (see "Unlocking a locked PC by asking").
- **Connection:** the Wi-Fi and Anywhere details, and what to do if the PC sleeps.
- **Activity:** the latest things that happened (requests, approvals, unlocks, phones paired, sign-ins).
- **Settings:** this PC, how you sign in, and changing the password.

It remembers the section you were on. On a narrow window the menu becomes a bar across the top.

**Checking it:** `python tests/e2e/dashboard_e2e.py` and `python tests/e2e/admin_unlock_e2e.py` (a real browser against a real PC app).

## Accounts and connecting phones

The first time you start AccessFromPhone, **this PC's page** opens in your browser (`http://127.0.0.1:8766`, reachable only from the PC itself). There you:

1. **Sign in with your Windows user name and password.** There is no new account or password to create. The user name is the Windows user who runs the app (typing `name`, `DOMAIN\name` or `name@domain` all work); the password is the one you use to sign in to Windows. The first successful sign-in makes you the owner. A PIN, fingerprint or face sign-in is not a password and won't work here; use the account password.
2. **Connect a phone**: the page shows a large QR code and a short code (like `K7M2-9QXP`). Point the phone's camera at the QR code, or type the code on the phone's sign-in screen. It works once, for one phone, for 2 minutes, then the page shows a new one.
3. **Manage phones**: the same page lists every paired phone with when it was last seen. **Rename**, **Block** (signs it out at once, **Unblock** brings it back) or **Remove** any of them. A phone can also sign itself out from its Settings.

What that means for safety:
- There is **no shared link or token to keep secret** any more. Each phone holds its own random token; the PC stores only a hash of it.
- Wrong pairing codes are limited to 5 tries a minute. A wrong Windows password stops after **3 tries for 5 minutes**, so the app can never lock your real Windows account.
- Windows itself checks the password; the app never stores or logs it. Only the Windows user who runs the app can become the owner.
- Pairing, sign-outs, blocks and failed attempts all appear in the audit log.
- The PC page is a separate listener on `127.0.0.1`. Phones and other computers on the Wi-Fi cannot reach it.
- If the PC's address changes, an already paired phone just opens the new address. If a phone was removed or blocked, it is told so and asked to pair again.

Settings are in the `accounts:` section of `config.yaml`. On a system without Windows (or with `accounts.sign_in: password`) the page asks you to create a separate password and shows a recovery code instead. If that password and code are both lost, `python -m handoff --reset-owner` on the PC clears the account. Setting `accounts.enabled: false` goes back to the older single shared link (for testing only).

## Where the data lives

Everything that must outlive a restart is in **one SQLite file, `data/app.db`** (`storage.database`). There is nothing to install or run: SQLite is part of Python.

| In the database | |
|---|---|
| Owner account and paired phones | passwords and phone tokens only as hashes |
| Requests and chats | so a chat is still there after a restart or on another phone |
| Audit trail | every action, searchable, never edited |
| Folders you allowed from the phone | |

Still plain files: undo snapshots (`data/snapshots`), downloadable results, the HTTPS certificate (`data/tls`) and `config.yaml`.

- **Backup:** stop the app and copy `data/app.db` (it may sit beside `app.db-wal`; copy both, or stop the app first).
- **Upgrading:** the first start imports an older `audit.log`, `grants.json` and `accounts.json` into the database, then renames them to `.migrated` so nothing is lost or imported twice.
- **After a restart,** a request that was still running shows as failed, and one waiting for approval shows as expired, instead of hanging. Nothing runs without a fresh approval.
- The database layer is one module (`handoff/db.py`), so a company that wants SQL Server or PostgreSQL later changes it in one place.

## Reaching your PC: Wi-Fi, from anywhere, and while it sleeps

**On the same Wi-Fi (nothing to set up).** `server.public_url: auto` finds this PC's current address at every start, so a new network or a new IP never needs an edit. The QR code and the certificate follow it. If you set `connectivity.lan_address: name`, the QR holds the PC's `.local` name instead, which keeps working when the address changes; the app also announces itself on the network (`connectivity.mdns`) so that name can be found.

**From anywhere, with a trusted certificate (no "not private" warning).** The PC page has a *How phones reach this PC* card with a checklist. It uses [Tailscale](https://tailscale.com): free for personal use, private, and nothing to open on your router.

1. Install Tailscale on the PC and on the phone, and sign in to the same account on both.
2. In the Tailscale admin page, open **DNS** and choose **Enable HTTPS** (once, free).
3. On the PC page press **Turn on**. The app asks Tailscale for a real certificate and opens a second listener (`connectivity.anywhere_port`, 8443) that only your Tailscale network can reach. It is never exposed to the Wi-Fi or the internet.
4. Switch the QR card to **Anywhere** and pair the phone with that code. A phone paired this way works at home and away, because its address is the same everywhere.

A phone paired on the Wi-Fi address stays tied to that address. Pair it again from the **Anywhere** tab to use it away from home. Windows may ask once to allow the app through its firewall. `connectivity.anywhere: off` removes the whole feature. If Tailscale isn't installed, nothing changes and the app works on the Wi-Fi as before.

**When the PC sleeps.** While the app runs it asks Windows not to sleep (`power.keep_awake: true`; the screen can still turn off), which is the most reliable fix. If the PC does go off or to sleep, the phone says so, shows when it was last reachable, and has a **Try now** button. Waking a sleeping PC remotely (Wake-on-LAN) needs it turned on in the BIOS and network adapter, and something awake on that network to send the signal (a router, a Raspberry Pi, or a Tailscale subnet router), because a sleeping PC can't wake itself and a phone's browser can't send it. The PC page shows this PC's MAC address for that.

**Putting the PC to sleep from the phone.** Say "put my PC to sleep", "lock my PC", "hibernate my laptop", "restart my PC" or "shut down my PC". You get an approval card and nothing happens until you tap Approve. The phone is told "done" first and the PC acts a few seconds later. `power.remote_actions` decides what the phone may ask for; the default is `lock` and `sleep`, and `hibernate`, `restart` and `shutdown` are off until you add them. Restart and shut down count down for 15 seconds, so a mistake can be cancelled at the PC with `shutdown /a`. A sleeping PC can't be woken from the phone (see above), so the card says so before you approve. Only plain commands count: "how do I put my PC to sleep?" is answered as a question. Windows only.

## Your own relay (reach the PC from anywhere, with your domain)

The relay is a small server you run on your domain. Every PC keeps one connection open **out** to it, so customers open no ports and install nothing extra. A phone opens `https://<pc-id>.xyz.com`; the relay passes each request down that PC's connection and the answer back. The relay stores no files and cannot act on a PC: only the app on the PC can read or change anything, and every change still waits for the phone's Approve.

```
phone  ->  https://abc123def456.xyz.com  ->  relay (your server)  <-  PC app (connects out)
```

**Run the relay** (it needs Python and this package):

```
set RELAY_DOMAIN=xyz.com
set RELAY_REGISTER_KEY=<a long random secret>
set RELAY_TRUST_PROXY=1
python -m handoff.relay --host 127.0.0.1 --port 9000
```

**In front of it, a reverse proxy with a wildcard certificate** for `xyz.com` and `*.xyz.com` (this is what gives phones a trusted padlock, with no warning). With Caddy, and a DNS record `*.xyz.com` pointing at the server:

```
*.xyz.com, xyz.com {
    tls { dns <your DNS provider> <token> }   # a wildcard certificate needs a DNS challenge
    reverse_proxy 127.0.0.1:9000
}
```

**Point a PC at it** in `config.yaml`:

```
relay:
  enabled: true
  url: https://xyz.com
```

and set `HANDOFF_RELAY__REGISTER_KEY` to the same secret. On start the PC registers once (its id and secret are kept in its own database) and stays connected, reconnecting by itself. The PC page's **Anywhere** tab then shows a QR code for its own address; scan it from any network.

**Try it locally first:** `python -m handoff.relay --domain localhost --port 9100`, set `relay.url: http://localhost:9100`, and open the Anywhere QR link in Chrome (`http://<pc-id>.localhost:9100`).

What this version does and does not do:
- Each PC's address is its own origin, so one PC's phone tokens never work on another.
- Pairing, sign-in, approvals and the PC's own limits all work unchanged through it; a phone's real address reaches the PC, so wrong-code lockouts are per phone.
- The relay sees the traffic it forwards (it terminates the padlock). End-to-end encryption between phone and PC, customer accounts, licences, and a limit on how much each customer may use are the next layer; they are not in this version.
- `RELAY_REGISTER_KEY` is a shared secret for now: anyone holding it can register a PC. Per-customer accounts replace it.


## Seeing how your PC is doing

A small chip in the phone's top bar shows the PC's battery (a bolt when it is charging). Tap it, or choose **PC status** in the profile menu, for the full picture, updated every 2 seconds:

- **Battery:** percent, charging or on battery, and the time left. A desktop PC says it has none. At 20% or lower while unplugged the phone warns you once.
- **Network speed:** download and upload right now, a graph of the last minute, the adapter and its link speed, and how fast the phone itself reaches the PC (a good check of your connection).
- **Processor, memory and the system drive:** with a warning when the drive is almost full.

You can also just ask in the chat: "what's my battery?", "network speed", "how is my PC doing?". The answer comes from the PC's own readings, not from the AI. Everything is read-only and stays on your network. It needs the `psutil` package, which is installed with the app.

## The Windows app and installer

Customers don't run Python. They run **AccessFromPhone-Setup-x.y.z.exe**: a wizard (no administrator prompt) that installs the app for the current user, with a Start menu entry, an optional desktop shortcut, and an optional *Start AccessFromPhone when I sign in to Windows*.

**What the customer sees after installing**
1. The app opens in its own window (no browser bar) with the welcome and sign-in page: sign in with the Windows password, then scan the QR code with the phone.
2. A **tray icon** stays by the clock. Its colour shows the state (amber = not set up yet, grey = running, blue with a green dot = a phone is connected). Right-click for *Open*, *Connect a phone*, *Start with Windows*, *Open my data folder* and *Quit*. It also pops up "New phone connected".
3. Closing the window leaves the app running in the tray. Opening it a second time just brings the window back.
4. Windows may ask once to allow it on private networks. Allow it, so the phone can reach the PC on the Wi-Fi.

Settings, the database and logs live in `%LOCALAPPDATA%\AccessFromPhone` (never in the install folder), so updating or uninstalling doesn't touch them. The first run writes a plain `config.yaml` there and makes a `Documents\AccessFromPhone` folder for the phone to work in. Uninstalling asks whether to keep that data. Logs are in `logs\app.log`.

**Build the installer** (needs the project's `.venv` from `.\run.ps1`, and Inno Setup: `winget install JRSoftware.InnoSetup`):

```
.\packaging\build.ps1                              # makes dist\AccessFromPhone-Setup-<version>.exe
.\packaging\build.ps1 -RelayUrl https://xyz.com    # the same, with your relay address built in
```

With `-RelayUrl`, a new install registers with your server by itself and the PC page's *Anywhere* tab works straight away. The version comes from `pyproject.toml`. The script draws the icon and the wizard pictures from the same logo as the app (`packaging\make_assets.py`), packages with PyInstaller (`AccessFromPhone.spec`), and wraps it with Inno Setup (`installer.iss`).

**Before you sell it:** replace `packaging\License.txt` with your real terms, and sign the installer and `AccessFromPhone.exe` with a code-signing certificate. Without one, Windows SmartScreen shows "unknown publisher" the first time. Signing goes in as one `SignTool=` line in `installer.iss` plus a `signtool` call after PyInstaller.

## The Android app

A real Android app (not just a web page): a native shell around the same phone page the PC serves, in the `android/` folder. Open that folder in Android Studio, or build from the command line.

**What the app adds over the browser**
- A **first screen with its own QR scanner**: scan the code on the PC and it connects. Only a code that really comes from the PC is accepted. Typing the address is the fallback.
- **No "not private" warning on your Wi-Fi.** It remembers the certificate your PC showed the first time and trusts only that one, and only for addresses on your own network. If the certificate ever changes it stops and says so. A relay on the internet must have a real certificate.
- **Voice input** through Android's own recogniser (the built-in web view has none).
- **Downloads** are saved to the phone's Downloads folder.
- A proper **icon** (with the themed, one-colour version Android 13+ can use), full-screen layout, and the Back button works as expected.
- **Sign out** in the app also makes the phone forget the PC and returns to the first screen.

**Build it**
```
.\android\build.ps1            # debug APK  ->  dist\AccessFromPhone-android-debug.apk
.\android\build.ps1 -Release   # 1.5 MB, unsigned
.\android\build.ps1 -Test      # the app's unit tests
```
It uses the Java and SDK that Android Studio installed, and its own Gradle cache so a damaged shared cache can't break it. (If Android Studio's own sync fails with "Could not read workspace metadata", delete `%USERPROFILE%\.gradle\caches\8.14.3\transforms` and sync again.)

**Put it on a phone**
1. *By cable:* turn on Developer options and USB debugging on the phone, plug it in, and run `adb install -r dist\AccessFromPhone-android-debug.apk` (`adb` is in `%LOCALAPPDATA%\Android\Sdk\platform-tools`). Or press Run in Android Studio.
2. *By file:* copy the APK to the phone, open it, and allow "install from this source" when asked.

**Before the Play Store:** create a signing key, sign the release build, set the final name and `applicationId` (`android/app/build.gradle.kts` and `res/values/strings.xml`), and add a Play developer account ($25 once). A different `applicationId` installs as a different app.

## Pictures: a gallery, a viewer and an editor

Ask in plain words and the phone shows the pictures, with no AI involved (so it is instant, and nothing leaves the PC):

| You say | You get |
|---|---|
| "open any photo file", "show me my screenshots", "I want to see the images in C:\Pictures\Trip" | a **gallery** of that folder (the folder the chat was last in, else the workspace) |
| "open photo.png", "show me C:\Pictures\a.jpg" | the **viewer** |
| "edit that photo", "photoshop an image in C:\Pictures", "edit C:\Pictures\a.png" | the **editor** (for "an image" with no name, the gallery, to pick one) |

A folder outside the workspace asks first, as always. Questions stay with the AI ("how many photos are in…").

**Gallery.** A grid of thumbnails (made once and kept in `data/thumbs`), newest first. Search by name, sort by newest, oldest, name or size, make the tiles bigger or smaller. 1,000 pictures at most are listed; search narrows the rest.

**Viewer.** Pinch, wheel or +/- to zoom; double-tap to zoom in and out; drag to move; swipe, arrow keys or the strip of thumbnails to go to the next or previous picture. Details (size in pixels, file size, date, folder), share, download, and **Edit**.

**Editor** (on a phone-sized screen, built to be used with a finger; undo and redo go 30 steps back):

- **Crop**: drag the corners and edges; free, original shape, square, 4:3, 3:2 or 16:9, and turn the shape sideways.
- **Rotate**: left, right, flip either way. Resize: to a size or 25/50/75%, keeping the shape.
- **Adjust**: brightness, contrast, colour, warmth. **Filters**: Vivid, Warm, Cool, Fade, Mono, Noir, Sepia (each is just a set of the same sliders).
- **Draw**: pen and highlighter, any colour and thickness. **Shapes**: arrow, line, box, oval (outline or filled). **Text**: any words, size, colour, bold, optional label behind. **Hide**: pixelate or blur a part, such as a name or a number.
- Everything you add can be tapped, moved, resized (boxes), recoloured, duplicated, brought to the front or deleted, and it all follows along when you crop or turn the picture. Hold the eye button to compare with the picture before your colour changes and notes.
- **Save a copy** (the default: `photo (edited).png`, never replacing anything, and `(2)`, `(3)`... if the name is taken), **Replace the original** (only when the format is the same; you can undo it), or **Download**. PNG, JPEG or WebP, with a quality slider.

**Safe by design.** The PC checks every saved picture before a byte is written: it must really be a picture of the kind its file name says, within `agent.max_image_mb` (25 MB) and 100 million pixels, or it is refused. Replacing needs the folder to be allowed for editing (it asks, like the text editor), is refused if the file changed on the PC since you opened it ("save a copy instead?"), is snapshotted so it can be undone from the chat, and is recorded in the activity log with what was done ("cropped, rotated, 2 text notes"). Colours and everything you added are flattened into the saved picture; metadata inside the original, such as where a photo was taken, is not kept. A picture over about 16 million pixels is reduced for editing (the phone's browser can't hold more) and says so.

**Checking it:** `node tests/js/imaging_test.js` (the maths), `pytest tests/test_pictures.py tests/test_imaging_assets.py`, and `python tests/e2e/pictures_e2e.py` (a real browser against a real server: gallery, viewer, rotate, crop, draw, text, hide, filters, save, replace and undo, with the saved pixels checked).

## Files: walk through your PC's folders from the phone

**My files** (the button under "New chat", and in the account menu) opens a live file browser. Or ask: "browse my folders", "open the folder C:\Reports", "explore Projects", or just give a folder's path. No AI is involved, so it is instant and nothing leaves the PC.

- **Dig down.** Tap a folder to go in, tap a step in the path bar to jump back to it, or the arrow for one level up. Closing a file you opened from the browser lands you in the same folder.
- **Big folders are fine.** Only 200 entries are loaded at a time and the rest follow as you scroll (a folder of 100,000 files is as quick as one of five; beyond that it says so and search narrows it down).
- **Find your way.** Search inside the folder, sort by name, date, size or type (folders stay on top), and show or hide hidden files.
- **Live.** The list follows the folder while you look at it: a file created or deleted on the PC appears or goes within a few seconds.
- **Open anything.** Text and code open in the viewer/editor, pictures in the picture viewer (a "Pictures" chip opens the folder as a gallery), PDFs in the viewer, **video and audio play from the PC** (you can skip around in them), and everything else can be downloaded. The ⋮ menu (or press and hold) has Open, Download, Copy path and Details.
- **Safe.** It only shows folders the app is allowed to use: the workspace, the read-only folders and the ones you allowed and kept. Anything else asks first, exactly like the editor does, and `..` or shortcuts that lead elsewhere are checked after they are resolved. Protected places (this app's own secrets, SSH keys) never appear. Opening a folder, playing a file and downloading are recorded in the activity log. Downloads have no size limit by default (set `agent.max_download_mb` to cap them); files are streamed, and a folder is sent as one zip.
- **How playback is kept private.** A player can't send the phone's token, so playing a file makes a short-lived, unguessable link for that one file (2 hours, gone when the folder is taken back). It is not sent through Google or anyone else.

**Checking it:** `pytest tests/test_browse.py` and `python tests/e2e/files_e2e.py` (a real browser against a real server: four levels of folders, a 530-file folder paged in, search, live updates, sort, hidden files, a real sound played, a download checked byte for byte, and a folder outside the allowed ones asking first).

## Unlocking a locked PC by asking

Write **"unlock my PC"** (or "unlock the screen") on the phone while the PC is locked. The request waits for your approval, the approval card asks for your **unlock PIN**, and the PC types its saved Windows sign-in at the lock screen. It is off until you set it up, and it does nothing while the PC is not locked.

**Set it up once, at the PC.** Open the PC's own page (the window with the connect code): the **Unlock this PC from your phone** card, right under your phones, shows whether unlocking is **Not set up**, **On**, **Off**, **Paused** or **Stopped**. Tap **Set up unlocking**: Windows asks for permission once, a small window opens, and you choose the sign-in to save and your unlock PIN. The card updates by itself when it is done. The same card has **Switch off**, **Switch on**, **Start trying again** (after it stopped itself) and **Remove saved sign-in**, so nothing needs a terminal. The helper restarts itself when the app is updated.

If you prefer a terminal, the same setup is:

    python -m handoff.unlock.setup install

The window and the command both explain the risk, then ask for: the Windows sign-in to save, and the unlock PIN you will type on the phone (6 to 32 characters, different from the sign-in). Choose your **Windows Hello PIN** if the PC signs in with one: it only works on that one PC, so it is the safer thing to keep. A password also works if the lock screen shows the password box; it is checked with Windows first, so a mistyped one is never saved. `python -m handoff.unlock.setup status` shows whether it is running, and the PC's own page has a card with **Switch off** and **Remove saved sign-in**.

**How it is kept safe**
- The saved sign-in is encrypted for this PC only (Windows DPAPI), in a folder only the system and administrators can read (`C:\ProgramData\AccessFromPhone`). The unlock PIN is never stored, only a salted hash. The sign-in is never sent to the phone, shown, logged or put in a request: the helper only ever sends it to the keyboard of the lock screen.
- The part that types is a small helper that runs as the system (a scheduled task started at boot). It does not trust the app: it checks the PIN and counts wrong ones itself, so nothing that skips the app can guess faster. **Three wrong PINs pause it for ten minutes**, even for the right PIN.
- **Two misses in a row stop it.** If the typed sign-in did not unlock the PC twice, it stops until you have looked, so a changed Windows PIN or password can't lock your account by repeated tries. Then run `python -m handoff.unlock.setup resume`.
- Every request needs your approval *and* the PIN (unlocking asks even if `approval.require_for` is empty). The PIN is typed fresh each time, held in memory for that one request, and is in no log, no saved request and no phone storage.
- It is recorded in the activity log (`unlocked`, or `unlock_failed` with the reason, never the PIN).

**Honest limits**
- **The typing at a real lock screen has not been tested.** It needs the system account and a locked PC, so everything around it is tested (the PIN rules, the pause, the stop, the approval, the key events that will be sent, the leaks) but the last step is not. Try it once yourself: lock the PC (Win+L), write "unlock my PC" on the phone, approve with the PIN. If nothing happens, read `C:\ProgramData\AccessFromPhone\unlock.log`. It stops itself after two misses, so trying is safe.
- How it wakes the lock screen: it clicks the middle of the screen, waits 1.6 seconds, types, and presses Enter. If your sign-in screen needs something else first, this is the place to adjust (`handoff/unlock/typer.py`).
- It needs the lock screen to offer the sign-in you saved. If you saved a **password** but the PC shows the PIN box, use the PIN instead.
- It cannot unlock a PC that is asleep, off, or signed out of Windows, only one that is locked and still running the app.
- Remove it all with `python -m handoff.unlock.setup uninstall`.

**Checking it:** `pytest tests/test_unlock.py` and `python tests/e2e/unlock_e2e.py` (a real browser and a real helper on the loopback connection, with a stand-in for the lock screen's keyboard: the PIN field, a wrong PIN refused with the request still waiting, the unlock, the pause after three wrong PINs, and the PIN found nowhere afterwards).

## Notifications

A notice on a locked phone: **"Plan ready – tap to approve"**, "Job finished", "Folder access needed", "Job failed". Tapping one opens that exact request. It fires from the PC the moment a request changes state, so it works with the page closed and the phone asleep.

**How it reaches the phone.** The phone gives the PC an address once (Settings → Notifications). The PC then sends through the phone maker's push service:
- **The page on the home screen** (Android Chrome, iPhone Safari 16.4+): standard browser push with VAPID keys. The message is end-to-end encrypted, so Google or Apple cannot read it. On iPhone, add the page to the Home Screen first; Safari tabs can't receive push.
- **The Android app:** Firebase Cloud Messaging.

**What it says.** By default only *that* something needs you, never what you asked or what was found (`push.show_details: false`). Firebase messages are not end-to-end encrypted, which is why. An instant answer doesn't buzz (`push.min_seconds`), and a newer notice about a request replaces the older one. A phone that is blocked or removed on the PC is never notified.

**Turn it on.** The keys are read from where they already are, never copied into this folder. In `config.yaml`:
```yaml
push:
  enabled: true
  credentials_file: C:\path\to\.env      # holds VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT, FIREBASE_SERVICE_ACCOUNT_PATH
```
or set `push.vapid_public_key` / `push.firebase_service_account_file` directly, and put the secret half in the `HANDOFF_PUSH__VAPID_PRIVATE_KEY` environment variable. The start-up line says what is on ("push: on: browser + Android app"). If a work network re-signs connections and sending fails with a certificate error, set `push.ca_file`.

**Browser push needs a trusted https link.** A phone refuses to run the notification helper on a page with a self-signed certificate, so on your Wi-Fi (the "not private" warning) the Settings switch explains this instead of failing. It works over your relay with a real certificate. The Android app has no such limit.

**Android app: one step in the Firebase console.** Firebase only delivers to apps registered in its project. Add an Android app with package `app.accessfromphone` (the `applicationId`; use the new one if you rename it) to the Firebase project that holds the service account, download its `google-services.json`, and put it in `android/app/`. Then run `.\android\build.ps1` again. Without that file the app still builds and runs; turning notifications on says they are unavailable. The file is git-ignored.

**Home-screen install.** The page installs properly: real icons (including the masked one Android shapes itself), the dark splash screen, a long-press shortcut "Ask my PC", and an offline shell, so opening it with the PC unreachable shows the app saying "can't reach your PC" and not the browser's error page. Re-run `python tools/make_web_icons.py` only if the logo changes.

**Selling it.** For your own use the PC sends the pushes itself with your keys. For customers, their PCs must not hold *your* Firebase and VAPID keys: the relay (which you run) should send on their behalf. The push code is already separate (`handoff/push.py`), so that move is a small one when the relay goes live.

## Reading your chats when the PC is off

Your chats live on the PC, so with the PC off or out of reach the phone used to have nothing to show. Now each phone keeps a **read-only copy of its recent chats**, so you can still look up an answer, a path or a command.

- **What is kept.** The newest chats, whole (never half a chat): up to 50 chats or about 3 MB, whichever comes first, oldest dropped first. Very long results are shortened in the copy. It is saved a few seconds after something changes, and only if something did.
- **Where it is kept.** On the phone only; it is never sent anywhere. In a browser it is in the browser's own storage for this page; in the Android app it is a private file inside the app (one per PC), because the app's built-in page, which is the only one that can open when the PC is off, can't read the web view's storage for the PC's address.
- **How you reach it.** When the PC can't be reached, the "can't reach your PC" screen (in the page, and in the app's first screen) has a **View saved chats** button next to Try again and Switch PC. A banner then says *"Your PC is offline. Reading chats saved 12 minutes ago. Nothing can be sent until it is back."*
- **It is read-only.** The message box is switched off and says why; New chat, approvals, downloads, file browsing and everything else that needs the PC are not offered, and anything that slips through says the PC is offline instead of failing. Switching chats and copying text still work.
- **It ends by itself.** The page keeps looking for the PC (and the app also looks when Wi-Fi changes or you come back to it). The moment the PC answers, the banner goes, the live chats load and the message box works again. In the app, Back from the saved chats returns to the "can't reach your PC" screen.
- **It is wiped** when you sign out, when the PC removes this phone, when you forget the PC in the app, when you switch **Keep recent chats on this phone** off in Settings (on by default), or tap **Clear saved chats**.

**Not done yet:** asking for the fingerprint or PIN before the saved chats are shown, and encrypting the copy with a key held by the phone's secure store. Until then anyone holding an unlocked phone can read the copy, just as they could read the live chats; turn the setting off if that matters to you.

**Checking it:** `node tests/js/offline_test.js` (what is kept, how much, how it is read back), `pytest tests/test_offline_assets.py`, `.\android\build.ps1 -Test` (the app's private store), and `python tests/e2e/saved_chats_e2e.py` (a real browser: chats are saved, the PC is stopped, the saved chats are read and nothing else can be done, the app's built-in page shows them, the PC returns and the page goes live by itself, the setting and sign-out wipe it).

## When the PC can't be reached

The phone checks on the PC every few seconds (`/api/ping`; anything else that talks to the PC counts too). If it stops answering:

1. **Under about 8 seconds: nothing is shown.** A weak signal that comes back is not worth interrupting anyone.
2. **After that, a popup blocks the whole app.** The full app is still loaded behind it (nothing is lost), but nothing behind it can be tapped, typed into or reached by keyboard, voice and spoken replies stop, and Android's Back button only puts the app away. It says *why*, in words that fit: phone offline, on another network, PC off or asleep or lost its Wi-Fi, the app on the PC not running, relay says the PC is offline, the PC has a new address, a changed certificate, an error from the PC. If the PC announced "going to sleep / restarting / shutting down / closing / battery low" shortly before, it says that instead.
3. **Buttons:** *Try again*, *Switch PC* (scan another PC's code; the old one is kept so a failed switch can be undone), and *Wi-Fi settings* where that helps. There is no way to dismiss it.
4. **It closes by itself** when the PC answers (with a success buzz and "Back online"), refreshes everything, and, if the PC was updated meanwhile, reloads the page. A phone the PC has removed or blocked gets the sign-in screen instead, never this popup.
5. **A slow but working connection** gets a small non-blocking banner, not a popup.

**Notifications.** A PC that drops off the network cannot tell the phone afterwards, so the PC says it *first* when it can: before it sleeps, restarts or shuts down (whether the phone asked, or Windows is doing it), when the app is closing, and when its battery is low (at `push.battery_low_percent`, and once more at 5%). Those are the `pc_*` entries in `push.notify_on`. They expire quickly (2 minutes) so one can never arrive after the PC has woken. An *unplanned* loss (Wi-Fi dropped, power cut) shows the popup when the app is open; telling a phone whose app is closed needs the relay to send it, which comes with the relay.

**Haptics** in the app are native (a web view ignores the page's own vibration until the first tap): a long double pulse when the popup appears, a tick on Try again, an error buzz when a retry fails, a success pulse on recovery. All follow *Settings → Haptic feedback*.

**Checking it:** `node tests/js/conn_test.js` (every timing case) and `python tests/e2e/popup_e2e.py` (a real browser against a real server: it stops the PC, checks the popup, brings the PC back).

## Which folders the agent can use

**You don't have to list folders in advance.** Ask for a file anywhere ("read app.log from C:\Logs") and, if that folder isn't set up yet, the chat shows a card: **Allow this folder**, **Just this once**, or **Don't allow**. Nothing is read until you tap. Allowing is **read only**: it can read and search there but never change anything. "Allow this folder" is remembered (in `data/grants.json`) until you take it back under **Settings, Folders you allowed**; "just this once" closes again when the request ends.

Some places can never be opened, whatever you tap, so a stolen phone can't be used to steal secrets: this app's own data (the access token, the https key, the audit log), `.ssh`, `.aws` and other credential folders, browser profiles, the Windows folder, and a whole drive such as `C:\` (name a folder instead). Add your own with `agent.protected_folders`. Changing files is different: it is only ever possible in `allowed_folders`, and asking doesn't change that.

Optional lists in `config.yaml` under `agent:`

- `allowed_folders`: can be read, searched and, with your approval, changed. The first one is where relative paths start.
- `read_only_folders`: always readable without asking, **never** changed, even if you tap Approve. A read-only folder may not sit inside a writable one.
- `ask_for_access`: `true` (the default) asks as described above. `false` is strict mode: only the two lists are ever used, and anything else is refused with the lines to add to `config.yaml`.

Each job card on the phone lists what the AI actually looked at ("Looked at: searched C:\PageLogin for *.bak: 1 found"). Check it before trusting an answer.

Searches skip `node_modules` and `.git` folders (and say so), and stop after 200 matches or 50,000 files.

Only files that a request offered (a file you approved sending, or one a job created) can be downloaded. There is no size limit unless you set `agent.max_download_mb` (0 = none); the approval card shows the size first, and a folder is sent as one zip. To skip the approval tap for downloads, remove `send` from `approval.require_for`.

## Add a local AI model (free, runs on this PC)

1. Install Ollama from https://ollama.com (check that your company allows it).
2. Download a model, about 5 GB: `ollama pull qwen2.5:7b`
3. Restart AccessFromPhone. With `llm.provider: auto` (the default) it uses the model when Ollama has it, and says so on start-up.

### If the AI feels slow

A small model on a laptop without a graphics card reads about 25 to 45 words a second and writes 5 to 8. That, not the app, is the limit, so the app tries not to use the model at all, and to give it less to read and write:

- **Plain requests skip the model**: reading, downloading, "50 lines from it", "last 100 lines of app.log" and `replace "old" with "new" in <file>` are done by the app in under a second. A change still waits for your Approve, and can be undone.
- **Small edits, not rewrites.** When the AI changes a file it sends only the old and new text (`edit_file`), and the app builds the file itself. Retyping a whole file at 6 words a second takes minutes. A very long answer is cut off at `llm.max_output_tokens` and is never applied.
- **Less to read.** Only `llm.file_chars` of a file is shown to the model, the chat memory is short (`llm.memory_turns`), and the instructions are brief.
- **The right threads.** `llm.num_thread: auto` uses all but two CPU cores. On a 12-thread laptop that measured about 60% faster at reading and 50% faster at writing than Ollama's own choice.
- **Folders are asked about first**: if you name a folder that isn't allowed, you are asked at once, before any model starts.
- **Stop** is always available.

For real speed you need more hardware or a bigger service: a PC with a graphics card (a 7B model then answers in seconds), or `llm.provider: anthropic`, which answers in a few seconds whatever your PC is.

To try another model, change `llm.model` in `config.yaml` and pull it first. On a PC with no graphics card, replies take from several seconds to a minute or more.

## The opening animation

Every launch, on the phone page, in the app and in the PC's window, starts with a 5 second opening. For the first three seconds it builds up: a ring draws itself and the dot pops in, the name rises letter by letter, then "Your PC, from your pocket." and "Ask in plain words. You approve every change.", with a thin progress line filling below. For the last two seconds the mark and the name **glow**, twice, like a light breathing. Then the whole screen fades out into the app (Home, or the sign-in screen if you aren't connected yet). The build-up only moves things by position and fade, so it is smooth on any phone. With the phone's "reduce motion" on, or the Reduce motion switch in Settings, it is a brief 1.3 second fade instead, with no glow. To switch it off, set `afp_splash_off` to `1` in the page's storage (the browser tests do).

**Checking it:** `python tests/e2e/splash_e2e.py` (timing, the glow only in the last two seconds, hand-over to Home, the off switch, reduced motion, and the PC's window).

## Home and the tab bar

The page opens on **Home**, a control center for the PC, and the chat is one tab among four. On a phone a bar at the bottom switches between **Home**, **Chat**, **Files** (the file browser) and **PC** (the live status). The bar is on every screen size, so a wide window uses it too.

**Home shows** (kept short, so it fits a phone screen without scrolling much)
- **The PC's state:** its name and whether it is online and its battery at the top, then a card that says **Locked** or **Unlocked**, with processor, memory and disk free.
- **The one thing you are likely to want:** a big **Unlock** button when the PC is locked and unlocking is set up (it opens the chat with the approval and the PIN box), otherwise **Lock**, with **Sleep** beside it. Only the power actions that `power.remote_actions` allows are offered.
- **What needs you:** an amber banner "1 request needs you" when a request is waiting for your approval, which takes you straight to it. The Chat tab also shows how many are waiting.
- **A first-run checklist ("Get set up, 2 of 4 done"):** connect your phone, allow a folder, turn on notifications, set up unlocking. Each unfinished step has a button; "Hide this" removes the card for good, and it goes by itself once everything is done.
- **Recent:** the last three requests with their state; tap one to open that chat.
- If the PC cannot be reached and saved chats exist, Home says so and offers to read them; nothing on it can be sent until the PC is back.

Files, Pictures, Battery and the rest are one tap away in the tab bar, or by asking in the chat.

**In the chat**, suggestion chips sit above the message box ("Unlock my PC" when the PC is locked, otherwise "Lock my PC"; "Open my folders", "Battery", "My pictures"). Tapping one asks it at once. They hide while you type.

The screen you were on is remembered. The app's built-in saved-chats page always starts in the chat.

**Checking it:** `pytest tests/test_home.py` and `python tests/e2e/home_e2e.py` (a real browser against a real PC app and a stand-in unlock helper: Home, the Unlock button, the request banner, the chips, the Files and PC tabs, the checklist, and the Lock button once the PC is unlocked). Mock-ups of the design are in `docs/ui-mockups/`.

## Settings

**Settings** (the sliders button on Home) is a short list of modules, each with its own small page, so nothing is buried in one long scroll:

- **Profile and phone:** the name shown on this phone, this phone's name on the PC, and Sign out.
- **Notifications:** turn them on or off.
- **Look and feel:** theme, accent colour, text size, reduce motion, haptic feedback and dial ticks.
- **Voice and input:** speaking language, microphone, how input starts, the voice button, sending when you stop talking, reading replies aloud and their speed.
- **Chats and privacy:** audit trails open, keep recent chats on this phone, clear saved chats, the activity log, and bring back removed chats.
- **This PC:** what the PC is set to do (read only: changed in config.yaml on the PC).
- **About:** the tour, version, secure link, and Reset settings.

The look is deliberately plain: flat colour, thin borders, no glows.

## The phone page

It is a chat, like the AI apps you know, and it works on a phone, a tablet and a desktop browser.

- **Chats.** Every conversation is saved on the PC in `data/audit.log`, so your chat list is still there after a restart. Use **New chat** to start fresh (the AI only remembers the chat it is in). Rename or remove a chat from its ⋯ menu. Removing only hides it on that phone; the PC's record is kept.
- **Stop.** While the AI is thinking or a command is running, the send button turns into a red stop button (and there is a **Stop** button under "Thinking…"). Pressing it kills a running command and its child processes, or hangs up on the model so a local model stops working at once. The job shows as **Stopped**; if it had already changed files, **Undo** is still offered. If the model is just slow, the reply falls back to showing the file the app already read.
- **Audit trail.** Under every reply, tap **Audit trail** to see each step the PC took, with times. **Settings, then Activity log** lists everything, can be filtered, and exports as JSON.
- **Settings** (tap your name, bottom left, or the avatar on a phone): theme (dark, light, system), accent colour, text size, reduce motion, voice options, haptics, and a read-only view of what this PC may do (AI, folders, commands, approvals). Those PC settings are changed in `config.yaml`, never from the phone.
- **Add to home screen** in your browser menu to open it like an app, full screen.
- On a computer: Enter sends, Shift+Enter adds a line, `/` jumps to the message box, Alt+N starts a new chat.

### Editing a file by hand

Say **"I want to edit that file"** (or "let me edit app.cfg in C:\Folder", or tap **Edit this file** under any file you read) and the file opens in a full-screen editor on the phone. Change it yourself and **Save**, or tap **Ask AI** and say what to change.

- **Find and replace**, wrap long lines, bigger or smaller text. The line count and size show at the top.
- **Review** shows exactly which lines you changed (red out, green in) before you save.
- **Save** is your approval. The file keeps its own line endings (Windows `\r\n` stays `\r\n`) and encoding, and only the lines you changed differ. The save appears in the chat as "Edited X by hand" with **Undo**, and goes in the audit trail.
- **If the file changed on the PC while you had it open**, saving stops and asks: save mine anyway, reload what's on the PC, or cancel. Nothing is overwritten by accident. Closing with unsaved changes asks first.
- **Folders:** in `allowed_folders` you can edit straight away. In any other folder the editor first asks **"Allow editing in this folder?"** (one tap; listed under Settings with a **Can edit** badge; **Remove** takes it back). It will never allow editing inside a `read_only_folders` entry, the app's own data, or credential folders. Turn the whole thing off with `agent.allow_edit_grants: false`.
- **Text files only**, up to `agent.max_edit_kb` (512 KB). Binary or non-UTF-8 files open as "can't edit", with the reason.
- **AI edits** show what they will do (old text in red, new text in green) on the approval card. The AI sends only the old and new text, never a whole retyped file.

### Opening a file full screen

Say **"open it full screen"**, **"open config.json in a new screen"**, or tap **Open full screen** under any file you read. The file opens in its own panel, like the canvas in Claude or ChatGPT: beside the chat on a wide screen, over the whole page on a phone (Back closes it).

- **View and Edit** are one switch at the top. Unsaved changes carry across; the panel asks before you close with edits pending.
- **Colours and line numbers** for code, config, XML, JSON, logs and more. **Markdown** shows as a formatted page, **CSV** as a table, **JSON** has a Format button. Images and PDFs display in the panel. Anything else offers **Download**.
- **Find** with highlighted matches, wrap, text size, copy, download, **Open in a new tab**, and a full-screen toggle.
- Big files load in pages as you scroll (view limit `agent.max_view_kb`, 4096 KB). Editing keeps its own limit, `agent.max_edit_kb`.
- If the AI changes the open file, the panel reloads it by itself.

### Signing in by scanning

On the sign-in screen, tap **Scan the QR code on your PC**, point the camera at the QR code printed in the PC's terminal, and you're in: the orb flares, a tick draws itself, and the screen opens onto your chat. (Opening the link with your phone's own camera app still works too.) You can also paste the access token. A wrong code shakes the screen and says why. If the PC's address changed since you last connected, scanning takes you to the new address.

The camera, like the microphone, needs the https link. QR reading uses your browser's built-in detector where there is one (Chrome on Android) and the bundled jsQR library everywhere else (Apache-2.0 licence, in `web/vendor/`). Nothing is sent anywhere: the picture never leaves the phone.

### Voice

Press and hold the big button, speak, and release. Slide left before releasing to cancel. **Use tap controls** switches to tap-to-start, tap-to-stop. Choose your speaking language in Settings (Hindi, Urdu, Kannada, Tamil, Telugu, Malayalam and more). Replies can be read aloud after a voice question, or always, or never.

Voice needs two things:

1. **A secure link.** Browsers only allow the microphone on https. `server.https: true` (the default in `config.yaml`) serves the page over https with a certificate the app makes for itself. Your phone shows a warning once because nobody it knows signed it: choose **Advanced, then Continue**. If you change the IP address in `public_url`, a new certificate is made on the next start.
2. **Your browser's speech service.** Chrome (Android) and Safari (iPhone) turn your voice into text on their makers' servers, so the audio goes to Google or Apple. Your PC's AI only receives the text. If that is not acceptable for your company, use the keyboard.

If voice isn't available the mic button explains why and offers the keyboard. The microphone key on your phone's own keyboard also works in the message box.

### Haptics

Taps, approvals, results, cancelling a voice message and errors each give a small, different buzz. Android browsers support this. iPhone browsers don't allow websites to vibrate, so there is nothing to feel there. Turn it off in Settings.

## Choose the AI: private on this PC, or hosted

`llm.provider` in `config.yaml`:

| Value | What it does | Where your text goes |
|---|---|---|
| `auto` (default) | Local model if Ollama has it, else the demo commands | Stays on this PC |
| `ollama` | Always the local model | Stays on this PC |
| `anthropic` | A hosted Claude model (`llm.hosted_model`). Far more capable | **Requests and any file text it reads are sent to the provider** |
| `demo` | Typed commands only, no AI | Stays on this PC |

`auto` never picks the hosted model, so nothing leaves the PC unless you choose `anthropic`.
For `anthropic`, put your key in an environment variable (name set by `llm.api_key_env`, default `ANTHROPIC_API_KEY`), never in the config file. The start-up message says which AI is active.

The AI is reminded of your last `llm.memory_turns` requests, so "now delete that one" works. Memory is kept until the server restarts.

## Letting the AI run commands

Off by default. Set `commands.enabled: true` and the AI may *propose* a command (PowerShell). Then:

- You always see the exact command and must tap **Approve**. This cannot be switched off.
- It runs only inside a writable folder, stops after `commands.timeout_seconds`, and secrets in the environment (names containing KEY, TOKEN, SECRET, PASSWORD) are hidden from it.
- A built-in block list (`commands.deny`) refuses things like `format`, `shutdown`, `iex`, registry edits and SSH keys. Treat it as a safety net, not a guarantee.
- To allow only specific commands, set `commands.allow_only: ["git status", "npm test"]`. Chaining (`;`, `&`, `|`) is then refused.
- Commands cannot be undone, and the AI does not see their output, so it proposes everything it needs at once.

## Configure it

Everything is in `config.yaml`. To change the Wi-Fi address, edit `server.public_url` and restart. Any value can also be set for one run with an environment variable, for example `HANDOFF_SERVER__PORT=9000`.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

## Limits of this version

- **Files are read by the app, not guessed by the AI.** "Read X in `C:\folder`" and "download X from `C:\folder`" are handled directly, with no AI, so they are instant and always show the real file. For "summarise X" or "is X there?", the app reads the file (or lists the folder) first and gives the AI the real text. If you don't repeat the folder, the last folder you named in the same chat is used. Typos are forgiven: `actionClient.ts` finds `actionsClient.ts`, `askcore` finds `AskCore.tsx`, capitals and a wrong or missing extension don't matter. The reply says what it corrected ("you typed …"). "Read 50 lines from it", "the first 20 lines of X" and "the last 100 lines of app.log" (the newest lines of a log) are answered directly too, and "it" means the file the chat was last about. A big log is streamed, so it costs no memory. If two files are equally close it asks which one you meant, and if nothing is close it says the file isn't there instead of guessing. If the AI still answers a file question without looking, the reply says so. Check the "Looked at" lines under a reply: they show what was really read.
- Small local models make mistakes. Read each plan before you approve it. In testing, the 3B model once answered "no .bak files" after searching the wrong folder; the search tool now requires a folder and names it in every result, but check the "Looked at" line.
- Reading files runs at once (inside the allowed and read-only folders), so a file's text can reach the model. With `provider: anthropic` that means it leaves this PC. Changes, downloads, moves, copies and commands still need your approval.
- Plain HTTP on your local network. Do not use it on public Wi-Fi.
- Jobs are kept in memory and are forgotten when the server restarts. The audit log in `data/audit.log` is kept.
- The PC must be on and awake.
- If the phone cannot open the link, Windows Firewall may be blocking port 8765. See the firewall note in the chat history, or allow it with an administrator PowerShell:
  `New-NetFirewallRule -DisplayName "AccessFromPhone 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Public,Private -RemoteAddress LocalSubnet`


## Opening apps, and Teams

Ask in plain words. Each one is a plan you approve on the phone first (opening an app can be set to skip the question: `apps.approve_open: false`).

| Say | What happens |
|---|---|
| `open Teams`, `open Excel`, `launch Chrome` | The app is found by name in this PC's Start menu and started, the way the Start menu starts it. Only Start-menu apps; never a typed command. |
| `show my unread Teams messages` | Teams comes forward on the PC, the unread chats are opened and the last few messages in each are sent to your phone. Opening a chat marks it as read in Teams. |
| `what did Vinod say on Teams` | The latest messages in that chat. |
| `reply to Vinod: I'm coming` | Your words are typed into Teams exactly as written, and sent. The approval card shows the person and the message first. |
| `reply: I'm coming` (straight after reading a chat) | The same, to the person you were just reading. |

How Teams is driven: through Windows' own accessibility interface, the way a screen reader does. There is no Microsoft sign-in and nothing is sent anywhere: no AI model is shown a message. A reply is only sent if Teams is in front, the right chat is open, the message box was empty, and what Teams shows in the box matches what was typed. Otherwise it stops, clears the box and tells you why.

Limits: the PC must be unlocked (say `unlock my PC` first), Teams uses the PC's keyboard for a few seconds, and a Teams update can change its window. `python -m handoff.appctl teams-look` prints what the helper sees, to check or fix that. To switch these off: `apps.enabled: false` (open apps) and `apps.teams: false` (Teams) in `config.yaml`. Your company may have rules about automating Teams: check them.
