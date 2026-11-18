# Mega Turrican Windows port

This repository uses GitHub-hosted Windows runners to build a downloadable Windows x64 package. Standard GitHub-hosted runners are free for public repositories.

## Private source, public Windows download

The build-kit source is stored as an encrypted ZIP. The decryption key is stored in the repository's Actions secrets as `MEGATURRICAN_SOURCE_KEY`; do not commit that key.

The source bundle is decrypted only on the Windows runner, compiled, and packaged. The finished Windows ZIP is uploaded as a normal Actions artifact and published as a GitHub prerelease asset so it can be downloaded directly from the **Releases** page without needing a separate decryption step.

Do not upload your ROM. The launcher reads a ROM you select locally; the ROM is not embedded in the build or uploaded.

## Run the build

1. Open the repository's **Actions** tab.
2. Select **Build Mega Turrican for Windows**.
3. Click **Run workflow** on `main`.
4. When the run completes, open the repository's **Releases** page and download `MegaTurrican-Windows-x64.zip`. You can also download the `MegaTurrican-Windows-x64` artifact from the workflow run.

Extract the ZIP, run the portable `MegaTurricanLauncher` executable, and select your own Mega Drive ROM.

## Security notes

- The source ZIP remains encrypted in the public repository; the key is an Actions secret.
- Repository secrets are not passed to workflows triggered by pull requests from forks.
- Anyone who can read the public repository can download the finished Windows executable from Releases. The compiled output is intentionally published for easy use.
- Anyone who gets both the encrypted source package and the key can decrypt the source. Treat the key like a password.
- Keep write access limited to trusted collaborators, since anyone who can change workflows could alter what the build does.

## Controller controls

The Windows launcher has a live three-button Mega Drive pad preview. It reads controller input through the standard Gamepad API, lets you select a connected pad, and provides per-action dropdowns for Up, Down, Left, Right, A, B, C, and Start. The selected mappings are saved in the launcher and written to the native SDL controller configuration when the game starts.

Default DualSense profile: D-pad for directions, Square = Genesis A, Cross = Genesis B, Circle = Genesis C, Options = Start. Left-stick directions are also available in the dropdowns. The native game core consumes the saved mapping rather than a separate hard-coded layout.

## Build inputs

The encrypted source bundle contains the generated C game code, C runtime, SDL2 SDK files, launcher, and build scripts. The workflow installs MinGW-w64, SDL2, and Node.js on a Windows runner; compiles the native game core; packages the Electron launcher; checks that both executable files are present; and publishes the ready-to-run ZIP.

Use only a ROM copy you are entitled to use.
