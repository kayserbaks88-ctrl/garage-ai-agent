$ErrorActionPreference = 'Stop'
$artifactRoot = Join-Path $PSScriptRoot '../../.release-validation/pwa-preview'
$null = New-Item -ItemType Directory -Force -Path $artifactRoot
$info = $null
for($attempt=0;$attempt -lt 60;$attempt++) {
 try {$info=Invoke-RestMethod 'http://127.0.0.1:55511/json/version';break} catch {Start-Sleep -Milliseconds 500}
}
if(!$info){throw 'Isolated browser diagnostics did not start on loopback port 55511.'}
$socket = New-Object System.Net.WebSockets.ClientWebSocket
$cancel = [System.Threading.CancellationToken]::None
$socket.ConnectAsync([Uri]$info.webSocketDebuggerUrl, $cancel).GetAwaiter().GetResult()
$script:sequence = 0
function Receive-Cdp {
    $buffer = New-Object byte[] 1048576
    $stream = New-Object System.IO.MemoryStream
    $deadline = New-Object System.Threading.CancellationTokenSource
    $deadline.CancelAfter(30000)
    try {
    do {
        $segment = New-Object 'System.ArraySegment[byte]' -ArgumentList @(,$buffer)
        $received = $socket.ReceiveAsync($segment, $deadline.Token).GetAwaiter().GetResult()
        if($received.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close){throw 'Isolated browser closed the diagnostics connection.'}
        $stream.Write($buffer, 0, $received.Count)
    } until ($received.EndOfMessage)
    $json = [Text.Encoding]::UTF8.GetString($stream.ToArray())
    return ($json | ConvertFrom-Json)
    } finally {$deadline.Dispose();$stream.Dispose()}
}
function Send-Cdp($method, $parameters, $sessionId = $null) {
    $script:sequence += 1
    $message = @{id=$script:sequence; method=$method; params=$parameters}
    if ($sessionId) { $message.sessionId = $sessionId }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($message | ConvertTo-Json -Depth 20 -Compress))
    $segment = New-Object 'System.ArraySegment[byte]' -ArgumentList @(,$bytes)
    $socket.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cancel).GetAwaiter().GetResult()
    do { $reply = Receive-Cdp } until ($reply.id -eq $script:sequence)
    if ($reply.error) { throw ($reply.error | ConvertTo-Json -Compress) }
    return $reply.result
}
function Wait-PwaPage($sessionId,$expectedPath) {
 for($attempt=0;$attempt -lt 100;$attempt++) {
  $state=Send-Cdp 'Runtime.evaluate' @{expression='({ready:document.readyState,path:location.pathname})';returnByValue=$true} $sessionId
  if($state.result.value.ready -eq 'complete' -and $state.result.value.path -eq $expectedPath){return}
  Start-Sleep -Milliseconds 100
 }
 throw "Page did not finish navigation to $expectedPath"
}

$results=@()
$layoutFailures=@()
try {
 $target=Send-Cdp 'Target.createTarget' @{url='about:blank'}
 $attached=Send-Cdp 'Target.attachToTarget' @{targetId=$target.targetId;flatten=$true}
 $sid=$attached.sessionId
 $null=Send-Cdp 'Page.enable' @{} $sid
 $null=Send-Cdp 'Network.enable' @{} $sid
 foreach($width in @(360,393,768,1440)) {
  $null=Send-Cdp 'Emulation.setDeviceMetricsOverride' @{width=$width;height=900;deviceScaleFactor=1;mobile=($width -lt 600)} $sid
  foreach($path in @('/staff/employee/app','/staff/employee/app/install','/qa/employee','/staff/alpha/employee/clocking','/staff/alpha/employee/hours','/staff/alpha/employee/rota','/staff/alpha/employee/pay','/staff/alpha/employee/leave','/qa/manager','/staff/alpha','/staff/alpha/employees','/staff/alpha/attendance','/staff/alpha/approvals','/staff/alpha/agency','/staff/alpha/payroll','/staff/alpha/settings','/qa/both','/qa/login')) {
   $expectedPath=switch($path){'/qa/manager'{'/staff/account'} '/qa/employee'{'/staff/alpha/employee'} '/qa/both'{'/staff/employee/app'} '/qa/login'{'/staff/employee/app'} default{$path}}
   $null=Send-Cdp 'Page.navigate' @{url=('http://127.0.0.1:55510'+$path)} $sid
   Wait-PwaPage $sid $expectedPath
   $check=Send-Cdp 'Runtime.evaluate' @{expression='JSON.stringify({path:location.pathname,width:innerWidth,scroll:document.documentElement.scrollWidth,heading:document.querySelector("h1")?.textContent,hasManifest:!!document.querySelector("link[rel=manifest]"),mobileNav:document.querySelector(".employee-mobile-nav") ? getComputedStyle(document.querySelector(".employee-mobile-nav")).display : null})';returnByValue=$true} $sid
   $metrics=$check.result.value|ConvertFrom-Json
   $expectedPath=switch($path){'/qa/manager'{'/staff/account'} '/qa/employee'{'/staff/alpha/employee'} '/qa/both'{'/staff/employee/app'} '/qa/login'{'/staff/employee/app'} default{$path}}
   if($metrics.path -ne $expectedPath){$layoutFailures+=@{width=$width;path=$path;unexpectedDestination=$metrics.path}}
   if($metrics.scroll -gt $width -or !$metrics.hasManifest -or !$metrics.heading){$layoutFailures+=@{width=$width;path=$path;metrics=$metrics}}
   $results+=@{width=$width;path=$path;metrics=$metrics}
   if($path -in @('/staff/employee/app','/staff/employee/app/install','/qa/employee') -and $width -in @(393,1440)) {
    $shot=Send-Cdp 'Page.captureScreenshot' @{format='png'} $sid
    $name=($path -replace '/','-')+'-'+$width+'.png'
    [IO.File]::WriteAllBytes((Join-Path $artifactRoot $name),[Convert]::FromBase64String($shot.data))
   }
  }
 }
 $ready=Send-Cdp 'Runtime.evaluate' @{expression='Promise.race([navigator.serviceWorker.ready.then(()=>new Promise(resolve=>{if(navigator.serviceWorker.controller)resolve(true);else navigator.serviceWorker.addEventListener("controllerchange",()=>resolve(true),{once:true});})),new Promise(resolve=>setTimeout(()=>resolve(false),15000))])';awaitPromise=$true;returnByValue=$true} $sid
 if(!$ready.result.value){throw 'Worker not controlling page'}
 $expression=@'
(async()=>{
 const handlers={};const calls=[];
 const fake={location:{origin:location.origin},addEventListener:(name,fn)=>handlers[name]=fn};
 const self=fake;
 const fetch=async(req,options)=>{calls.push(options);throw Error('offline');};
 __TEST_WORKER_SOURCE__
 const cases=[['GET','navigate','/staff/alpha/employee/clocking',true],['GET','navigate','/staff/employee/app',true],['GET','navigate','/staff/alpha',true],['GET','navigate','/staff/account/login',true],['GET','navigate','/staff/alpha/approvals',true],['GET','navigate','/staff/alpha/payroll',true],['GET','navigate','/staff/alpha/agency',true],['POST','navigate','/staff/alpha/employee/clock-in',false],['POST','cors','/staff/alpha/employee/presence',false],['POST','navigate','/staff/alpha/payroll',false],['GET','navigate','/staff/alpha/api/presence',false],['GET','navigate','/staff/alpha/employee/payslips/1/download',false],['GET','navigate','/staff/alpha/employee/payslips/1/view',false],['GET','navigate','/staff/account/register',false],['GET','navigate','/staff/platform',false],['GET','navigate','/staff/alpha/subscription',false],['GET','navigate','/staff/alpha/dashboard',false],['GET','navigate','/paychaser',false],['GET','navigate','/staff/alpha/setup',false],['GET','cors','/staff/alpha/employee/clocking',false]];
 for(const [method,mode,path,expected] of cases){let reply;handlers.fetch({request:{url:location.origin+path,method,mode},respondWith:r=>reply=r});if(!!reply!==expected)throw Error('Intercept mismatch '+path);if(reply){const r=await reply;if(r.status!==503||!(await r.text()).includes('Reconnect to continue'))throw Error('Fallback mismatch');}}
 if(calls.some(c=>c.cache!=='no-store'))throw Error('Cache policy');
 return {workerCases:cases.length,caches:await caches.keys(),databases:await indexedDB.databases()};
})()
'@
 # Compile the trusted loopback worker directly through DevTools. Do not use
 # browser eval/new Function or weaken the preview's Content Security Policy.
 $workerSource=(Invoke-WebRequest 'http://127.0.0.1:55510/staff/employee-sw.js' -UseBasicParsing).Content
 $expression=$expression.Replace('__TEST_WORKER_SOURCE__',$workerSource)
 $worker=Send-Cdp 'Runtime.evaluate' @{expression=$expression;awaitPromise=$true;returnByValue=$true} $sid
 if($worker.exceptionDetails){throw ($worker.exceptionDetails|ConvertTo-Json -Depth 5)}
 if($worker.result.value.caches.Count -or $worker.result.value.databases.Count){throw 'Unexpected offline storage'}
 $null=Send-Cdp 'Page.navigate' @{url='http://127.0.0.1:55510/qa/employee'} $sid
 Wait-PwaPage $sid '/staff/alpha/employee'
 $null=Send-Cdp 'Page.navigate' @{url='http://127.0.0.1:55510/staff/alpha/employee/clocking'} $sid
 Wait-PwaPage $sid '/staff/alpha/employee/clocking'
 $null=Send-Cdp 'Network.emulateNetworkConditions' @{offline=$true;latency=0;downloadThroughput=0;uploadThroughput=0} $sid
 $offlineForm=Send-Cdp 'Runtime.evaluate' @{expression='(()=>{let gps=0;navigator.geolocation.getCurrentPosition=()=>gps++;const form=document.querySelector("[data-location-form]");const allowed=form.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));return {allowed,gps,warning:!document.querySelector("[data-pwa-status]").hidden};})()';returnByValue=$true} $sid
 if($offlineForm.exceptionDetails -or $offlineForm.result.value.allowed -or $offlineForm.result.value.gps -ne 0 -or !$offlineForm.result.value.warning){throw 'Offline form was not blocked before GPS'}
 # Service worker networking has its own DevTools target; emulate offline there too.
 $targets=Send-Cdp 'Target.getTargets' @{}
 foreach($workerTarget in @($targets.targetInfos | Where-Object {$_.type -eq 'service_worker' -and $_.url -like '*55510/staff/employee-sw.js'})) {
  $workerSession=Send-Cdp 'Target.attachToTarget' @{targetId=$workerTarget.targetId;flatten=$true}
  $null=Send-Cdp 'Network.enable' @{} $workerSession.sessionId
  $null=Send-Cdp 'Network.emulateNetworkConditions' @{offline=$true;latency=0;downloadThroughput=0;uploadThroughput=0} $workerSession.sessionId
 }
 $null=Send-Cdp 'Page.navigate' @{url='http://127.0.0.1:55510/staff/alpha/employee/hours'} $sid
 Wait-PwaPage $sid '/staff/alpha/employee/hours'
 $offline=Send-Cdp 'Runtime.evaluate' @{expression='({safe:document.body.textContent.includes("Reconnect to continue")&&!document.body.textContent.includes("Test Employee"),forms:document.forms.length})';returnByValue=$true} $sid
 if(!$offline.result.value.safe -or $offline.result.value.forms){throw 'Offline document unsafe'}
 $shot=Send-Cdp 'Page.captureScreenshot' @{format='png'} $sid
 [IO.File]::WriteAllBytes((Join-Path $artifactRoot 'offline.png'),[Convert]::FromBase64String($shot.data))
 $null=Send-Cdp 'Network.emulateNetworkConditions' @{offline=$false;latency=0;downloadThroughput=-1;uploadThroughput=-1} $sid
 @{layouts=$results;layoutFailures=$layoutFailures;worker=$worker.result.value;offlineForm=$offlineForm.result.value;offline=$offline.result.value}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $artifactRoot 'results.json')
 if($layoutFailures.Count){throw "Layout/PWA failures recorded: $($layoutFailures.Count). See results.json."}
 Write-Output "PASS: $($results.Count) responsive pages; $($worker.result.value.workerCases) worker isolation cases; no cache/IDB; offline form and navigation safe."
} finally {
 try{$null=Send-Cdp 'Browser.close' @{}}catch{}
 $socket.Dispose()
}
