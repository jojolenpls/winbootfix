# Pester 5 tests for the Windows scripts. Run on Windows: Invoke-Pester tests/windows
BeforeAll {
    $repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $post = Join-Path $repo 'windows/winbootfix-post.ps1'
    . $post
    $script:Root = Join-Path $TestDrive 'wbf'
    New-Item -ItemType Directory -Force -Path (Join-Path $script:Root 'locales') | Out-Null
    Copy-Item (Join-Path $repo 'locales/*.json') (Join-Path $script:Root 'locales')

    function New-Pe([string]$Path, [uint16]$Machine) {
        $bytes = New-Object byte[] 512
        $bytes[0] = 0x4D; $bytes[1] = 0x5A
        [BitConverter]::GetBytes([uint32]0x80).CopyTo($bytes, 0x3C)
        [Text.Encoding]::ASCII.GetBytes("PE`0`0").CopyTo($bytes, 0x80)
        [BitConverter]::GetBytes($Machine).CopyTo($bytes, 0x84)
        [IO.File]::WriteAllBytes($Path, $bytes)
    }
}

Describe 'Translations' {
    It 'loads French with English fallback' {
        Import-Strings 'fr'
        T 'ui.yes' | Should -Be 'Oui'
        T 'post.gpu_ok' @{ name = 'GPU' } | Should -Match 'GPU'
        T 'missing.key' | Should -Be 'missing.key'
    }
    It 'every key used by the scripts exists in en.json' {
        $en = Get-Content (Join-Path $script:Root 'locales/en.json') -Raw | ConvertFrom-Json
        $used = Select-String -Path (Join-Path $repo 'windows/*.ps1'), (Join-Path $repo 'windows/winpe/*.ps1') -Pattern "\bT '([a-z0-9_.]+)'" -CaseSensitive -AllMatches |
            ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
        foreach ($k in $used) { $en.PSObject.Properties.Name | Should -Contain $k }
    }
}

Describe 'Get-PeMachine' {
    It 'reads x64, x86, empty and invalid files' {
        New-Pe (Join-Path $TestDrive 'a64.dll') 0x8664
        New-Pe (Join-Path $TestDrive 'a86.dll') 0x14c
        [IO.File]::WriteAllBytes((Join-Path $TestDrive 'empty.dll'), [byte[]]@())
        [IO.File]::WriteAllText((Join-Path $TestDrive 'text.dll'), 'hello')
        Get-PeMachine (Join-Path $TestDrive 'a64.dll') | Should -Be 0x8664
        Get-PeMachine (Join-Path $TestDrive 'a86.dll') | Should -Be 0x14c
        Get-PeMachine (Join-Path $TestDrive 'empty.dll') | Should -Be 0
        Get-PeMachine (Join-Path $TestDrive 'text.dll') | Should -Be -1
    }
}

Describe 'Find-WrongArchDll' {
    It 'flags x86 in System32 and x64 in SysWOW64' {
        $win = Join-Path $TestDrive 'Windows'
        New-Item -ItemType Directory -Force -Path "$win/System32", "$win/SysWOW64" | Out-Null
        New-Pe "$win/System32/good.dll" 0x8664
        New-Pe "$win/System32/wintab32.dll" 0x14c
        New-Pe "$win/SysWOW64/good.dll" 0x14c
        New-Pe "$win/SysWOW64/bad64.dll" 0x8664
        $found = Find-WrongArchDll -WindowsDir $win | ForEach-Object { Split-Path $_.Path -Leaf }
        $found | Should -Contain 'wintab32.dll'
        $found | Should -Contain 'bad64.dll'
        $found | Should -Not -Contain 'good.dll'
    }
}

Describe 'Find-DriverStoreInf' {
    It 'finds display INF files declaring the hardware id, newest first' {
        $repo2 = Join-Path $TestDrive 'FileRepository'
        New-Item -ItemType Directory -Force -Path "$repo2/nv_old", "$repo2/nv_new", "$repo2/net" | Out-Null
        Set-Content "$repo2/nv_old/nv_dispi.inf" "[Version]`r`nClass=Display`r`nDriverVer=01/01/2022,30.0.0.1`r`n[NVIDIA]`r`n%dev%=Section,PCI\VEN_10DE&DEV_2484"
        Set-Content "$repo2/nv_new/nv_dispi.inf" "[Version]`r`nClass=Display`r`nDriverVer=06/01/2024,31.0.0.1`r`n[NVIDIA]`r`n%dev%=Section,PCI\VEN_10DE&DEV_2484&SUBSYS_146B10DE"
        Set-Content "$repo2/net/net.inf" "[Version]`r`nClass=Net`r`n%dev%=Section,PCI\VEN_10DE&DEV_2484"
        $infs = @(Find-DriverStoreInf -HwId 'VEN_10DE&DEV_2484' -Repository $repo2)
        $infs.Count | Should -Be 2
        $infs[0].Path | Should -Match 'nv_new'
    }
}

Describe 'WinPE script' {
    It 'parses without errors' {
        $tokens = $null; $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'windows/winpe/winpe-repair.ps1'), [ref]$tokens, [ref]$errors) | Out-Null
        $errors | Should -BeNullOrEmpty
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'windows/winpe/build-winpe.ps1'), [ref]$tokens, [ref]$errors) | Out-Null
        $errors | Should -BeNullOrEmpty
    }
}
