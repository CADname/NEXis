$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Base = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $env:LOCALAPPDATA 'NEXis\VisionEdge'
$Venv = Join-Path $Runtime 'venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Log = Join-Path $Runtime 'launcher.log'
$EdgeLog = Join-Path $Runtime 'edge.log'
$EdgeErr = Join-Path $Runtime 'edge-error.log'
$Install = Join-Path $Base 'INSTALL_VISION_EDGE.bat'
$Agent = Join-Path $Base 'vision_edge_agent.py'
$ServerFile = Join-Path $Base 'server_url.txt'
$ExampleServerFile = Join-Path $Base 'server_url.example.txt'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

function Resolve-ServerUrl {
  if ($env:NEXIS_SERVER_URL) { return $env:NEXIS_SERVER_URL.Trim().TrimEnd('/') }
  if (Test-Path $ServerFile) {
    $v = (Get-Content -Raw -Encoding UTF8 $ServerFile).Trim().TrimEnd('/')
    if ($v) { return $v }
  }
  throw "Create edge_vision\server_url.txt from server_url.example.txt and set the NEXis server URL, or define NEXIS_SERVER_URL."
}

$Server = Resolve-ServerUrl
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] NEXis Vision launcher started" | Set-Content -Encoding UTF8 $Log
"Server=$Server" | Add-Content -Encoding UTF8 $Log

$form = New-Object System.Windows.Forms.Form
$form.Text = 'NEXis Vision Connector'
$form.StartPosition = 'CenterScreen'
$form.Size = [System.Drawing.Size]::new(540,220)
$form.MinimumSize = [System.Drawing.Size]::new(540,220)
$form.MaximumSize = [System.Drawing.Size]::new(540,270)
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(15,22,29)
$form.ForeColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Preparing NEXis Vision'
$title.Font = [System.Drawing.Font]::new('Segoe UI',14,[System.Drawing.FontStyle]::Bold)
$title.Location = [System.Drawing.Point]::new(24,20)
$title.Size = [System.Drawing.Size]::new(480,28)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Starting...'
$status.Font = [System.Drawing.Font]::new('Segoe UI',10)
$status.Location = [System.Drawing.Point]::new(24,61)
$status.Size = [System.Drawing.Size]::new(480,42)
$form.Controls.Add($status)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Location = [System.Drawing.Point]::new(24,111)
$bar.Size = [System.Drawing.Size]::new(480,20)
$bar.Minimum = 0
$bar.Maximum = 100
$bar.Value = 2
$form.Controls.Add($bar)

$detail = New-Object System.Windows.Forms.Label
$detail.Text = 'The first run may take a few minutes while vision dependencies are installed.'
$detail.Font = [System.Drawing.Font]::new('Segoe UI',8)
$detail.ForeColor = [System.Drawing.Color]::FromArgb(145,160,172)
$detail.Location = [System.Drawing.Point]::new(24,140)
$detail.Size = [System.Drawing.Size]::new(480,55)
$form.Controls.Add($detail)

function Pump { [System.Windows.Forms.Application]::DoEvents() }
function Step([int]$value,[string]$message,[string]$sub='') {
  $bar.Style = 'Blocks'
  $bar.Value = [Math]::Max(0,[Math]::Min(100,$value))
  $status.Text = $message
  if ($sub) { $detail.Text = $sub }
  Pump
}
function Fail([string]$message) {
  $status.Text = 'Launch failed'
  $status.ForeColor = [System.Drawing.Color]::FromArgb(255,100,100)
  $detail.Text = $message + "`r`nLog: " + $Log
  "ERROR: $message" | Add-Content -Encoding UTF8 $Log
  Pump
}

$form.Add_Shown({
  try {
    Step 8 '1/5 - Checking local Vision Edge' 'Stopping duplicate edge processes and checking the local environment.'
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -and $_.CommandLine.Contains('vision_edge_agent.py')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 300

    $depsOk = $false
    if (Test-Path $Py) {
      & $Py -c "import cv2,numpy,requests,ultralytics,mediapipe as mp; assert hasattr(mp, 'solutions')" *> $null
      $depsOk = ($LASTEXITCODE -eq 0)
    }

    if (-not $depsOk) {
      Step 20 '2/5 - Installing vision dependencies' 'This runs only when the local environment is missing or incomplete.'
      $bar.Style = 'Marquee'
      $bar.MarqueeAnimationSpeed = 25
      $cmdLine = 'call "' + $Install + '" >> "' + $Log + '" 2>&1'
      $proc = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d','/s','/c',('"' + $cmdLine + '"')) -WindowStyle Hidden -PassThru
      while (-not $proc.HasExited) {
        Pump
        Start-Sleep -Milliseconds 500
        $proc.Refresh()
      }
      $bar.Style = 'Blocks'
      $bar.Value = 55
      if ($proc.ExitCode -ne 0 -or -not (Test-Path $Py)) { throw 'Vision dependency installation failed.' }
      & $Py -c "import cv2,numpy,requests,ultralytics,mediapipe as mp; assert hasattr(mp, 'solutions')" *> $null
      if ($LASTEXITCODE -ne 0) { throw 'Vision dependency verification failed.' }
    } else {
      Step 55 '2/5 - Vision dependencies ready' 'Reusing the existing local environment.'
    }

    Step 68 '3/5 - Connecting to NEXis' $Server
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $null = Invoke-RestMethod -Method Post -Uri ($Server + '/api/enter/physical') -WebSession $session -TimeoutSec 10
    $edgeInfo = Invoke-RestMethod -Method Get -Uri ($Server + '/api/vision/edge-info') -WebSession $session -TimeoutSec 10
    $token = [string]$edgeInfo.token
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'The server did not provide a Vision Edge token.' }
    try { $null = Invoke-RestMethod -Method Post -Uri ($Server + '/api/workspace/leave') -WebSession $session -TimeoutSec 5 } catch {}

    Step 80 '4/5 - Starting camera discovery' 'Available cameras will appear in the Vision Safety page.'
    $args = @($Agent,'--server',$Server,'--token',$token,'--camera','auto','--preview-port','8765')
    Start-Process -FilePath $Py -ArgumentList $args -WorkingDirectory $Base -WindowStyle Hidden -RedirectStandardOutput $EdgeLog -RedirectStandardError $EdgeErr | Out-Null

    $localReady = $false
    for ($i = 0; $i -lt 40; $i++) {
      try {
        $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 1
        if ($h.ok) { $localReady = $true; break }
      } catch {}
      Pump
      Start-Sleep -Milliseconds 300
    }
    if (-not $localReady) { throw 'The local Vision Edge service did not start. Check edge-error.log.' }

    Step 94 '5/5 - Opening Vision Safety' 'Select the intended camera from the browser.'
    Start-Process ($Server + '/?workspace=physical&page=vision&auto=1')
    Step 100 'Connected' 'Vision Edge is running in the background.'
    Start-Sleep -Milliseconds 1200
    $form.Close()
  } catch {
    Fail $_.Exception.Message
  }
})

[void]$form.ShowDialog()
