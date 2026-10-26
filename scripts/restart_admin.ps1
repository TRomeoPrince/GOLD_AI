param(
    [string]$ExePath,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
if (-not $ExePath) { $ExePath = Join-Path $repoRoot 'dist_utc\GOLD_AI_Admin.exe' }
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$prefix = $repoRoot + [IO.Path]::DirectorySeparatorChar
$old = @(Get-Process -Name 'GOLD_AI_Admin' -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } catch { $false }
})
if ($ValidateOnly) {
    [pscustomobject]@{ Executable = $resolvedExe; ExistingProcesses = $old.Count; Mode = 'Validation only; nothing closed or started' }
    return
}
foreach ($process in $old) {
    if ($process.MainWindowHandle -ne [IntPtr]::Zero) { $null = $process.CloseMainWindow() }
}
$deadline = [DateTime]::UtcNow.AddSeconds(40)
foreach ($process in $old) {
    $remaining = [Math]::Max(1, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds)
    if (-not $process.WaitForExit($remaining)) {
        throw 'Admin is still closing. Close its open dialogs/window and retry; nothing was force-killed.'
    }
}
Start-Process -FilePath $resolvedExe -WorkingDirectory $repoRoot -WindowStyle Normal
