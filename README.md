# Mega Turrican Windows port

The Windows x64 build uses GitHub-hosted Windows runners. Standard GitHub-hosted runners are free for public repositories, so this repository can remain public without consuming private-repository Actions minutes.

## Keep the source private while using public runners

The repository intentionally stores only an encrypted copy of the source build kit. The decryption key is a GitHub Actions repository secret; do not commit it to the repository.

### One-time setup

1. Open Settings → Secrets and variables → Actions → New repository secret.
2. Set the secret name to MEGATURRICAN_SOURCE_KEY.
3. Paste the decryption key provided separately in the setup instructions. Do not put it in a file or commit it.
4. Upload MegaTurrican_Windows_Build_Kit.zip.enc to the repository root. The encrypted file does not contain readable source without the secret.

Do not upload your ROM. The launcher reads a ROM you select locally; the ROM is not embedded in the build or uploaded.

### Run the Windows build

1. Open the repository's Actions tab.
2. Select Build Mega Turrican for Windows.
3. Click Run workflow on main.
4. When the run completes, download the MegaTurrican-Windows-x64-encrypted artifact and extract the downloaded artifact ZIP. It contains MegaTurrican-Windows-x64.zip.enc.
5. Download Decrypt-MegaTurrican-Build.ps1 from this repository and place it beside the encrypted package.
6. Run PowerShell: powershell -ExecutionPolicy Bypass -File .\Decrypt-MegaTurrican-Build.ps1
7. Enter the same key stored as MEGATURRICAN_SOURCE_KEY. The script creates MegaTurrican-Windows-x64.zip. Extract it, run the portable launcher, and select your own ROM.

The final artifact is encrypted because anyone with read access to a public repository can download its Actions artifacts. The artifact expires after three days.

## Security notes

- Repository secrets are not passed to workflows triggered by pull requests from forks.
- Only run workflows from code you trust. Anyone with write access to this repository can change workflows; keep write access limited to trusted collaborators.
- Do not print the secret, place it in command-line source files, or commit it.
- Anyone who gets both the encrypted source package and the key can decrypt the source. Treat the key like a password.

## Build inputs

The encrypted source bundle contains the generated C game code, C runtime, SDL2 SDK files, launcher, and build scripts. The workflow installs MinGW-w64, SDL2, and Node.js on a Windows runner; compiles the native game core; packages the Electron launcher; and encrypts the resulting portable Windows ZIP.

Use only a ROM copy you are entitled to use.
