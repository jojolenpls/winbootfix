<#
.SYNOPSIS
    winbootfix WinPE menu: repair Windows startup (bcdboot) and offline system files (DISM / SFC).
#>
[CmdletBinding()]
param([string]$Lang)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

$script:Root = $PSScriptRoot
$script:Strings = @{}
$EspGuid = '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
$DataGuid = '{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}'

function Import-Strings([string]$Language) {
    $table = @{}
    foreach ($code in @('en', $Language)) {
        if (-not $code) { continue }
        $file = Join-Path $script:Root "locales\$code.json"
        if (Test-Path -LiteralPath $file) {
            $json = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $json.PSObject.Properties) { if ($p.Name -notlike '_*') { $table[$p.Name] = [string]$p.Value } }
        }
    }
    $script:Strings = $table
}

function T([string]$Key, [hashtable]$Params = @{}) {
    $text = if ($script:Strings.ContainsKey($Key)) { $script:Strings[$Key] } else { $Key }
    foreach ($k in $Params.Keys) { $text = $text.Replace('{' + $k + '}', [string]$Params[$k]) }
    return $text
}

function Confirm-Step([string]$Question) {
    $answer = Read-Host "$Question $(T 'ui.yes_no_hint_default_no')"
    if (-not $answer) { return $false }
    return (T 'ui.yes_letters').ToLower().Contains($answer.Trim().Substring(0, 1).ToLower())
}

function Select-Item([string]$Title, [object[]]$Items, [scriptblock]$Label) {
    if ($Items.Count -eq 1) { return $Items[0] }
    Write-Host $Title
    for ($i = 0; $i -lt $Items.Count; $i++) { Write-Host ("  {0}) {1}" -f ($i + 1), (& $Label $Items[$i])) }
    while ($true) {
        $a = Read-Host (T 'ui.choice_prompt' @{ max = $Items.Count })
        if ($a -match '^\d+$' -and [int]$a -ge 1 -and [int]$a -le $Items.Count) { return $Items[[int]$a - 1] }
    }
}

function Get-FreeLetter {
    $used = (Get-PSDrive -PSProvider FileSystem).Name
    foreach ($l in 'S', 'T', 'U', 'V', 'W', 'Y', 'Z', 'R', 'Q', 'P') { if ($used -notcontains $l) { return $l } }
    return $null
}

function Initialize-Letters {
    <# Gives a letter to data partitions without one, so Windows volumes become visible. #>
    foreach ($p in Get-Partition | Where-Object { $_.GptType -eq $DataGuid -and -not $_.DriveLetter }) {
        try { $p | Add-PartitionAccessPath -AssignDriveLetter -ErrorAction Stop } catch { }
    }
}

function Get-OfflineInfo([string]$Letter) {
    $hive = "${Letter}:\Windows\System32\config\SOFTWARE"
    $info = [pscustomobject]@{ Name = 'Windows'; Build = 0; Edition = ''; Version = '' }
    & reg.exe load 'HKLM\WBF_SOFT' $hive 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        try {
            $v = Get-ItemProperty 'HKLM:\WBF_SOFT\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop
            $info.Name = $v.ProductName
            $info.Build = [int]$v.CurrentBuild
            $info.Edition = $v.EditionID
            if ($v.PSObject.Properties['DisplayVersion']) { $info.Version = $v.DisplayVersion }
            if ($info.Build -ge 22000) { $info.Name = $info.Name -replace 'Windows 10', 'Windows 11' }
        } catch { }
        [gc]::Collect()
        & reg.exe unload 'HKLM\WBF_SOFT' | Out-Null
    }
    return $info
}

function Get-WindowsInstalls {
    Initialize-Letters
    $list = @()
    foreach ($p in Get-Partition | Where-Object { $_.DriveLetter -and $_.DriveLetter -ne 'X' }) {
        $l = [string]$p.DriveLetter
        if (Test-Path -LiteralPath "${l}:\Windows\System32\config\SYSTEM") {
            $i = Get-OfflineInfo $l
            $list += [pscustomobject]@{ Letter = $l; Disk = $p.DiskNumber; Partition = $p.PartitionNumber; Info = $i }
        }
    }
    return $list
}

function Get-LockedVolumes {
    try {
        return @(Get-CimInstance -Namespace 'root\cimv2\Security\MicrosoftVolumeEncryption' -ClassName Win32_EncryptableVolume -ErrorAction Stop |
            Where-Object { (Invoke-CimMethod -InputObject $_ -MethodName GetLockStatus).LockStatus -eq 1 })
    } catch { return @() }
}

function Get-Esp([object]$Install) {
    $esps = @(Get-Partition | Where-Object { $_.GptType -eq $EspGuid })
    if ($esps.Count -eq 0) { return $null }
    $same = @($esps | Where-Object { $_.DiskNumber -eq $Install.Disk })
    $pool = if ($same.Count -gt 0) { $same } else { $esps }
    $esp = Select-Item (T 'winpe.choose_esp') $pool { param($e) "Disk $($e.DiskNumber) partition $($e.PartitionNumber) ($([int]($e.Size / 1MB)) MB)" }
    if (-not $esp.DriveLetter) {
        $letter = Get-FreeLetter
        Add-PartitionAccessPath -DiskNumber $esp.DiskNumber -PartitionNumber $esp.PartitionNumber -AccessPath "${letter}:\"
        $esp = Get-Partition -DiskNumber $esp.DiskNumber -PartitionNumber $esp.PartitionNumber
    }
    return $esp
}

function Backup-Esp([string]$EspLetter, [object]$Install) {
    $dir = "$($Install.Letter):\winbootfix\backups\winpe-{0:yyyyMMdd-HHmmss}" -f (Get-Date)
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    if (Test-Path "${EspLetter}:\EFI") { Copy-Item -LiteralPath "${EspLetter}:\EFI" -Destination (Join-Path $dir 'EFI') -Recurse -Force }
    & bcdedit.exe /enum firmware > (Join-Path $dir 'bcdedit-firmware.txt') 2>&1
    return $dir
}

function Repair-Boot([object]$Install) {
    $esp = Get-Esp $Install
    if (-not $esp) { Write-Host (T 'winpe.no_esp') -ForegroundColor Red; return }
    $e = [string]$esp.DriveLetter
    Write-Host (T 'winpe.boot_explain' @{ windows = "$($Install.Letter):\Windows"; esp = "${e}:" })
    if (-not (Confirm-Step (T 'engine.confirm_all'))) { return }
    try { $b = Backup-Esp $e $Install; Write-Host (T 'winpe.backup_done' @{ path = $b }) }
    catch { Write-Host (T 'winpe.backup_failed') -ForegroundColor Red; if (-not (Confirm-Step (T 'winpe.continue_without_backup'))) { return } }
    $bcdArgs = @("$($Install.Letter):\Windows", '/s', "${e}:", '/f', 'UEFI')
    $others = @(Get-ChildItem -LiteralPath "${e}:\EFI" -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -notin 'Microsoft', 'Boot' })
    if ($others.Count -gt 0) {
        $names = ($others.Name -join ', ')
        if (Confirm-Step (T 'winpe.keep_other_first' @{ other = $names })) { $bcdArgs += '/addlast' }
    }
    & bcdboot.exe @bcdArgs
    if ($LASTEXITCODE -eq 0) { Write-Host (T 'winpe.boot_done') -ForegroundColor Green }
    else { Write-Host (T 'winpe.boot_failed' @{ code = $LASTEXITCODE }) -ForegroundColor Red }
}

function Find-Source([object]$Install) {
    foreach ($d in Get-PSDrive -PSProvider FileSystem) {
        if ($d.Name -eq 'X' -or $d.Name -eq $Install.Letter) { continue }
        foreach ($n in 'install.wim', 'install.esd') {
            $p = Join-Path $d.Root "sources\$n"
            if (Test-Path -LiteralPath $p) { return $p }
        }
    }
    $a = Read-Host (T 'winpe.ask_source')
    if ($a -and (Test-Path -LiteralPath $a.Trim('"'))) { return $a.Trim('"') }
    return $null
}

function Repair-Offline([object]$Install) {
    $l = $Install.Letter
    Write-Host (T 'winpe.offline_explain' @{ windows = "${l}:\Windows" })
    if (-not (Confirm-Step (T 'engine.confirm_all'))) { return }
    $scratch = "${l}:\winbootfix\scratch"
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    if ((Test-Path -LiteralPath "${l}:\Windows\WinSxS\pending.xml") -and (Confirm-Step (T 'winpe.revert_pending'))) {
        & dism.exe "/Image:${l}:\" /Cleanup-Image /RevertPendingActions "/ScratchDir:$scratch"
    }
    $dismArgs = @("/Image:${l}:\", '/Cleanup-Image', '/RestoreHealth', "/ScratchDir:$scratch")
    $src = Find-Source $Install
    if ($src) {
        $index = 1
        foreach ($img in Get-WindowsImage -ImagePath $src) {
            $detail = Get-WindowsImage -ImagePath $src -Index $img.ImageIndex
            if ($detail.EditionId -eq $Install.Info.Edition) {
                $index = $img.ImageIndex
                $build = [int]($detail.Version.Split('.')[2])
                if ($build -ne $Install.Info.Build) { Write-Host (T 'winpe.build_mismatch' @{ image = $build; windows = $Install.Info.Build }) -ForegroundColor Yellow }
                break
            }
        }
        $kind = if ($src -like '*.esd') { 'ESD' } else { 'WIM' }
        $dismArgs += "/Source:${kind}:${src}:$index"
        $dismArgs += '/LimitAccess'
    }
    & dism.exe @dismArgs
    if ($LASTEXITCODE -eq 0) { Write-Host (T 'post.dism_ok') -ForegroundColor Green }
    else { Write-Host (T 'post.dism_failed' @{ code = ('0x{0:X8}' -f $LASTEXITCODE) }) -ForegroundColor Yellow }
    & sfc.exe /scannow "/offbootdir=${l}:\" "/offwindir=${l}:\Windows"
    Write-Host (T 'post.sfc_result' @{ code = $LASTEXITCODE })
}

function Unlock-BitLocker {
    $locked = Get-LockedVolumes
    if ($locked.Count -eq 0) { Write-Host (T 'winpe.no_locked'); return }
    foreach ($v in $locked) {
        $key = Read-Host (T 'question.bitlocker_key' @{ partition = $v.DriveLetter })
        if ($key) { & manage-bde.exe -unlock $v.DriveLetter -RecoveryPassword $key.Trim() }
    }
}

function Invoke-Main {
    $default = if ($Lang) { $Lang } else { [System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName }
    Import-Strings $default
    $codes = @(Get-ChildItem -LiteralPath (Join-Path $script:Root 'locales') -Filter *.json | ForEach-Object { $_.BaseName })
    if (-not $Lang -and $codes.Count -gt 1) {
        $chosen = Select-Item 'Language / Langue' $codes { param($c) $c }
        Import-Strings $chosen
    }
    while ($true) {
        Write-Host ''
        Write-Host (T 'winpe.title') -ForegroundColor Cyan
        $installs = @(Get-WindowsInstalls)
        if ($installs.Count -eq 0) {
            Write-Host (T 'winpe.no_windows') -ForegroundColor Yellow
            if ((Get-LockedVolumes).Count -gt 0) { Write-Host (T 'winpe.bitlocker_hint') }
        }
        Write-Host "  1) $(T 'winpe.menu_boot')"
        Write-Host "  2) $(T 'winpe.menu_offline')"
        Write-Host "  3) $(T 'winpe.menu_bitlocker')"
        Write-Host "  4) $(T 'winpe.menu_cmd')"
        Write-Host "  5) $(T 'menu.reboot')"
        Write-Host "  6) $(T 'menu.poweroff')"
        $c = Read-Host (T 'ui.choice_prompt' @{ max = 6 })
        switch ($c) {
            '1' { if ($installs.Count) { Repair-Boot (Select-Item (T 'question.choose_windows') $installs { param($i) "$($i.Info.Name) $($i.Info.Version) (build $($i.Info.Build)) - $($i.Letter):" }) } }
            '2' { if ($installs.Count) { Repair-Offline (Select-Item (T 'question.choose_windows') $installs { param($i) "$($i.Info.Name) $($i.Info.Version) (build $($i.Info.Build)) - $($i.Letter):" }) } }
            '3' { Unlock-BitLocker }
            '4' { Write-Host (T 'winpe.cmd_hint'); return }
            '5' { & wpeutil.exe reboot }
            '6' { & wpeutil.exe shutdown }
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') { Invoke-Main }
