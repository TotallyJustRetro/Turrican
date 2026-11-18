# Mega Turrican Windows port

This private repository is prepared to build the Mega Turrican Windows x64 package with GitHub Actions.

## Add the source bundle (one-time step)

The source bundle is not committed yet. Download **MegaTurrican_Windows_Build_Kit.zip** from the ChatGPT conversation and upload that ZIP to the repository root using **Add file → Upload files**:

- Expected filename: `MegaTurrican_Windows_Build_Kit.zip`
- Keep the repository private. The generated game-derived source and build outputs should not be published.
- Do not upload your ROM. The launcher accepts a ROM you select locally; the ROM stays on your PC.

Uploading the ZIP to `main` automatically starts the workflow.

## Get the Windows build

1. Open the repository's **Actions** tab.
2. Select **Build Mega Turrican for Windows**.
3. Open the newest successful run.
4. Download the `MegaTurrican-Windows-x64` artifact and extract it.
5. Run the portable `MegaTurricanLauncher` executable and select your own Mega Drive ROM.

The native game core can also be launched directly with a ROM path and `config.ini`.

## Build contents

The source bundle contains the generated C game code, runtime, SDL2 SDK files, launcher, and build scripts. GitHub Actions installs the Windows compiler and SDL2 dependency, compiles the native core, bundles its required DLLs, packages the Electron launcher, and uploads a ready-to-extract ZIP artifact.

## Privacy / legal

This is a private build workspace. Keep this repository and its generated game-derived source/build artifacts private. Use only a ROM copy you are entitled to use.
