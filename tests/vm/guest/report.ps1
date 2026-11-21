# Runs at every Windows start (scheduled task created by autounattend). Writes test markers to COM1.
$port = New-Object System.IO.Ports.SerialPort 'COM1', 115200, 'None', 8, 'One'
$port.Open()
function Say([string]$s) { $port.WriteLine($s) }
Say 'WINDOWS-BOOT-OK'
$deadline = (Get-Date).AddHours(2)
$runonce = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' -ErrorAction SilentlyContinue).'!winbootfix'
if ($runonce -or (Test-Path 'C:\winbootfix\state.json')) {
    while (-not (Get-ChildItem 'C:\winbootfix\reports\post-report-*.txt' -ErrorAction SilentlyContinue)) {
        if ((Get-Date) -gt $deadline) { Say 'WINDOWS-POST-TIMEOUT'; break }
        Start-Sleep -Seconds 30
    }
    Say 'WINDOWS-POST-DONE'
}
foreach ($d in Get-PnpDevice -Class Display -PresentOnly) {
    $svc = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Device_Service).Data
    $pb = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Device_ProblemCode).Data
    if ($svc -and $svc -ne 'BasicDisplay' -and -not $pb) { Say "WINDOWS-GPU-OK service=$svc" } else { Say "WINDOWS-GPU-BAD service=$svc problem=$pb" }
}
& sfc.exe /verifyfile=C:\Windows\System32\winver.exe | Out-Null
Say "WINDOWS-SFC-WINVER=$LASTEXITCODE"
Say "WINDOWS-TESTDLL-PRESENT=$(Test-Path 'C:\Windows\System32\wbftest32.dll')"
$port.Close()
