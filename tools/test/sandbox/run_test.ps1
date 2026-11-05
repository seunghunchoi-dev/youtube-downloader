# Windows 샌드박스 안에서 자동 실행: 설치 → 실행 → 영상 1개 다운로드 → 결과 저장
# 결과는 C:\YTBuild\sandbox\results (샌드박스 안에서는 C:\Test\results) 에 남는다
$ErrorActionPreference = "Continue"
$res = "C:\Test\results"
New-Item -ItemType Directory -Force $res | Out-Null
function Log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Out-File "$res\result.txt" -Append -Encoding utf8 }

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class U {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(int f, int x, int y, int d, int e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte v, byte s, int f, int e);
  [DllImport("user32.dll")] public static extern IntPtr GetFocus();
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, int m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
[U]::SetProcessDPIAware() | Out-Null

function Shot($name) {
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save("$res\$name", [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}
Add-Type -AssemblyName System.Windows.Forms
function Click($x, $y) {
    [U]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 200
    [U]::mouse_event(2, 0, 0, 0, 0); Start-Sleep -Milliseconds 50; [U]::mouse_event(4, 0, 0, 0, 0)
    Start-Sleep -Milliseconds 300
}

Log "설치 시작"
$setup = Get-ChildItem "C:\Setup\YouTubeDownloader_Setup_*.exe" | Select-Object -First 1
$p = Start-Process $setup.FullName -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/NORESTART", "/DIR=C:\App" -Wait -PassThru
Log "설치 종료 코드 $($p.ExitCode)"

Log "프로그램 실행"
$app = Start-Process "C:\App\YouTubeDownloader.exe" -PassThru
$h = [IntPtr]::Zero
for ($i = 0; $i -lt 60 -and $h -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 500
    $app.Refresh()
    $h = $app.MainWindowHandle
}
if ($h -eq [IntPtr]::Zero) { Log "실패: 창이 뜨지 않음 (종료 여부 $($app.HasExited))"; Shot "fail.png"; exit }
Log "창 표시됨: $($app.MainWindowTitle)"
Start-Sleep 3
[U]::SetForegroundWindow($h) | Out-Null
$pt = New-Object U+POINT; [U]::ClientToScreen($h, [ref]$pt) | Out-Null
$rc = New-Object U+RECT; [U]::GetClientRect($h, [ref]$rc) | Out-Null
Shot "1_started.png"

# 주소 입력칸 클릭 → 주소 입력 → Enter
Click ($pt.X + 300) ($pt.Y + 140)
$fg = [U]::GetForegroundWindow(); $pid2 = 0
$tid = [U]::GetWindowThreadProcessId($fg, [ref]$pid2)
[U]::AttachThreadInput([U]::GetCurrentThreadId(), $tid, $true) | Out-Null
$focus = [U]::GetFocus()
foreach ($ch in "https://www.youtube.com/watch?v=jNQXAC9IVRw".ToCharArray()) {
    [U]::SendMessage($focus, 0x0102, [IntPtr][int]$ch, [IntPtr]::Zero) | Out-Null
}
[U]::keybd_event(0x0D, 0, 0, 0); Start-Sleep -Milliseconds 50; [U]::keybd_event(0x0D, 0, 2, 0)
Log "주소 추가"
Start-Sleep 15
Shot "2_added.png"

# 목록 머리의 '전체 다운로드' 버튼
Click ($pt.X + $rc.R - 300) ($pt.Y + 305)
Log "전체 다운로드 클릭"
$dl = "$env:USERPROFILE\Downloads\YouTube Downloader"
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 2
    $mp4 = Get-ChildItem $dl -Filter *.mp4 -ErrorAction SilentlyContinue
    if ($mp4) { break }
}
Start-Sleep 3
Shot "3_done.png"
if ($mp4) {
    Log ("성공: {0} ({1:N0} 바이트)" -f $mp4[0].Name, $mp4[0].Length)
    Copy-Item $mp4[0].FullName "$res\" -Force
} else {
    Log "실패: 다운로드된 MP4 없음"
}
Log "끝"
