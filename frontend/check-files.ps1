$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

function Ensure($rel, $content) {
    $path = Join-Path $root $rel
    $dir  = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    if (Test-Path $path) {
        Write-Host ("  kept    {0}" -f $rel) -ForegroundColor DarkGray
    } else {
        Set-Content -Path $path -Value $content -Encoding utf8
        Write-Host ("  WROTE   {0}" -f $rel) -ForegroundColor Green
    }
}

Write-Host "Checking frontend files..." -ForegroundColor Cyan

Ensure "src/components/Modal.css" @"
.modal-scrim{
  position:fixed;inset:0;
  background:rgba(0,0,0,.6);
  display:flex;align-items:center;justify-content:center;
  padding:20px;
  z-index:80;
}
.modal{
  width:100%;
  max-height:88vh;
  overflow-y:auto;
  box-shadow:var(--shadow);
  padding:22px;
}
.modal-head{margin-bottom:18px}
.modal-x{padding:6px 8px;border:0}
"@

# Report anything still absent, so nothing fails silently later.
$expected = @(
  "src/theme.css",
  "src/App.jsx",
  "src/main.jsx",
  "src/lib/api.js",
  "src/lib/auth.jsx",
  "src/lib/useList.js",
  "src/components/Layout.jsx",
  "src/components/Layout.css",
  "src/components/Modal.jsx",
  "src/components/Modal.css",
  "src/components/Pager.jsx",
  "src/components/bits.jsx",
  "src/pages/Landing.jsx",
  "src/pages/Landing.css",
  "src/pages/Login.jsx",
  "src/pages/Login.css",
  "src/pages/Overview.jsx",
  "src/pages/UnknownCards.jsx",
  "src/pages/Students.jsx",
  "src/pages/Courses.jsx",
  "src/pages/Timetable.jsx",
  "src/pages/Timetable.css"
)

Write-Host ""
$missing = @()
foreach ($f in $expected) {
    if (-not (Test-Path (Join-Path $root $f))) { $missing += $f }
}
if ($missing.Count -eq 0) {
    Write-Host "All files present." -ForegroundColor Green
} else {
    Write-Host "STILL MISSING:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host ("  {0}" -f $_) -ForegroundColor Red }
}
