$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Base = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $env:LOCALAPPDATA 'NEXis\VisionEdge'
$Venv = Join-Path $Runtime 'venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Log = Join-Path $Runtime 'launcher.log'
$InstallLog = Join-Path $Runtime 'install.log'
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
$form.Text = 'NEXis Vision Connection'
$form.StartPosition = 'CenterScreen'
$form.Size = [System.Drawing.Size]::new(520,210)
$form.MinimumSize = [System.Drawing.Size]::new(520,210)
$form.MaximumSize = [System.Drawing.Size]::new(520,330)
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(15,22,29)
$form.ForeColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Preparing NEXis Camera Connection'
$title.Font = [System.Drawing.Font]::new('Segoe UI',14,[System.Drawing.FontStyle]::Bold)
$title.Location = [System.Drawing.Point]::new(24,20)
$title.Size = [System.Drawing.Size]::new(460,28)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Starting...'
$status.Font = [System.Drawing.Font]::new('Segoe UI',10)
$status.Location = [System.Drawing.Point]::new(24,61)
$status.Size = [System.Drawing.Size]::new(460,42)
$form.Controls.Add($status)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Location = [System.Drawing.Point]::new(24,111)
$bar.Size = [System.Drawing.Size]::new(460,20)
$bar.Minimum = 0
$bar.Maximum = 100
$bar.Value = 2
$form.Controls.Add($bar)

$detail = New-Object System.Windows.Forms.Label
$detail.Text = 'Reusing the existing local Vision environment when available.'
$detail.Font = [System.Drawing.Font]::new('Segoe UI',8)
$detail.ForeColor = [System.Drawing.Color]::FromArgb(145,160,172)
$detail.Location = [System.Drawing.Point]::new(24,140)
$detail.Size = [System.Drawing.Size]::new(460,125)
$form.Controls.Add($detail)

function Pump { [System.Windows.Forms.Application]::DoEvents() }
function Step([int]$value,[string]$message,[string]$sub='') {
  if ($value -ge 0) { $bar.Style='Blocks'; $bar.Value=[Math]::Max(0,[Math]::Min(100,$value)) }
  $status.Text=$message
  if($sub){$detail.Text=$sub}
  Pump
}
function Tail-Text([string]$path,[int]$lines=14) {
  if(-not(Test-Path $path)){return ''}
  try{return((Get-Content -LiteralPath $path -Tail $lines -ErrorAction SilentlyContinue)-join "`r`n")}catch{return ''}
}
function Fail([string]$message,[string]$extra='') {
  $status.Text='Launch Failed'
  $status.ForeColor=[System.Drawing.Color]::FromArgb(255,100,100)
  $msg=$message
  if($extra){$msg+="`r`n"+$extra}
  $detail.Text=$msg+"`r`nLog: "+$Log
  $form.Size=[System.Drawing.Size]::new(520,305)
  "ERROR: $message" | Add-Content -Encoding UTF8 $Log
  if($extra){$extra | Add-Content -Encoding UTF8 $Log}
  Pump
}

$form.Add_Shown({
  try {
    Step 10 '1/4 - Checking local Vision environment' 'Existing environments are reused without package probes or automatic repair.'
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -and $_.CommandLine.Contains('vision_edge_agent.py')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 250

    if(-not(Test-Path $Py)) {
      Step 25 'Creating Vision environment' 'This runs only when no local Vision Python environment exists.'
      if(-not(Test-Path $Install)){throw 'INSTALL_VISION_EDGE.bat is missing.'}
      $proc=Start-Process -FilePath $Install -ArgumentList @('/quiet') -WorkingDirectory $Base -WindowStyle Hidden -PassThru -Wait
      if($proc.ExitCode -ne 0 -or -not(Test-Path $Py)) {
        $why=Tail-Text $InstallLog 16
        if(-not $why){$why='Vision environment creation failed.'}
        throw "Vision environment could not be created.`r`n$why"
      }
    }

    Step 45 '2/4 - Connecting to NEXis server' $Server
    $session=New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $null=Invoke-RestMethod -Method Post -Uri ($Server+'/api/enter/physical') -WebSession $session -TimeoutSec 10
    $edgeInfo=Invoke-RestMethod -Method Get -Uri ($Server+'/api/vision/edge-info') -WebSession $session -TimeoutSec 10
    $token=[string]$edgeInfo.token
    if([string]::IsNullOrWhiteSpace($token)){throw 'Failed to receive a Vision Edge token from the server.'}
    try{$null=Invoke-RestMethod -Method Post -Uri ($Server+'/api/workspace/leave') -WebSession $session -TimeoutSec 5}catch{}

    Step 70 '3/4 - Starting local camera service' 'Camera enumeration runs at startup and only after an explicit Refresh Cameras request.'
    Remove-Item -Force -ErrorAction SilentlyContinue $EdgeLog,$EdgeErr
    $args=@($Agent,'--server',$Server,'--token',$token,'--camera','auto','--preview-port','8765')
    $edgeProc=Start-Process -FilePath $Py -ArgumentList $args -WorkingDirectory $Base -WindowStyle Hidden -RedirectStandardOutput $EdgeLog -RedirectStandardError $EdgeErr -PassThru
    $localReady=$false
    for($i=0;$i-lt 60;$i++){
      if($edgeProc.HasExited){break}
      try{
        $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 1
        if($h.ok){$localReady=$true;break}
      }catch{}
      Pump
      Start-Sleep -Milliseconds 300
    }
    if(-not $localReady){
      $errTail=Tail-Text $EdgeErr 18
      if(-not $errTail){$errTail=Tail-Text $EdgeLog 18}
      if(-not $errTail){$errTail='The local Vision process exited before the health endpoint became ready.'}
      Fail 'The local camera service did not start.' $errTail
      return
    }

    Step 92 '4/4 - Opening Vision Safety' 'Select the intended camera from the web interface.'
    Start-Process ($Server+'/?workspace=physical&page=vision&auto=1')
    Step 100 'Connection Complete' 'Vision Edge is running in the background.'
    Start-Sleep -Milliseconds 1000
    $form.Close()
  } catch {
    Fail $_.Exception.Message
  }
})
[void]$form.ShowDialog()
