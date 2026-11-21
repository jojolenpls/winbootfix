<#
.SYNOPSIS
    Builds the optional winbootfix WinPE ISO with the Windows ADK installed on YOUR PC.

.DESCRIPTION
    Nothing from Microsoft is redistributed by winbootfix: this script uses your
    own Windows ADK + WinPE add-on to create the image. Run it in an elevated
    PowerShell on Windows 10/11:

        powershell -ExecutionPolicy Bypass -File .\build-winpe.ps1

    Requirements: "Windows ADK" (Deployment Tools) and the "Windows PE add-on
    for the ADK": https://learn.microsoft.com/windows-hardware/get-started/adk-install

.PARAMETER OutputIso   Path of the ISO to create (default: .\winbootfix-winpe.iso).
.PARAMETER WorkDir     Temporary build folder (must not exist, or use -Force).
.PARAMETER DriverPath  Folder with extra drivers (.inf), e.g. Intel RST/VMD storage
                       drivers so WinPE can see NVMe disks behind VMD.
.PARAMETER Language    WinPE language, e.g. fr-fr (needs the matching ADK language files).
.PARAMETER Force       Delete WorkDir if it already exists.
#>
[CmdletBinding()]
param(
    [string]$OutputIso = (Join-Path (Get-Location) 'winbootfix-winpe.iso'),
    [string]$WorkDir = (Join-Path $env:TEMP 'winbootfix-winpe'),
    [ValidateSet('amd64')][string]$Arch = 'amd64',
    [string]$DriverPath,
    [string]$Language,
    [switch]$Force
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$OptionalComponents = @(
    'WinPE-WMI', 'WinPE-NetFX', 'WinPE-Scripting', 'WinPE-PowerShell',
    'WinPE-StorageWMI', 'WinPE-DismCmdlets', 'WinPE-SecureStartup', 'WinPE-EnhancedStorage'
)

function Fail([string]$Message) { Write-Host "ERROR: $Message" -ForegroundColor Red; exit 1 }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail 'run this script in a PowerShell opened as administrator.'
}

$roots = Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots' -ErrorAction SilentlyContinue
if (-not $roots -or -not $roots.PSObject.Properties['KitsRoot10']) { Fail 'Windows ADK not found. Install it: https://learn.microsoft.com/windows-hardware/get-started/adk-install' }
$adk = Join-Path $roots.KitsRoot10 'Assessment and Deployment Kit'
$dandi = Join-Path $adk 'Deployment Tools\DandISetEnv.bat'
$winpeRoot = Join-Path $adk 'Windows Preinstallation Environment'
$ocDir = Join-Path $winpeRoot "$Arch\WinPE_OCs"
if (-not (Test-Path -LiteralPath $dandi)) { Fail 'ADK "Deployment Tools" are not installed.' }
if (-not (Test-Path -LiteralPath $ocDir)) { Fail 'the "Windows PE add-on for the ADK" is not installed.' }

$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$locales = Join-Path $repo 'locales'
if (-not (Test-Path -LiteralPath $locales)) { $locales = Join-Path (Split-Path $PSScriptRoot -Parent) 'locales' }
if (-not (Test-Path -LiteralPath $locales)) { Fail "translations folder not found ($locales)." }

if (Test-Path -LiteralPath $WorkDir) {
    if (-not $Force) { Fail "$WorkDir already exists (use -Force to delete it)." }
    Remove-Item -LiteralPath $WorkDir -Recurse -Force
}

Write-Host '[1/6] copype...' -ForegroundColor Cyan
& cmd.exe /c "call `"$dandi`" >nul && copype $Arch `"$WorkDir`""
if ($LASTEXITCODE -ne 0) { Fail "copype failed ($LASTEXITCODE)." }

$mount = Join-Path $WorkDir 'mount'
$wim = Join-Path $WorkDir 'media\sources\boot.wim'
New-Item -ItemType Directory -Force -Path $mount | Out-Null

Write-Host '[2/6] mounting boot.wim...' -ForegroundColor Cyan
Mount-WindowsImage -ImagePath $wim -Index 1 -Path $mount | Out-Null
$committed = $false
try {
    Write-Host '[3/6] optional components...' -ForegroundColor Cyan
    if ($Language) {
        $lp = Join-Path $ocDir "$Language\lp.cab"
        if (Test-Path -LiteralPath $lp) { Add-WindowsPackage -Path $mount -PackagePath $lp | Out-Null }
        else { Write-Warning "language pack $Language not found, WinPE stays in English." }
    }
    foreach ($oc in $OptionalComponents) {
        Write-Host "      $oc"
        Add-WindowsPackage -Path $mount -PackagePath (Join-Path $ocDir "$oc.cab") | Out-Null
        if ($Language) {
            $loc = Join-Path $ocDir "$Language\${oc}_$Language.cab"
            if (Test-Path -LiteralPath $loc) { Add-WindowsPackage -Path $mount -PackagePath $loc | Out-Null }
        }
    }
    if ($Language) {
        & dism.exe "/Image:$mount" "/Set-AllIntl:$Language" | Out-Null
    }

    if ($DriverPath) {
        Write-Host '[4/6] drivers...' -ForegroundColor Cyan
        Add-WindowsDriver -Path $mount -Driver $DriverPath -Recurse | Out-Null
    } else {
        Write-Host '[4/6] no extra drivers (-DriverPath)' -ForegroundColor Cyan
    }

    Write-Host '[5/6] winbootfix scripts...' -ForegroundColor Cyan
    $dest = Join-Path $mount 'winbootfix'
    New-Item -ItemType Directory -Force -Path (Join-Path $dest 'locales') | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'winpe-repair.ps1') -Destination $dest
    Copy-Item -Path (Join-Path $locales '*.json') -Destination (Join-Path $dest 'locales')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'startnet.cmd') -Destination (Join-Path $mount 'Windows\System32\startnet.cmd') -Force

    Dismount-WindowsImage -Path $mount -Save | Out-Null
    $committed = $true
} finally {
    if (-not $committed) {
        Write-Warning 'build failed, discarding changes...'
        Dismount-WindowsImage -Path $mount -Discard -ErrorAction SilentlyContinue | Out-Null
    }
}

Write-Host '[6/6] creating the ISO...' -ForegroundColor Cyan
& cmd.exe /c "call `"$dandi`" >nul && MakeWinPEMedia /ISO /F `"$WorkDir`" `"$OutputIso`""
if ($LASTEXITCODE -ne 0) { Fail "MakeWinPEMedia failed ($LASTEXITCODE)." }

$hash = (Get-FileHash -LiteralPath $OutputIso -Algorithm SHA256).Hash
Write-Host ''
Write-Host "OK: $OutputIso" -ForegroundColor Green
Write-Host "SHA256: $hash"
Write-Host 'Write it to a USB stick with Rufus, Ventoy or balenaEtcher (see docs/usb-guide.md).'
