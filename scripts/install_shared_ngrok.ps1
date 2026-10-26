param(
    [Parameter(Mandatory=$true)][string]$NgrokExe,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [string]$TaskName = 'Shared-ngrok',
    [switch]$StartNow
)
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path -LiteralPath $NgrokExe).Path
$config = (Resolve-Path -LiteralPath $ConfigPath).Path
& $exe config check --config $config
if ($LASTEXITCODE -ne 0) { throw 'ngrok configuration validation failed' }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Task $TaskName exists. Review/remove it before replacing it."
}
# A non-interactive SYSTEM task has no visible console and starts before login.
# The chosen config and executable must be readable by SYSTEM.
$logDir = Join-Path $env:ProgramData 'Shared-ngrok'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir 'ngrok.log'
$action = New-ScheduledTaskAction -Execute $exe -Argument ('start --all --config "{0}" --log "{1}" --log-format json' -f $config,$logPath)
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Shared ngrok agent: tunnels from one explicit config, independent of GOLD_AI.' | Out-Null
if ($StartNow) { Start-ScheduledTask -TaskName $TaskName }
Write-Output "Installed $TaskName; logs: $logPath"
