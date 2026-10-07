<#
.SYNOPSIS
  Register (or remove) the figure-queue tick: one pass of figure_queue.py
  every few minutes under Windows Task Scheduler.

.DESCRIPTION
  A runner that lives for days stops everything when it dies and has to be
  started by hand after every reboot. The tick is a short process instead:
  land finished replies, top the server queue up, exit. One that fails costs
  one interval.

    powershell -ExecutionPolicy Bypass -File scripts\install-figure-tick.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install-figure-tick.ps1 -Remove

  It runs as you, while you are logged on, through pythonw — no console window
  every five minutes. Output goes to <data>\logs\figure_queue.log.

  Pause without unregistering: create <data>\figure_queue.stop (ticks skip
  while it exists); delete it to resume.

  Stop a long-running `figure_queue.py --execute` before registering: the two
  share a lock, so ticks would only find it busy and exit.
#>
param(
    [int]$Minutes = 5,
    [string]$Python = "$env:USERPROFILE\anaconda3\envs\PaperMeister\pythonw.exe",
    [switch]$Remove
)

$TaskName = 'PaperMeister Figure Queue'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'."
    return
}

if (-not (Test-Path $Python)) {
    throw "pythonw not found at $Python — pass -Python <path to the env's pythonw.exe>"
}
$Repo = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Repo 'scripts\figure_queue.py'

$action = New-ScheduledTaskAction -Execute $Python `
    -Argument "`"$Script`" --tick --execute" -WorkingDirectory $Repo
# A repeating trigger with no end: it carries on across reboots, and
# -StartWhenAvailable runs a missed tick as soon as the machine is back.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
# IgnoreNew: Task Scheduler does not start a tick while the last one runs (the
# script's own lock would turn it away anyway). The time limit only catches a
# tick that hangs on the network — a pass normally ends well inside its budget.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Force `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Host "Registered '$TaskName': every $Minutes min, $Python $Script --tick --execute"
