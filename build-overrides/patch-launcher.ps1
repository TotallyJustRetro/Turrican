param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
$launcher = Join-Path $ProjectRoot 'launcher'
$preloadPath = Join-Path $launcher 'preload.js'
$mainPath = Join-Path $launcher 'main.js'
$htmlPath = Join-Path $launcher 'index.html'

if (-not (Test-Path $preloadPath) -or -not (Test-Path $mainPath) -or -not (Test-Path $htmlPath)) {
    throw "Launcher files are missing under $launcher"
}

# Electron's sandboxed preload does not provide the full Node global surface.
# Pass a structured-clone-safe Uint8Array through IPC instead of calling Buffer
# from preload. The main process converts it to a Buffer before writing the ROM.
$preload = @'
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('GenesisCore', {
  run: (rom, settings) => {
    let bytes;
    if (rom instanceof Uint8Array) {
      bytes = new Uint8Array(rom);
    } else if (rom instanceof ArrayBuffer) {
      bytes = new Uint8Array(rom);
    } else if (ArrayBuffer.isView(rom)) {
      bytes = new Uint8Array(rom.buffer, rom.byteOffset, rom.byteLength);
    } else if (Array.isArray(rom)) {
      bytes = Uint8Array.from(rom);
    } else {
      throw new TypeError('The selected ROM data could not be transferred to the game core.');
    }
    return ipcRenderer.invoke('md-launch', bytes, settings || {});
  }
});
'@
Set-Content -LiteralPath $preloadPath -Value $preload -Encoding utf8

# Normalize the data received over Electron IPC in the main process.
$main = Get-Content -LiteralPath $mainPath -Raw
$oldGuard = "  if (!rom || !rom.byteLength) return { ok: false, error: 'Load a Mega Drive ROM first.' };"
$newGuard = @'
  const romBytes = Buffer.isBuffer(rom)
    ? rom
    : rom instanceof ArrayBuffer
      ? Buffer.from(rom)
      : ArrayBuffer.isView(rom)
        ? Buffer.from(rom.buffer, rom.byteOffset, rom.byteLength)
        : Array.isArray(rom)
          ? Buffer.from(rom)
          : null;
  if (!romBytes || romBytes.length <= 0x200) {
    return { ok: false, error: 'The selected ROM data did not reach the game core correctly. Reload the ROM and try again.' };
  }
'@
if (-not $main.Contains($oldGuard)) {
    throw 'Could not locate the expected ROM validation code in launcher/main.js.'
}
$main = $main.Replace($oldGuard, $newGuard.TrimEnd())
$oldWrite = '  fs.writeFileSync(romPath, Buffer.from(rom));'
$newWrite = '  fs.writeFileSync(romPath, romBytes);'
if (-not $main.Contains($oldWrite)) {
    throw 'Could not locate the expected ROM file write code in launcher/main.js.'
}
$main = $main.Replace($oldWrite, $newWrite)
Set-Content -LiteralPath $mainPath -Value $main -Encoding utf8

# Add a visible status line and catch errors thrown by the preload/IPC bridge.
$html = Get-Content -LiteralPath $htmlPath -Raw
$oldButton = @'
 <button class="b" id="launch">▶ LAUNCH MEGA TURRICAN</button>
'@
$newButton = @'
 <button class="b" id="launch">▶ LAUNCH MEGA TURRICAN</button>
 <p class="mut" id="launchStatus" role="status" aria-live="polite">Load a ROM to enable launching.</p>
'@
if (-not $html.Contains($oldButton)) {
    throw 'Could not locate the Play button in launcher/index.html.'
}
$html = $html.Replace($oldButton, $newButton)
$oldHandler = @'
$("launch").onclick=async()=>{
 if(!window.GenesisCore){alert("Open the packaged Windows launcher to start the native game core.");return}
 if(!rom){alert("Load a Mega Drive ROM first.");return}
 const result=await window.GenesisCore.run(rom,S);
 if(!result?.ok) alert(result?.error||"Mega Turrican could not be started.");
};
'@
$newHandler = @'
$("launch").onclick=async()=>{
 const button=$("launch"),status=$("launchStatus");
 if(!window.GenesisCore){
  const message="The native launcher bridge did not load. Close the launcher and reinstall/extract the complete Windows package.";
  status.textContent=message;alert(message);return;
 }
 if(!rom){status.textContent="Load a Mega Drive ROM first.";alert("Load a Mega Drive ROM first.");return}
 button.disabled=true;button.textContent="STARTING MEGA TURRICAN…";status.textContent="Preparing ROM and starting the native game…";
 try{
  const result=await window.GenesisCore.run(rom,S);
  if(!result?.ok)throw new Error(result?.error||"Mega Turrican could not be started.");
  status.textContent="Game launched in its own window.";
 }catch(error){
  const message=error?.message||String(error);
  status.textContent="Launch failed: "+message;
  alert("Mega Turrican could not be started.\n\n"+message);
 }finally{
  button.disabled=false;button.textContent="▶ LAUNCH MEGA TURRICAN";
 }
};
'@
if (-not $html.Contains($oldHandler)) {
    throw 'Could not locate the expected Play button handler in launcher/index.html.'
}
$html = $html.Replace($oldHandler, $newHandler)
Set-Content -LiteralPath $htmlPath -Value $html -Encoding utf8

Write-Host 'Applied sandbox-safe ROM IPC and visible Play-button error handling.'
