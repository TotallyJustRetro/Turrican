# Mega Turrican Windows port

This repository has a GitHub Actions workflow prepared to build the Windows x64 package.

> **Important: this repository currently appears to be public. Do not upload the source bundle or run the build until you change the repository visibility to Private.** The generated static-recompilation source and build output are game-derived. Public repository contents and Actions artifacts can be downloaded by others.

## One-time setup

1. Open **Settings → General → Danger Zone → Change repository visibility** and set this repository to **Private**.
2. Download **MegaTurrican_Windows_Build_Kit.zip** from the ChatGPT conversation.
3. Upload that ZIP to the repository root using **Add file → Upload files**. Keep the exact filename.
4. The upload to `main` automatically starts the Windows build.

Do not upload your ROM. The launcher is designed to load a ROM that you select locally; it is not embedded in the build or uploaded by the launcher.

## Get the Windows build

1. Open the repository's **Actions** tab.
2. Select **Build Mega Turrican for Windows**.
3. Open the newest successful run.
4. Download the `MegaTurrican-Windows-x64` artifact and extract it.
5. Run the portable `MegaTurricanLauncher` executable and select your own Mega Drive ROM.

## Build contents

The source bundle contains the generated C game code, C runtime, SDL2 SDK files, launcher, and build scripts. GitHub Actions installs the Windows compiler and SDL2, compiles the native core, bundles its DLL dependencies, packages the Electron launcher, and uploads a ready-to-extract ZIP artifact.

## Privacy / legal

Keep this repository and any generated game-derived source/build artifacts private. Use only a ROM copy you are entitled to use.
