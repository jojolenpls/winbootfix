<#
.SYNOPSIS
    winbootfix post-repair script for Windows 10/11.

.DESCRIPTION
    Runs automatically at the next sign-in when winbootfix (Linux) scheduled it
    through RunOnce, or by hand as administrator. Steps:
      1. regenerate the boot configuration with bcdboot (if winbootfix rebuilt it);
      2. DISM /Online /Cleanup-Image /RestoreHealth, then sfc /scannow;
      3. graphics driver: re-enable, reinstall from the DriverStore, Windows Update,
         official vendor driver, DDU in Safe Mode as a last resort;
      4. list the quarantined DLLs and what to reinstall;
      5. final check and report. Never restarts the PC without confirmation.

.PARAMETER FromRunOnce   Set by the RunOnce entry.
.PARAMETER Lang          Force the language (en, fr...).
.PARAMETER Yes           Answer yes to questions (never to a restart).
.PARAMETER SkipDism      Do not run DISM.
.PARAMETER SkipSfc       Do not run SFC.
.PARAMETER SkipGpu       Do not touch the graphics driver.
.PARAMETER NoPause       Do not wait for Enter at the end and do not ask to restart (automation).
#>
[CmdletBinding()]
param(
    [switch]$FromRunOnce,
    [string]$Lang,
    [switch]$Yes,
    [switch]$SkipDism,
    [switch]$SkipSfc,
    [switch]$SkipGpu,
    [switch]$NoPause
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

$script:Root = $PSScriptRoot
$script:BoundParams = $PSBoundParameters
$script:Strings = @{}
$script:Report = New-Object System.Collections.Generic.List[string]
$script:Problems = 0
$script:DisplayClass = '{4d36e968-e325-11ce-bfc1-08002be10318}'
$script:RunOnceKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce'
$script:WantsReboot = $false

# ---------------------------------------------------------------- language
function Import-Strings {
    param([string]$Language)
    $dir = Join-Path $script:Root 'locales'
    $table = @{}
    foreach ($code in @('en', $Language)) {
        if (-not $code) { continue }
        $file = Join-Path $dir "$code.json"
        if (Test-Path -LiteralPath $file) {
            $json = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $json.PSObject.Properties) {
                if ($p.Name -notlike '_*') { $table[$p.Name] = [string]$p.Value }
            }
        }
    }
    $script:Strings = $table
}

function T {
    param([string]$Key, [hashtable]$Params = @{})
    $text = if ($script:Strings.ContainsKey($Key)) { $script:Strings[$Key] } else { $Key }
    foreach ($k in $Params.Keys) { $text = $text.Replace('{' + $k + '}', [string]$Params[$k]) }
    return $text
}

function Get-DefaultLanguage {
    param([string]$Forced)
    if ($Forced) { return $Forced.Split('-')[0].ToLower() }
    $state = Get-State
    if ($state -and $state.PSObject.Properties['language'] -and $state.language) { return [string]$state.language }
    return ([System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName)
}

# ---------------------------------------------------------------- output
function Write-Step([string]$Text) { Write-Host ''; Write-Host "== $Text ==" -ForegroundColor Cyan; Add-Report "== $Text ==" }
function Write-Info([string]$Text) { Write-Host $Text; Add-Report $Text }
function Write-Ok([string]$Text) { Write-Host "v $Text" -ForegroundColor Green; Add-Report "[OK] $Text" }
function Write-Warn2([string]$Text) { Write-Host "! $Text" -ForegroundColor Yellow; Add-Report "[!] $Text"; $script:Problems++ }
function Add-Report([string]$Text) { [void]$script:Report.Add($Text) }

function Confirm-Step {
    param([string]$Question, [switch]$NeverAuto)
    if ($Yes -and -not $NeverAuto) { Write-Info "$Question -> $(T 'ui.yes')"; return $true }
    $letters = (T 'ui.yes_letters').ToLower()
    $answer = Read-Host "$Question $(T 'ui.yes_no_hint_default_no')"
    if (-not $answer) { return $false }
    return $letters.Contains($answer.Trim().Substring(0, 1).ToLower())
}

# ---------------------------------------------------------------- state
function Get-State {
    $file = Join-Path $script:Root 'state.json'
    if (Test-Path -LiteralPath $file) {
        try { return Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
    }
    return $null
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Remove-RunOnceEntry {
    foreach ($name in @('!winbootfix', 'winbootfix')) {
        Remove-ItemProperty -Path $script:RunOnceKey -Name $name -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------- PE helpers
function Get-PeMachine {
    <# Returns the PE Machine field (0x14c x86, 0x8664 x64, 0xaa64 ARM64), 0 if empty, -1 if invalid. #>
    param([string]$Path)
    try {
        $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try {
            if ($fs.Length -eq 0) { return 0 }
            $br = New-Object System.IO.BinaryReader($fs)
            if ($br.ReadUInt16() -ne 0x5A4D) { return -1 }
            $fs.Seek(0x3C, 'Begin') | Out-Null
            $lfanew = $br.ReadUInt32()
            if ($lfanew + 6 -gt $fs.Length) { return -1 }
            $fs.Seek($lfanew, 'Begin') | Out-Null
            if ($br.ReadUInt32() -ne 0x00004550) { return -1 }
            return [int]$br.ReadUInt16()
        } finally { $fs.Dispose() }
    } catch { return -1 }
}

function Find-WrongArchDll {
    param([string]$WindowsDir = $env:windir)
    $out = @()
    $sys32 = Join-Path $WindowsDir 'System32'
    $wow = Join-Path $WindowsDir 'SysWOW64'
    if (Test-Path $wow) {
        foreach ($f in Get-ChildItem -LiteralPath $sys32 -Filter *.dll -File -ErrorAction SilentlyContinue) {
            $m = Get-PeMachine $f.FullName
            if ($m -eq 0x14c -or $m -eq 0 -or $m -eq -1) { $out += [pscustomobject]@{ Path = $f.FullName; Machine = $m } }
        }
        foreach ($f in Get-ChildItem -LiteralPath $wow -Filter *.dll -File -ErrorAction SilentlyContinue) {
            $m = Get-PeMachine $f.FullName
            if ($m -eq 0x8664 -or $m -eq 0 -or $m -eq -1) { $out += [pscustomobject]@{ Path = $f.FullName; Machine = $m } }
        }
    }
    return $out
}

# ---------------------------------------------------------------- boot (bcdboot)
function Invoke-BcdRefresh {
    param($State)
    Write-Step (T 'post.step_bcd')
    $letter = $null
    foreach ($l in @('S', 'T', 'U', 'V', 'W', 'Y', 'Z')) { if (-not (Test-Path "${l}:\")) { $letter = $l; break } }
    if (-not $letter) { Write-Warn2 (T 'post.bcd_no_letter'); return }
    & mountvol "${letter}:" /S | Out-Null
    if (-not (Test-Path "${letter}:\EFI")) { Write-Warn2 (T 'post.bcd_no_esp'); return }
    try {
        $bcd = "${letter}:\EFI\Microsoft\Boot\BCD"
        $saved = "$bcd.winbootfix"
        if (Test-Path -LiteralPath $bcd) { Copy-Item -LiteralPath $bcd -Destination $saved -Force; Remove-Item -LiteralPath $bcd -Force }
        $bcdArgs = @($env:windir, '/s', "${letter}:", '/f', 'UEFI')
        if ($State -and $State.keep_bootorder) { $bcdArgs += '/addlast' }
        if ($State -and $State.boot_set -eq 'EFI_EX') { $bcdArgs += '/bootex' }
        & bcdboot @bcdArgs | ForEach-Object { Add-Report $_ }
        if ($LASTEXITCODE -eq 0) {
            Write-Ok (T 'post.bcd_done')
            Remove-Item -LiteralPath $saved -Force -ErrorAction SilentlyContinue
        } else {
            Write-Warn2 (T 'post.bcd_failed' @{ code = $LASTEXITCODE })
            if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination $bcd -Force }
        }
    } finally {
        & mountvol "${letter}:" /D | Out-Null
    }
}

# ---------------------------------------------------------------- DISM / SFC
function Invoke-SystemRepair {
    $logs = Join-Path $script:Root 'logs'
    if (-not $SkipDism) {
        Write-Step (T 'post.step_dism')
        Write-Info (T 'post.dism_wait')
        $dismLog = Join-Path $logs 'dism.log'
        & dism.exe /Online /Cleanup-Image /RestoreHealth "/LogPath:$dismLog"
        $code = $LASTEXITCODE
        if ($code -eq 0) { Write-Ok (T 'post.dism_ok') }
        else {
            Write-Warn2 (T 'post.dism_failed' @{ code = ('0x{0:X8}' -f $code) })
            $src = Find-InstallImage
            if ($src -and (Confirm-Step (T 'post.dism_retry_source' @{ path = $src.Path }))) {
                & dism.exe /Online /Cleanup-Image /RestoreHealth "/Source:$($src.Source)" /LimitAccess "/LogPath:$dismLog"
                if ($LASTEXITCODE -eq 0) { Write-Ok (T 'post.dism_ok') } else { Write-Warn2 (T 'post.dism_failed' @{ code = ('0x{0:X8}' -f $LASTEXITCODE) }) }
            } elseif (-not $src) {
                Write-Info (T 'post.dism_need_media')
            }
        }
    }
    if (-not $SkipSfc) {
        Write-Step (T 'post.step_sfc')
        Write-Info (T 'post.sfc_wait')
        & sfc.exe /scannow
        $code = $LASTEXITCODE
        Copy-Item -LiteralPath (Join-Path $env:windir 'Logs\CBS\CBS.log') -Destination (Join-Path $logs 'CBS.log') -ErrorAction SilentlyContinue
        if ($code -eq 0) { Write-Ok (T 'post.sfc_ok') } else { Write-Warn2 (T 'post.sfc_result' @{ code = $code }) }
    }
}

function Find-InstallImage {
    <# Looks for sources\install.wim/esd on every drive (mounted Windows ISO or USB). #>
    $edition = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction SilentlyContinue).EditionID
    foreach ($d in Get-PSDrive -PSProvider FileSystem) {
        foreach ($name in @('install.wim', 'install.esd')) {
            $p = Join-Path $d.Root "sources\$name"
            if (Test-Path -LiteralPath $p) {
                $index = 1
                try {
                    $img = Get-WindowsImage -ImagePath $p | Where-Object {
                        (Get-WindowsImage -ImagePath $p -Index $_.ImageIndex).EditionId -eq $edition } | Select-Object -First 1
                    if ($img) { $index = $img.ImageIndex }
                } catch { }
                $kind = if ($name -like '*.esd') { 'ESD' } else { 'WIM' }
                return [pscustomobject]@{ Path = $p; Source = "${kind}:${p}:${index}" }
            }
        }
    }
    return $null
}

# ---------------------------------------------------------------- GPU
function Get-DeviceProp {
    param($Device, [string]$Key)
    try { return (Get-PnpDeviceProperty -InstanceId $Device.InstanceId -KeyName $Key -ErrorAction Stop).Data } catch { return $null }
}

function Get-GpuState {
    $list = @()
    foreach ($d in Get-PnpDevice -Class Display -PresentOnly -ErrorAction SilentlyContinue) {
        $hw = ''
        if ($d.InstanceId -match 'VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})') { $hw = "VEN_$($Matches[1])&DEV_$($Matches[2])" }
        $list += [pscustomobject]@{
            Device  = $d
            Name    = $d.FriendlyName
            HwId    = $hw
            Vendor  = if ($hw) { $hw.Substring(4, 4).ToLower() } else { '' }
            Service = [string](Get-DeviceProp $d 'DEVPKEY_Device_Service')
            Version = [string](Get-DeviceProp $d 'DEVPKEY_Device_DriverVersion')
            Problem = [int](Get-DeviceProp $d 'DEVPKEY_Device_ProblemCode')
            Status  = [string]$d.Status
        }
    }
    return $list
}

function Test-GpuHealthy($g) {
    return ($g.Service -and $g.Service -ne 'BasicDisplay' -and $g.Problem -eq 0 -and $g.Version)
}

function Find-DriverStoreInf {
    <# INF files in the DriverStore that declare this hardware id, newest first. #>
    param([string]$HwId, [string]$Repository = (Join-Path $env:windir 'System32\DriverStore\FileRepository'))
    $repo = $Repository
    $pattern = [regex]::Escape("PCI\$HwId")
    $found = @()
    foreach ($inf in Get-ChildItem -LiteralPath $repo -Filter *.inf -Recurse -File -ErrorAction SilentlyContinue) {
        try { $text = Get-Content -LiteralPath $inf.FullName -Raw -ErrorAction Stop } catch { continue }
        if ($text -notmatch '(?im)^\s*Class\s*=\s*Display') { continue }
        if ($text -match "(?i)$pattern") {
            $date = [datetime]::MinValue
            if ($text -match '(?im)^\s*DriverVer\s*=\s*([0-9/]+)') { [void][datetime]::TryParse($Matches[1], [ref]$date) }
            $found += [pscustomobject]@{ Path = $inf.FullName; Date = $date }
        }
    }
    return $found | Sort-Object Date -Descending
}

function Get-GpuDb {
    $file = Join-Path $script:Root 'data\gpu.json'
    if (Test-Path -LiteralPath $file) { return Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json }
    return $null
}

function Repair-Gpu {
    Write-Step (T 'post.step_gpu')
    $db = Get-GpuDb
    $gpus = Get-GpuState
    if (-not $gpus) { Write-Warn2 (T 'post.gpu_none'); return }
    foreach ($g in $gpus) {
        Write-Info (T 'post.gpu_found' @{ name = $g.Name; hwid = $g.HwId; version = $(if ($g.Version) { $g.Version } else { '-' }) })
        if (Test-GpuHealthy $g) { Write-Ok (T 'post.gpu_ok' @{ name = $g.Name }); continue }
        if (-not $g.HwId) { continue }

        if ($g.Problem -eq 22) {
            if (Confirm-Step (T 'post.gpu_enable' @{ name = $g.Name })) {
                Enable-PnpDevice -InstanceId $g.Device.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 5
                if (Test-GpuHealthy (Get-GpuState | Where-Object { $_.Device.InstanceId -eq $g.Device.InstanceId })) { Write-Ok (T 'post.gpu_fixed'); continue }
            }
        }

        $infs = @(Find-DriverStoreInf $g.HwId)
        if ($infs.Count -gt 0) {
            if (Confirm-Step (T 'post.gpu_reinstall_store' @{ inf = (Split-Path $infs[0].Path -Leaf) })) {
                & pnputil.exe /add-driver $infs[0].Path /install | ForEach-Object { Add-Report $_ }
                Start-Sleep -Seconds 10
                $now = Get-GpuState | Where-Object { $_.Device.InstanceId -eq $g.Device.InstanceId }
                if ($now -and (Test-GpuHealthy $now)) { Write-Ok (T 'post.gpu_fixed'); continue }
            }
        }

        Write-Info (T 'post.gpu_scan')
        & pnputil.exe /scan-devices | Out-Null
        Start-Sleep -Seconds 30
        $now = Get-GpuState | Where-Object { $_.Device.InstanceId -eq $g.Device.InstanceId }
        if ($now -and (Test-GpuHealthy $now)) { Write-Ok (T 'post.gpu_fixed'); continue }

        Invoke-VendorDriver $g $db
    }
}

function Invoke-VendorDriver {
    param($Gpu, $Db)
    $vendor = $null
    if ($Db -and $Db.vendors.PSObject.Properties[$Gpu.Vendor]) { $vendor = $Db.vendors.($Gpu.Vendor) }
    if (-not $vendor) { Write-Warn2 (T 'post.gpu_unknown_vendor' @{ hwid = $Gpu.HwId }); return }
    Write-Warn2 (T 'post.gpu_need_download' @{ vendor = $vendor.name; hwid = $Gpu.HwId })
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $chassis = (Get-CimInstance Win32_SystemEnclosure -ErrorAction SilentlyContinue).ChassisTypes
    $laptop = $chassis | Where-Object { $_ -in 8, 9, 10, 14, 30, 31, 32 }
    if ($laptop -and $cs) {
        $maker = ([string]$cs.Manufacturer).ToLower()
        foreach ($p in $Db.oem_support.PSObject.Properties) {
            if ($maker -like "*$($p.Name)*") { Write-Info (T 'post.gpu_oem_hint' @{ url = $p.Value }) }
        }
    }
    if (Confirm-Step (T 'post.gpu_open_page' @{ vendor = $vendor.name })) { Start-Process $vendor.driver_page }
    $installer = $null
    if ($vendor.installer_url) {
        if (Confirm-Step (T 'post.gpu_download_now' @{ vendor = $vendor.name })) {
            $installer = Join-Path $env:TEMP ("winbootfix-gpu-" + [IO.Path]::GetFileName(([uri]$vendor.installer_url).LocalPath))
            try { Invoke-WebRequest -Uri $vendor.installer_url -OutFile $installer -UseBasicParsing } catch { Write-Warn2 $_.Exception.Message; $installer = $null }
        }
    } elseif (-not $Yes) {
        $answer = Read-Host (T 'post.gpu_installer_path')
        if ($answer -and (Test-Path -LiteralPath $answer.Trim('"'))) { $installer = $answer.Trim('"') }
    }
    if ($installer) { Start-VerifiedInstaller $installer $vendor }
    if (-not $Yes -and (Confirm-Step (T 'post.gpu_ddu_offer'))) { Enable-DduSafeMode $Db }
}

function Start-VerifiedInstaller {
    param([string]$Path, $Vendor)
    $sig = Get-AuthenticodeSignature -LiteralPath $Path
    $subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' }
    if ($sig.Status -ne 'Valid' -or $subject -notlike "*$($Vendor.signer)*") {
        Write-Warn2 (T 'post.gpu_bad_signature' @{ file = $Path; signer = $subject })
        return
    }
    Write-Ok (T 'post.gpu_signature_ok' @{ signer = $Vendor.signer })
    Write-Info (T $Vendor.clean_install_hint)
    Start-Process -FilePath $Path -Wait
}

function Enable-DduSafeMode {
    param($Db)
    Write-Info (T 'post.ddu_explain')
    Start-Process $Db.ddu_page
    if (-not (Confirm-Step (T 'post.ddu_confirm_safeboot'))) { return }
    & bcdedit.exe /set '{default}' safeboot minimal | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warn2 (T 'post.ddu_bcdedit_failed'); return }
    # "*" = also run in Safe Mode. Removes Safe Mode at the first sign-in there.
    New-ItemProperty -Path $script:RunOnceKey -Name '*winbootfix-safeboot' -PropertyType String -Force `
        -Value 'cmd.exe /c bcdedit /deletevalue {default} safeboot' | Out-Null
    Write-Ok (T 'post.ddu_ready')
    Write-Info (T 'post.ddu_manual_exit')
    $script:WantsReboot = $true
}

# ---------------------------------------------------------------- quarantine
function Show-Quarantine {
    param($State)
    $base = Join-Path $env:SystemDrive 'winbootfix_quarantine'
    if (-not (Test-Path -LiteralPath $base)) { return }
    Write-Step (T 'post.step_quarantine')
    foreach ($dir in Get-ChildItem -LiteralPath $base -Directory) {
        $manifest = Join-Path $dir.FullName 'restore.json'
        if (-not (Test-Path -LiteralPath $manifest)) { continue }
        $data = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($f in $data.files) {
            $soft = if ($f.software -and $f.software.Count -gt 0) { $f.software -join ', ' } else { T 'finding.health.dll_unknown_software' }
            Write-Info (T 'post.quarantine_item' @{ file = $f.original; software = $soft })
        }
        Write-Info (T 'post.quarantine_restore' @{ path = (Join-Path $dir.FullName 'restore.cmd') })
    }
}

# ---------------------------------------------------------------- final check
function Test-Final {
    param([datetime]$Since)
    Write-Step (T 'post.step_final')
    foreach ($g in Get-GpuState) {
        if (Test-GpuHealthy $g) { Write-Ok (T 'post.final_gpu_ok' @{ name = $g.Name; version = $g.Version }) }
        else { Write-Warn2 (T 'post.final_gpu_bad' @{ name = $g.Name }) }
    }
    $events = @()
    try {
        $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; Id = 26; StartTime = $Since } -ErrorAction Stop |
            Where-Object { $_.Message -match '(?i)c000007b' })
    } catch { }
    $bad = @(Find-WrongArchDll)
    if ($events.Count -eq 0 -and $bad.Count -eq 0) { Write-Ok (T 'post.final_no_7b') }
    else {
        foreach ($b in $bad) { Write-Warn2 (T 'post.final_bad_dll' @{ file = $b.Path }) }
        if ($events.Count -gt 0) { Write-Warn2 (T 'post.final_7b_events' @{ count = $events.Count }) }
    }
}

function Save-Report {
    $dir = Join-Path $script:Root 'reports'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $file = Join-Path $dir ("post-report-{0:yyyyMMdd-HHmmss}.txt" -f (Get-Date))
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $header = @("winbootfix-post - $(Get-Date -Format 'yyyy-MM-dd HH:mm')",
        "Windows: $($os.Caption) $($os.Version) $($os.OSArchitecture)", '')
    ($header + $script:Report) -replace '(?i)(\\Users\\)[^\\\s]+', '$1<user>' | Set-Content -LiteralPath $file -Encoding UTF8
    return $file
}

# ---------------------------------------------------------------- main
function Invoke-Main {
    if (-not (Test-Admin)) {
        $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
        foreach ($k in $script:BoundParams.Keys) {
            $v = $script:BoundParams[$k]
            if ($v -is [switch]) { if ($v) { $argList += "-$k" } }
            else { $argList += "-$k"; $argList += "`"$v`"" }
        }
        Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -Verb RunAs
        return
    }
    Import-Strings (Get-DefaultLanguage $Lang)
    $logs = Join-Path $script:Root 'logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $started = Get-Date
    try { Start-Transcript -Path (Join-Path $logs ("post-{0:yyyyMMdd-HHmmss}.log" -f $started)) -Append | Out-Null } catch { }
    try {
        Remove-RunOnceEntry
        $host.UI.RawUI.WindowTitle = 'winbootfix'
        Write-Host (T 'post.title') -ForegroundColor Cyan
        Write-Info (T 'post.intro')
        $state = Get-State
        if ($state -and $state.bcdboot) { Invoke-BcdRefresh $state }
        Invoke-SystemRepair
        if (-not $SkipGpu) { Repair-Gpu }
        Show-Quarantine $state
        Test-Final $started
        $file = Save-Report
        Write-Host ''
        if ($script:Problems -eq 0) { Write-Ok (T 'post.done_ok') } else { Write-Warn2 (T 'post.done_problems' @{ count = $script:Problems }) }
        Write-Info (T 'post.report_saved' @{ path = $file })
        if (-not $NoPause) {
            $question = if ($script:WantsReboot) { T 'post.ask_reboot_safemode' } else { T 'post.ask_reboot' }
            if (Confirm-Step $question -NeverAuto) { Restart-Computer -Force }
            if ($FromRunOnce) { Read-Host (T 'post.press_enter') | Out-Null }
        }
    } finally {
        try { Stop-Transcript | Out-Null } catch { }
    }
}

if ($MyInvocation.InvocationName -ne '.') { Invoke-Main }
