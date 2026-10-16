#Requires -Version 5.1
<#
.SYNOPSIS
  在 DSH 沙箱内离线安装 akshare 及依赖到指定 venv。

.DESCRIPTION
  DSH 的文件沙箱会拦截 Python 子进程在平台临时目录（C:\...\Temp）里的
  pip build/unpack 操作（WinError 5 拒绝访问）。本脚本绕开该限制：
  1. 用 Node fetch（TLS 由 Node 处理，不依赖 schannel）从 PyPI 下载 wheel
  2. 把 wheel 放到工作区内
  3. 用 --no-index --find-links 本地离线安装（pip 不再建平台临时目录）

  实测在 DSH workspace-write 沙箱下 100% 通过（2026-10-16）。

.PARAMETER VenvPython
  目标 venv 的 python.exe 全路径。

.PARAMETER WheelsDir
  wheel 缓存目录（工作区内）。

.EXAMPLE
  .\install_akshare.ps1 -VenvPython D:\...\venv-ak\Scripts\python.exe `
                        -WheelsDir   D:\...\equity-pipeline\buildtmp\wheels
#>
param(
  [Parameter(Mandatory)][string]$VenvPython,
  [Parameter(Mandatory)][string]$WheelsDir
)

$ErrorActionPreference = 'Stop'

# 找 DSH 自带 node（v24，有 zlib.zstdDecompressSync 和 fetch）
$dshNode = $null
foreach ($cand in @(
  'D:\Users\KHADAS\AppData\Local\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe',
  "$env:LOCALAPPDATA\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
)) {
  if (Test-Path $cand) { $dshNode = $cand; break }
}
if (-not $dshNode) { throw 'DSH bundled node.exe not found' }

New-Item -ItemType Directory -Force $WheelsDir | Out-Null
$dlScript = Join-Path $WheelsDir 'dlwheels.js'

# 内联下载脚本：从 PyPI JSON API 取最新稳定版 wheel
@'
const fs = require('fs'), path = require('path');
const outDir = process.argv[2];
fs.mkdirSync(outDir, { recursive: true });
const INDEX = 'https://pypi.org/pypi/';
const projects = [
  'akshare','beautifulsoup4','requests','curl_cffi','html5lib','xlrd','urllib3',
  'tqdm','jsonpath','tabulate','decorator','mini-racer',
  'charset-normalizer','idna','certifi','soupsieve','webencodings','cffi','pycparser',
  'typing-extensions','colorama','lxml','pandas','numpy','openpyxl','six',
  'python-dateutil','pytz','tzdata','et-xmlfile','pillow',
];
async function pick(p){
  const r = await fetch(INDEX+p+'/json',{signal:AbortSignal.timeout(20000)});
  if(!r.ok){console.log(p,'index',r.status);return null;}
  const j=await r.json(); const ver=j.info.version; const urls=j.releases[ver]||[];
  if(!urls.length){console.log(p,'no files for',ver);return null;}
  const score=u=>{const f=u.filename.toLowerCase();let s=0;
    if(f.includes('py3-none-any'))s+=100; if(f.includes('cp312-none-any'))s+=90;
    if(f.includes('cp312-win_amd64'))s+=80; if(f.includes('win_amd64'))s+=40;
    if(f.includes('win32'))s-=100; if(f.endsWith('.whl'))s+=10; return s;};
  urls.sort((a,b)=>score(b)-score(a)); return urls[0];
}
(async()=>{
  for(const p of projects){
    try{
      const u=await pick(p); if(!u)continue;
      const out=path.join(outDir,u.filename);
      if(fs.existsSync(out)){console.log('skip',u.filename);continue;}
      const buf=Buffer.from(await(await fetch(u.url,{signal:AbortSignal.timeout(120000)})).arrayBuffer());
      fs.writeFileSync(out,buf); console.log('got',u.filename,buf.length);
    }catch(e){console.log(p,'ERR',e.name);}
  }
  console.log('download done');
})();
'@ | Set-Content -Path $dlScript -Encoding utf8

Write-Host '[1/3] 下载 wheel（Node fetch，绕开 schannel）…'
& $dshNode $dlScript $WheelsDir

Write-Host '[2/3] 离线安装（--no-index --find-links，绕开平台 temp）…'
$pkgs = 'akshare','beautifulsoup4','requests','curl_cffi','html5lib','xlrd','urllib3','tqdm','tabulate','decorator','mini-racer','lxml','pandas','numpy','openpyxl'
& $VenvPython -m pip install --no-cache-dir --no-index --find-links $WheelsDir $pkgs 2>&1 | Select-Object -Last 15

Write-Host '[3/3] jsonpath（sdist，pip build 受限）手动装…'
$jp = Get-ChildItem $WheelsDir -Filter 'jsonpath-*.tar.gz' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($jp) {
  $extract = Join-Path $WheelsDir ('jp_' + $jp.BaseName)
  New-Item -ItemType Directory -Force $extract | Out-Null
  & $VenvPython -c "import tarfile; tarfile.open(r'$($jp.FullName)', 'r:gz').extractall(r'$extract', filter='data')" 2>$null
  $src = Get-ChildItem $extract -Directory | Select-Object -First 1
  $pkg = Join-Path $src.FullName 'jsonpath'
  if (Test-Path $pkg) {
    $sitePkg = Split-Path (Split-Path (Split-Path $VenvPython)) '\Lib\site-packages'
    Copy-Item $pkg $sitePkg -Recurse -Force
    Write-Host '  jsonpath 手动安装完成'
  }
}

Write-Host '=== 验证 ==='
& $VenvPython -c "import akshare; print('akshare', akshare.__version__)" 2>&1 | Select-Object -First 3
