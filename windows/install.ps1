# windows/install.ps1: puts agent-desktop on the G14 (Windows 11, Windows PowerShell 5.1). Run it by hand, once; run it again
# any time. chezmoi never deploys this folder. Docs: docs/agent-desktop.md, section "G14".
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File windows\install.ps1
#
# It
#   1. copies agent-desktop.ps1 and agent-desktop.cmd (the files next to this one) into %USERPROFILE%\.local\bin;
#   2. downloads Vercel's agent-desktop v1.3.1 (x86_64-pc-windows-msvc), checks it against the release's checksums.txt and
#      unpacks agent-desktop.exe into %USERPROFILE%\.local\share\agent-desktop\vercel\;
#   3. registers the scheduled task "agent-desktop", set to run only when the user is logged on, so it runs inside the desktop
#      session and can see and drive the screen. The task has no trigger: each agent-desktop call starts it;
#   4. adds %USERPROFILE%\.local\bin to the user PATH when it is not there.
# A second run changes nothing, downloads nothing and says so. It touches no sign-in, PIN, sleep, power or remote-desktop setting.
#
# Exit: 0 ok; 1 failed (a bad checksum leaves no tool behind); 69 curl.exe or tar.exe is missing.
$ErrorActionPreference = 'Stop'

$script:Name = 'install.ps1'
$VercelVersion = '1.3.1'
$ReleaseBase = "https://github.com/vercel-labs/agent-desktop/releases/download/v$VercelVersion"
$Asset = "agent-desktop-v$VercelVersion-x86_64-pc-windows-msvc.tar.gz"
$TaskName = 'agent-desktop'
$changed = New-Object Collections.Generic.List[string]

function Write-Info([string]$Message) { [Console]::Out.WriteLine("[$script:Name] INFO: $Message") }

function Exit-Fail([int]$Code, [string]$Message) {
    [Console]::Error.WriteLine("[$script:Name] ERROR: $Message")
    exit $Code
}

function Join-All([string]$Base, [string[]]$Parts) {
    $p = $Base
    foreach ($part in $Parts) { $p = Join-Path $p $part }
    $p
}

$userHome = $env:USERPROFILE
if (-not $userHome) { $userHome = $HOME }
$binDir = Join-All $userHome @('.local', 'bin')
$vercelDir = Join-All $userHome @('.local', 'share', 'agent-desktop', 'vercel')
$here = $PSScriptRoot

# ---- 1. the scripts -------------------------------------------------------------------------------------------------------
[void](New-Item -ItemType Directory -Force -Path $binDir)
foreach ($file in 'agent-desktop.ps1', 'agent-desktop.cmd') {
    $source = Join-Path $here $file
    $target = Join-Path $binDir $file
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Exit-Fail 1 "$source is missing; run this script from a full copy of the windows folder" }
    $state = 'unchanged'
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { $state = 'installed' }
    elseif ((Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash) { $state = 'updated' }
    if ($state -ne 'unchanged') {
        Copy-Item -LiteralPath $source -Destination $target -Force
        $changed.Add("$file $state")
    }
    Write-Info "$file ${state}: $target"
}

# ---- 2. Vercel's tool -----------------------------------------------------------------------------------------------------
$exe = Join-Path $vercelDir 'agent-desktop.exe'
$marker = Join-Path $vercelDir 'version.txt'
$have = $false
if ((Test-Path -LiteralPath $exe -PathType Leaf) -and (Test-Path -LiteralPath $marker -PathType Leaf)) {
    $have = ([IO.File]::ReadAllText($marker).Trim() -eq $VercelVersion)
}
if ($have) {
    Write-Info "Vercel agent-desktop v$VercelVersion already installed: $exe"
} else {
    foreach ($tool in 'curl.exe', 'tar.exe') {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            Exit-Fail 69 "$tool is not on PATH. Windows 11 ships it in System32; check the PATH of this session."
        }
    }
    $stage = Join-Path ([IO.Path]::GetTempPath()) ('agent-desktop-install-' + [Guid]::NewGuid().ToString('N'))
    [void](New-Item -ItemType Directory -Force -Path $stage)
    try {
        $archive = Join-Path $stage $Asset
        $sums = Join-Path $stage 'checksums.txt'
        foreach ($pair in @(@("$ReleaseBase/$Asset", $archive), @("$ReleaseBase/checksums.txt", $sums))) {
            & curl.exe --fail --location --silent --show-error --output $pair[1] $pair[0]
            if ($LASTEXITCODE -ne 0) { Exit-Fail 1 "download failed (curl.exe exit $LASTEXITCODE): $($pair[0])" }
        }
        $want = $null
        foreach ($line in [IO.File]::ReadAllLines($sums)) {
            $cells = $line.Trim() -split '\s+'
            if ($cells.Count -ge 2 -and $cells[1].TrimStart('*') -eq $Asset) { $want = $cells[0] }
        }
        if (-not $want) { Exit-Fail 1 "checksums.txt of release v$VercelVersion has no line for $Asset" }
        $got = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
        if ($got -ne $want.ToUpperInvariant()) { Exit-Fail 1 "checksum mismatch for ${Asset}: checksums.txt says $want, the download is $got. Nothing was installed." }
        Write-Info "checksum ok: $got"
        $unpacked = Join-Path $stage 'unpacked'
        [void](New-Item -ItemType Directory -Force -Path $unpacked)
        & tar.exe -xzf $archive -C $unpacked
        if ($LASTEXITCODE -ne 0) { Exit-Fail 1 "tar.exe could not unpack $Asset (exit $LASTEXITCODE)" }
        $found = Get-ChildItem -LiteralPath $unpacked -Recurse -Filter 'agent-desktop.exe' | Select-Object -First 1
        if (-not $found) { Exit-Fail 1 "$Asset holds no agent-desktop.exe" }
        [void](New-Item -ItemType Directory -Force -Path $vercelDir)
        Copy-Item -LiteralPath $found.FullName -Destination $exe -Force
        [IO.File]::WriteAllText($marker, $VercelVersion)
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    $changed.Add("Vercel agent-desktop v$VercelVersion installed")
    Write-Info "Vercel agent-desktop v$VercelVersion installed: $exe"
}

# ---- 3. the scheduled task ------------------------------------------------------------------------------------------------
$program = 'powershell.exe'
$taskArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $binDir 'agent-desktop.ps1') + '" --worker'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$same = $false
if ($existing -and @($existing.Actions).Count -ge 1) {
    $a = @($existing.Actions)[0]
    $same = ($a.Execute -eq $program) -and ($a.Arguments -eq $taskArguments)
}
if ($same) {
    Write-Info "scheduled task '$TaskName' unchanged"
} else {
    # COMPUTERNAME, not USERDOMAIN: an OpenSSH session sets USERDOMAIN to WORKGROUP, which names no account.
    $action = New-ScheduledTaskAction -Execute $program -Argument $taskArguments
    $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    # Parallel: each call starts its own worker. Battery: the G14 is a laptop and must run the task unplugged.
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances Parallel -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    [void](Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Settings $settings -Force)
    $verb = 'registered'
    if ($existing) { $verb = 'registered again (its command differed)' }
    $changed.Add("scheduled task $verb")
    Write-Info "scheduled task '$TaskName' $verb"
}

# ---- 4. the user PATH -----------------------------------------------------------------------------------------------------
$regKey = 'HKCU\Environment'
$current = ''
$kind = 'REG_EXPAND_SZ'
# Read through a process object: on 5.1 a redirected native stderr turns into error records, which stop the script.
$psi = New-Object Diagnostics.ProcessStartInfo 'reg.exe'
$psi.Arguments = "query $regKey /v Path"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$proc = [Diagnostics.Process]::Start($psi)
$queried = $proc.StandardOutput.ReadToEndAsync()
$ignored = $proc.StandardError.ReadToEndAsync()
$proc.WaitForExit()
if ($proc.ExitCode -eq 0) {   # a non-zero exit means the user has no Path value yet
    foreach ($line in ($queried.Result -split "`r?`n")) {
        if ($line -match '^\s*Path\s+(REG_SZ|REG_EXPAND_SZ)\s+(.*)$') { $kind = $Matches[1]; $current = $Matches[2].Trim() }
    }
}
$onPath = $false
$names = @($binDir.TrimEnd('\', '/'), '%USERPROFILE%\.local\bin')
foreach ($entry in ($current -split ';')) {
    if ($names -contains $entry.Trim().TrimEnd('\', '/')) { $onPath = $true }
}
if ($onPath) {
    Write-Info "$binDir is on the user PATH"
} else {
    $new = $binDir
    if ($current) { $new = $current.TrimEnd(';') + ';' + $binDir }
    # reg.exe keeps the kind of the value (REG_EXPAND_SZ), so entries such as %USERPROFILE%\bin keep working
    & reg.exe add $regKey /v Path /t $kind /d $new /f | Out-Null
    if ($LASTEXITCODE -ne 0) { Exit-Fail 1 "could not add $binDir to the user PATH (reg.exe exit $LASTEXITCODE)" }
    $changed.Add('user PATH')
    Write-Info "added $binDir to the user PATH; a new ssh session or sign-in sees it"
}

# ---- done -----------------------------------------------------------------------------------------------------------------
if ($changed.Count -eq 0) {
    Write-Info 'Nothing changed.'
} else {
    Write-Info ('Changed: ' + ($changed -join '; ') + '.')
}
Write-Info 'Check it while the G14 is unlocked: agent-desktop cursor'
