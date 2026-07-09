# Invoked by Task Scheduler — see install_scheduled_task.ps1
param()

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot = Split-Path $Root -Parent
$PreferredLogDir = Join-Path $RepoRoot "data\pilot\logs"
$FallbackLogDir = Join-Path $Root "logs"
$AppDataLogDir = Join-Path $env:LOCALAPPDATA "WBAdvert\logs"
$TempLogDir = Join-Path $env:TEMP "wb-advert\logs"
$script:LogDir = $null
$script:LogFile = $null
$script:LogWriter = $null
$Utf8WithBom = New-Object System.Text.UTF8Encoding $true

function Initialize-PythonUtf8 {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    try {
        chcp 65001 | Out-Null
    } catch {
        # ignore on hosts without chcp
    }
    $utf8 = [System.Text.Encoding]::UTF8
    $OutputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
}

function Test-LogDirWritable {
    param([string]$Dir)
    if ([string]::IsNullOrWhiteSpace($Dir)) {
        return $false
    }
    try {
        if (-not (Test-Path -Path $Dir)) {
            $null = [System.IO.Directory]::CreateDirectory($Dir)
        }
        $probe = Join-Path $Dir (".write_probe_" + [guid]::NewGuid().ToString("N"))
        [System.IO.File]::WriteAllText($probe, "ok", $Utf8WithBom)
        Remove-Item -Path $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Resolve-LogDir {
    foreach ($dir in @($PreferredLogDir, $FallbackLogDir, $AppDataLogDir, $TempLogDir)) {
        if (Test-LogDirWritable -Dir $dir) {
            $script:LogDir = $dir
            $script:LogFile = Join-Path $dir ("cycle_" + (Get-Date -Format "yyyy-MM-dd") + ".log")
            return
        }
    }
    $script:LogDir = $null
    $script:LogFile = $null
}

function Get-LogWriter {
    if (-not $script:LogFile) {
        return $null
    }
    if (-not $script:LogWriter) {
        $script:LogWriter = New-Object System.IO.StreamWriter($script:LogFile, $true, $Utf8WithBom)
    }
    return $script:LogWriter
}

function Write-CycleLog {
    param([string]$Message)
    $writer = Get-LogWriter
    if (-not $writer) {
        return
    }
    try {
        $writer.WriteLine($Message)
        $writer.Flush()
    } catch {
        # Console output from run_daily_cycle.ps1 is enough if file logging is blocked.
    }
}

function Close-CycleLog {
    if ($script:LogWriter) {
        try {
            $script:LogWriter.Flush()
            $script:LogWriter.Close()
        } catch {
            # ignore
        }
        $script:LogWriter = $null
    }
}

function Invoke-LoggedPowerShell {
    param(
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ScriptArgs
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "powershell.exe"
    $psi.Arguments = ($argList | ForEach-Object {
        if ($_ -match '\s') { "`"$_`"" } else { $_ }
    }) -join " "
    $psi.WorkingDirectory = $Root
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    while (-not $proc.StandardOutput.EndOfStream) {
        $line = $proc.StandardOutput.ReadLine()
        if ($null -ne $line) {
            Write-Host $line
            Write-CycleLog $line
        }
    }
    while (-not $proc.StandardError.EndOfStream) {
        $line = $proc.StandardError.ReadLine()
        if ($null -ne $line) {
            Write-Host $line
            Write-CycleLog $line
        }
    }
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) {
        Write-Host "Cycle script exit code: $($proc.ExitCode)" -ForegroundColor Yellow
        Write-CycleLog "Cycle script exit code: $($proc.ExitCode)"
    }
}

try {
    Set-Location -Path $Root
    Initialize-PythonUtf8
    Resolve-LogDir

    if ($script:LogFile) {
        Write-Host "Cycle log: $script:LogFile" -ForegroundColor DarkGray
    } else {
        Write-Host "Cycle log: disabled (no writable log directory)" -ForegroundColor Yellow
    }

    Write-CycleLog ""
    Write-CycleLog "========== $(Get-Date -Format o) =========="
    Write-CycleLog "Root=$Root LogDir=$script:LogDir"

    Invoke-LoggedPowerShell -ScriptPath (Join-Path $Root "run_daily_cycle.ps1") -ScriptArgs @()

    Write-CycleLog "========== cycle finished =========="
} finally {
    Close-CycleLog
}
