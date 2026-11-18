param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $ProjectRoot 'launcher'
$preloadPath = Join-Path $launcher 'preload.js'
$mainPath = Join-Path $launcher 'main.js'
$htmlPath = Join-Path $launcher 'index.html'
$harnessPath = Join-Path $ProjectRoot 'runtime/harness.c'
$readmePath = Join-Path $ProjectRoot 'README.txt'
foreach ($path in @($preloadPath, $mainPath, $htmlPath, $harnessPath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required source file is missing: $path" }
}

$preload = @'
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('GenesisCore', {
  run: (rom, settings) => {
    let bytes;
    if (rom instanceof Uint8Array) bytes = new Uint8Array(rom);
    else if (rom instanceof ArrayBuffer) bytes = new Uint8Array(rom);
    else if (ArrayBuffer.isView(rom)) bytes = new Uint8Array(rom.buffer, rom.byteOffset, rom.byteLength);
    else if (Array.isArray(rom)) bytes = Uint8Array.from(rom);
    else throw new TypeError('The selected ROM data could not be transferred to the game core.');
    return ipcRenderer.invoke('md-launch', bytes, settings || {});
  }
});
'@
Set-Content -LiteralPath $preloadPath -Value $preload -Encoding utf8

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
    return { ok: false, error: 'The selected file is too small to be a Mega Drive ROM.' };
  }
  if (romBytes[0] === 0x4d && romBytes[1] === 0x5a) {
    return { ok: false, error: 'That is a Windows executable, not a Mega Drive ROM. Select Mega_Turrican__USA_.md instead.' };
  }
  if (romBytes.length > 0x400000) {
    return { ok: false, error: 'This native core supports Mega Drive ROMs up to 4 MiB.' };
  }
  const romSystem = romBytes.subarray(0x100, 0x110).toString('ascii').replace(/\0/g, ' ').trim();
  if (!/^SEGA\s+(GENESIS|MEGA DRIVE)/i.test(romSystem)) {
    return { ok: false, error: 'This file does not contain a valid Sega Mega Drive header. Select a .md, .bin, .gen or .smd ROM.' };
  }
  const resetPc = romBytes.readUInt32BE(4);
  if (resetPc < 0x200 || resetPc >= romBytes.length) {
    return { ok: false, error: 'The ROM reset vector is invalid or points outside the ROM image.' };
  }
'@
if (-not $main.Contains($oldGuard)) { throw 'Could not locate ROM validation in launcher/main.js.' }
$main = $main.Replace($oldGuard, $newGuard.TrimEnd())
$oldWrite = '  fs.writeFileSync(romPath, Buffer.from(rom));'
if (-not $main.Contains($oldWrite)) { throw 'Could not locate ROM temporary-file write in launcher/main.js.' }
$main = $main.Replace($oldWrite, '  fs.writeFileSync(romPath, romBytes);')

$spawnStart = $main.IndexOf('  return await new Promise(resolve => {')
if ($spawnStart -lt 0) { throw 'Could not locate native process launch block in launcher/main.js.' }
$spawnClose = [regex]::Match($main.Substring($spawnStart), '(?m)^  \}\);')
if (-not $spawnClose.Success) { throw 'Could not locate end of native process launch block.' }
$newSpawn = @'
  return await new Promise(resolve => {
    let settled = false;
    let startupTimer = null;
    const finish = result => {
      if (settled) return;
      settled = true;
      if (startupTimer) clearTimeout(startupTimer);
      resolve(result);
    };
    const child = spawn(exe, [romPath, configPath], {
      detached: true,
      stdio: 'ignore',
      cwd: path.dirname(exe),
      windowsHide: false
    });
    child.once('error', error => finish({ ok: false, error: 'Could not start Mega Turrican: ' + error.message }));
    child.once('exit', (code, signal) => {
      const details = 'Mega Turrican exited during startup (code ' +
        (code === null ? 'unknown' : code) + (signal ? ', ' + signal : '') +
        '). The ROM may be invalid or the native runtime may be missing.';
      finish({ ok: false, error: details });
    });
    child.once('spawn', () => {
      startupTimer = setTimeout(() => {
        child.unref();
        finish({ ok: true });
      }, 1500);
    });
  });
'@
$spawnEnd = $spawnStart + $spawnClose.Index + $spawnClose.Length
$main = $main.Substring(0, $spawnStart) + $newSpawn.TrimEnd() + $main.Substring($spawnEnd)
Set-Content -LiteralPath $mainPath -Value $main -Encoding utf8

$html = Get-Content -LiteralPath $htmlPath -Raw
$button = ' <button class="b" id="launch">▶ LAUNCH MEGA TURRICAN</button>'
if (-not $html.Contains($button)) { throw 'Could not locate Play button in launcher/index.html.' }
$statusLine = ' <p class="mut" id="launchStatus" role="status" aria-live="polite">Choose a valid Mega Drive ROM to enable Play.</p>'
$html = $html.Replace($button, $button + [Environment]::NewLine + $statusLine)
$html = $html.Replace('<h3>Screen preview</h3>', '<h3>ROM tile data (raw)</h3>')
$html = $html.Replace('the preview shows ROM tile data while the game runs in its own window.', 'the side panel shows raw ROM tile bytes, not a live gameplay capture. The game opens in its own window.')
$romStart = $html.IndexOf('/* ROM */')
$tileStart = $html.IndexOf('/* tile decode */', $romStart)
if ($romStart -lt 0 -or $tileStart -lt 0) { throw 'Could not locate ROM loading section in launcher/index.html.' }
$romBlock = @'
/* ROM */
const hex=n=>n.toString(16).toUpperCase();
function headerText(bytes,start,length){
 let out="";
 for(let i=start;i<start+length;i++){const b=bytes[i];out+=(b>=0x20&&b<=0x7e)?String.fromCharCode(b):" ";}
 return out.replace(/\s+/g," ").trim();
}
function rejectROM(message){
 orig=null;rom=null;romName="game.md";
 $("hdr").replaceChildren();
 const b=document.createElement("b"),s=document.createElement("span");
 b.textContent="ROM status";s.textContent=message;$("hdr").append(b,s);
 $("launch").disabled=true;$("launchStatus").textContent=message;
 $("hackLog").textContent=message;
 const c=$("cv").getContext("2d");c.fillStyle="#000";c.fillRect(0,0,320,224);
}
function load(buf,name){
 const source=new Uint8Array(buf);
 if(source.length>=2&&source[0]===0x4d&&source[1]===0x5a){
  rejectROM("This is a Windows .exe, not a Mega Drive ROM. Select Mega_Turrican__USA_.md instead.");return;
 }
 if(source.length<=0x200){rejectROM("This file is too small to be a Mega Drive ROM.");return;}
 if(source.length>0x400000){rejectROM("This file is larger than the native core's 4 MiB ROM limit.");return;}
 let candidate=source.slice();
 if(source.length>512&&source.length%16384===512&&source[8]===0xaa&&source[9]===0xbb){
  const out=new Uint8Array(source.length-512),blocks=(source.length-512)/16384;
  for(let block=0;block<blocks;block++){
   for(let i=0;i<8192;i++){
    out[block*16384+i*2+1]=source[512+block*16384+i];
    out[block*16384+i*2]=source[512+block*16384+8192+i];
   }
  }
  candidate=out;
 }
 const system=headerText(candidate,0x100,16);
 if(!/^SEGA\s+(GENESIS|MEGA DRIVE)/i.test(system)){
  rejectROM("No Sega Mega Drive header was found at 0x100. Choose the actual .md/.bin/.gen/.smd ROM, not the launcher or game .exe.");return;
 }
 const view=new DataView(candidate.buffer,candidate.byteOffset,candidate.byteLength);
 const resetPc=view.getUint32(4,false);
 if(resetPc<0x200||resetPc>=candidate.length){
  rejectROM("The Mega Drive reset vector is invalid. This file is not a usable ROM image.");return;
 }
 orig=candidate.slice();rom=candidate.slice();romName=name;
 const sum=(()=>{let s=0;for(let i=0x200;i+1<rom.length;i+=2)s=(s+(rom[i]<<8|rom[i+1]))&0xffff;return s})();
 const checksum=rom[0x18e]<<8|rom[0x18f];
 const fields=[
  ["System",headerText(rom,0x100,16)],
  ["Copyright",headerText(rom,0x110,16)],
  ["Title",headerText(rom,0x120,48)],
  ["Region",headerText(rom,0x1f0,3)],
  ["Size",(rom.length/1024).toFixed(1)+" KB"],
  ["Checksum",hex(checksum)+(checksum===sum?" ✔":" (calc "+hex(sum)+")")]
 ];
 $("hdr").replaceChildren();
 for(const [label,value] of fields){const b=document.createElement("b"),s=document.createElement("span");b.textContent=label;s.textContent=value;$("hdr").append(b,s);}
 $("launch").disabled=false;
 $("launchStatus").textContent="Valid Mega Drive ROM: "+name+" ("+(rom.length/1024).toFixed(1)+" KB). Ready to launch.";
 $("hackLog").textContent="ROM validated. No patches applied.";
 drawPreview();drawAll();
}
const pick=()=>$("romIn").click();$("drop").onclick=pick;
$("romIn").onchange=e=>{const f=e.target.files[0];if(f)f.arrayBuffer().then(b=>load(b,f.name)).catch(err=>rejectROM("Could not read that file: "+err.message));};
$("drop").ondragover=e=>{e.preventDefault();};
$("drop").ondrop=e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f)f.arrayBuffer().then(b=>load(b,f.name)).catch(err=>rejectROM("Could not read that file: "+err.message));};
$("launch").disabled=true;
$("launch").onclick=async()=>{
 const button=$("launch"),status=$("launchStatus");
 if(!window.GenesisCore){const message="The native launcher bridge did not load. Extract the complete Windows package and reopen it.";status.textContent=message;alert(message);return;}
 if(!rom){const message="Load a valid Mega Drive ROM first.";status.textContent=message;alert(message);return;}
 button.disabled=true;button.textContent="STARTING MEGA TURRICAN…";status.textContent="Checking ROM and starting the native game…";
 try{
  const result=await window.GenesisCore.run(rom,S);
  if(!result?.ok)throw new Error(result?.error||"Mega Turrican could not be started.");
  status.textContent="Mega Turrican process started. Check its game window.";
 }catch(error){
  const message=error?.message||String(error);status.textContent="Launch failed: "+message;
  alert("Mega Turrican could not be started.\n\n"+message);
 }finally{button.disabled=false;button.textContent="▶ LAUNCH MEGA TURRICAN";}
};
'@
$html = $html.Substring(0,$romStart) + $romBlock + [Environment]::NewLine + $html.Substring($tileStart)
Set-Content -LiteralPath $htmlPath -Value $html -Encoding utf8

$harness = Get-Content -LiteralPath $harnessPath -Raw
$windowsFrameLimit = 'static long frame = 0, max_frames = 0x7fffffffffffffffL;'
if (-not $harness.Contains($windowsFrameLimit)) {
  throw 'Could not locate the SDL frame-limit constant in runtime/harness.c.'
}
$harness = $harness.Replace($windowsFrameLimit, 'static long frame = 0, max_frames = 0x7fffffffL;')
Set-Content -LiteralPath $harnessPath -Value $harness -Encoding utf8
$oldLoader = 'int md_load_rom(const char *p){ FILE *f = fopen(p, "rb"); if(!f) return 0; rom = malloc(0x400000); romlen = fread(rom, 1, 0x400000, f); fclose(f); return romlen > 0x200; }'
$newLoader = @'
int md_load_rom(const char *p){
  FILE *f = fopen(p, "rb");
  if(!f) return 0;
  rom = malloc(0x400000);
  if(!rom){ fclose(f); return 0; }
  romlen = fread(rom, 1, 0x400000, f);
  fclose(f);
  if(romlen <= 0x200 || memcmp(rom + 0x100, "SEGA", 4) != 0){
    free(rom); rom = NULL; romlen = 0; return 0;
  }
  uint32_t reset_pc = ((uint32_t)rom[4] << 24) | ((uint32_t)rom[5] << 16) |
                      ((uint32_t)rom[6] << 8) | (uint32_t)rom[7];
  if(reset_pc < 0x200 || reset_pc >= romlen){
    free(rom); rom = NULL; romlen = 0; return 0;
  }
  return 1;
}
'@
if (-not $harness.Contains($oldLoader)) { throw 'Could not locate native ROM loader in runtime/harness.c.' }
$harness = $harness.Replace($oldLoader, $newLoader.TrimEnd())
Set-Content -LiteralPath $harnessPath -Value $harness -Encoding utf8

if (Test-Path -LiteralPath $readmePath) {
  $readme = Get-Content -LiteralPath $readmePath -Raw
  $readme = $readme.Replace('Drop your own Mega Drive ROM into the launcher and click LAUNCH MEGA TURRICAN.', 'Select the actual Mega Drive ROM file (for this game, Mega_Turrican__USA_.md) and click LAUNCH MEGA TURRICAN. Do not drop MegaTurrican.exe into the ROM box; that is the Windows game program, not the cartridge ROM.')
  Set-Content -LiteralPath $readmePath -Value $readme -Encoding utf8
}
Write-Host 'Applied ROM-header validation, native ROM guard, corrected IPC, and process-startup reporting.'
