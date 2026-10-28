using System;
using System.Drawing;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly:System.Reflection.AssemblyTitle("NCT Studio")]
[assembly:System.Reflection.AssemblyDescription("NCT Studio desktop")]
[assembly:System.Reflection.AssemblyVersion("1.1.7.0")]
[assembly:System.Reflection.AssemblyFileVersion("1.1.7.0")]
static class Program {
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int command);
    [STAThread] static void Main(string[] args) {
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        string root=AppDomain.CurrentDomain.BaseDirectory;
        string data=File.Exists(Path.Combine(root,"portable.mode"))?Path.Combine(root,"data"):Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"NCT Studio","data");
        int smoke=0,restartParent=0;string report="";
        for(int i=0;i<args.Length;i++){
            if(args[i]=="--restart-parent" && i+1<args.Length)restartParent=int.Parse(args[++i]);
            else if(args[i]=="--data-dir" && i+1<args.Length)data=Path.GetFullPath(args[++i]);
            else if(args[i]=="--smoke-test" && i+1<args.Length)smoke=int.Parse(args[++i]);
            else if(args[i]=="--test-report" && i+1<args.Length)report=Path.GetFullPath(args[++i]);
        }
        if(restartParent>0){try{if(!Process.GetProcessById(restartParent).WaitForExit(30000))return;}catch(ArgumentException){}}
        string id;using(var sha=System.Security.Cryptography.SHA256.Create())id=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(data.ToLowerInvariant()))).Replace("-","").Substring(0,20);
        bool first;using(var mutex=new Mutex(true,"Local\\NCTStudio-"+id,out first)){
            if(!first){foreach(Process p in Process.GetProcessesByName("NCT Studio")){if(p.Id!=Process.GetCurrentProcess().Id && p.MainWindowHandle!=IntPtr.Zero){ShowWindow(p.MainWindowHandle,9);SetForegroundWindow(p.MainWindowHandle);break;}}return;}
            try{Application.Run(new Studio(root,data,smoke,report));}
            catch(Exception ex){MessageBox.Show("Không mở được NCT Studio.\n"+ex.Message,"NCT Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);}
        }
    }
}

class Studio:Form {
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h,int a,ref int v,int s);
    string root,data,url="",origin="",key="",report,installer="",importSource="";int smoke;Process backend;WebView2 web;
    Label title,status;bool ready=false,closing=false,exitAllowed=false;StreamWriter log;
    TaskCompletionSource<string> address=new TaskCompletionSource<string>();
    public Studio(string r,string d,int test,string reportPath){
        root=r;data=d;smoke=test;report=reportPath;Text="NCT Studio";
        BackColor=Color.FromArgb(8,8,10);ForeColor=Color.White;Font=new Font("Segoe UI",10);
        Size=new Size(1320,880);MinimumSize=new Size(960,680);StartPosition=FormStartPosition.CenterScreen;
        AutoScaleMode=AutoScaleMode.Dpi;
        string icon=Path.Combine(root,"studio.ico");if(File.Exists(icon))Icon=new Icon(icon);
        title=new Label{Text="NCT Studio",Font=new Font("Segoe UI",26,FontStyle.Bold),AutoSize=false,TextAlign=ContentAlignment.MiddleCenter,Dock=DockStyle.Fill};
        status=new Label{Text="Đang chuẩn bị không gian làm việc…",ForeColor=Color.FromArgb(150,150,160),Height=66,TextAlign=ContentAlignment.TopCenter,Dock=DockStyle.Bottom};
        Controls.Add(title);Controls.Add(status);Shown+=async delegate{await Start();};
        FormClosing+=async delegate(object sender,FormClosingEventArgs e){
            if(exitAllowed)return;e.Cancel=true;if(closing)return;
            if(ready && smoke==0){await web.ExecuteScriptAsync("window.nctRequestClose ? window.nctRequestClose() : window.chrome.webview.postMessage('exit-confirmed')");return;}
            await Shutdown();
        };
        HandleCreated+=delegate{int dark=1;DwmSetWindowAttribute(Handle,20,ref dark,4);};
    }
    ProcessStartInfo Python(string script,string arguments){
        var p=new ProcessStartInfo(Path.Combine(root,"runtime","python.exe"));
        p.Arguments="-X utf8 -u \""+Path.Combine(root,"app",script)+"\" "+arguments;
        p.WorkingDirectory=Path.Combine(root,"app");p.UseShellExecute=false;p.CreateNoWindow=true;
        p.RedirectStandardOutput=true;p.RedirectStandardError=true;p.StandardOutputEncoding=Encoding.UTF8;p.StandardErrorEncoding=Encoding.UTF8;
        p.EnvironmentVariables["PYTHONHOME"]=Path.Combine(root,"runtime");
        p.EnvironmentVariables["PYTHONPATH"]=Path.Combine(root,"app");p.EnvironmentVariables["PYTHONUTF8"]="1";
        p.EnvironmentVariables["NCT_DATA_DIR"]=data;p.EnvironmentVariables["NCT_NO_BROWSER"]="1";
        p.EnvironmentVariables["NCT_PORT"]="0";p.EnvironmentVariables["NCT_DESKTOP"]="1";
        p.EnvironmentVariables["NCT_DESKTOP_PID"]=Process.GetCurrentProcess().Id.ToString();
        p.EnvironmentVariables["ANONYMIZED_TELEMETRY"]="false";return p;
    }
    async Task Start(){
        try{
            if(!File.Exists(Path.Combine(root,"runtime","python.exe")))throw new Exception("Thiếu runtime. Giải nén toàn bộ bản Portable hoặc chạy lại Setup.");
            if(!File.Exists(Path.Combine(data,"manager.sqlite3")) && smoke==0){
                using(var welcome=new Welcome()){
                    welcome.ShowDialog(this);
                    if(welcome.Import){
                        using(var folder=new FolderBrowserDialog{Description="Chọn thư mục data cũ, có manager.sqlite3",ShowNewFolderButton=false}){
                            if(folder.ShowDialog(this)==DialogResult.OK){
                                string selected=folder.SelectedPath;if(!File.Exists(Path.Combine(selected,"manager.sqlite3")))selected=Path.Combine(selected,"data");
                                if(!File.Exists(Path.Combine(selected,"manager.sqlite3")))throw new Exception("Thư mục đã chọn không có manager.sqlite3. Mở lại ứng dụng và chọn thư mục data cũ.");
                                status.Text="Đang sao chép kho nội dung và chuyển đường dẫn…";
                                using(Process importer=Process.Start(Python("deployment.py","--import-data \""+selected+"\" --destination \""+data+"\""))){
                                    Task<string> err=importer.StandardError.ReadToEndAsync();Task<string> output=importer.StandardOutput.ReadToEndAsync();
                                    await Task.Run(()=>importer.WaitForExit());await output;string errors=await err;
                                    if(importer.ExitCode!=0)throw new Exception("Không nhập được dữ liệu. Dữ liệu gốc được giữ. Kiểm tra đích chưa có dữ liệu và thử lại.\n"+errors.Substring(Math.Max(0,errors.Length-600)));
                                }
                            }
                        }
                    }
                }
            }
            Directory.CreateDirectory(data);Directory.CreateDirectory(Path.Combine(data,"logs"));
            log=new StreamWriter(Path.Combine(data,"logs","desktop.log"),true,Encoding.UTF8){AutoFlush=true};
            backend=new Process{StartInfo=Python("app.py",""),EnableRaisingEvents=true};
            backend.OutputDataReceived+=delegate(object s,DataReceivedEventArgs e){
                if(e.Data==null || closing)return;
                Match m=Regex.Match(e.Data,@"http://127\.0\.0\.1:\d+/\?key=([\w-]+)");
                if(m.Success)address.TrySetResult(m.Value);
                else lock(log)log.WriteLine(e.Data);
            };
            backend.ErrorDataReceived+=delegate(object s,DataReceivedEventArgs e){if(e.Data!=null && log!=null && !closing)lock(log)log.WriteLine(e.Data);};
            backend.Exited+=delegate{if(!closing){address.TrySetException(new Exception("Dịch vụ ứng dụng đã dừng. Xem thư mục logs trong dữ liệu."));if(IsHandleCreated)BeginInvoke((Action)(()=>{if(ready){ready=false;status.Text="Dịch vụ đã dừng. Đóng rồi mở lại NCT Studio.";status.Visible=true;}}));}};
            backend.Start();backend.BeginOutputReadLine();backend.BeginErrorReadLine();
            if(await Task.WhenAny(address.Task,Task.Delay(60000))!=address.Task)throw new Exception("Khởi động quá 60 giây. Xem desktop.log trong thư mục dữ liệu.");
            url=await address.Task;Uri local=new Uri(url);origin=local.GetLeftPart(UriPartial.Authority);key=Regex.Match(url,@"key=([\w-]+)").Groups[1].Value;
            status.Text="Đang mở giao diện…";
            web=new WebView2{Dock=DockStyle.Fill,DefaultBackgroundColor=Color.FromArgb(8,8,10)};Controls.Add(web);web.BringToFront();
            var env=await CoreWebView2Environment.CreateAsync(null,Path.Combine(Directory.GetParent(data).FullName,"WebView"));
            await web.EnsureCoreWebView2Async(env);
            web.CoreWebView2.Settings.AreDevToolsEnabled=false;web.CoreWebView2.Settings.IsStatusBarEnabled=false;web.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
            web.CoreWebView2.NavigationStarting+=delegate(object s,CoreWebView2NavigationStartingEventArgs e){if(!e.Uri.StartsWith(origin+"/",StringComparison.OrdinalIgnoreCase) && e.Uri!="about:blank"){e.Cancel=true;External(e.Uri);}};
            web.CoreWebView2.NewWindowRequested+=delegate(object s,CoreWebView2NewWindowRequestedEventArgs e){e.Handled=true;External(e.Uri);};
            web.CoreWebView2.WebMessageReceived+=async delegate(object s,CoreWebView2WebMessageReceivedEventArgs e){
                if(!e.Source.StartsWith(origin+"/",StringComparison.OrdinalIgnoreCase))return;
                string message=e.TryGetWebMessageAsString();
                if(message=="exit-confirmed"){await Shutdown();return;}
                try{
                    var obj=new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string,string>>(message);
                    if(obj["action"]=="import-data"){
                        string selected=Path.GetFullPath(obj["source"]);
                        if(!File.Exists(Path.Combine(selected,"manager.sqlite3")))throw new Exception("Chọn thư mục data có manager.sqlite3.");
                        importSource=selected;await Shutdown();return;
                    }
                    if(obj["action"]!="install-update")return;
                    string path=Path.GetFullPath(obj["path"]);string folder=Path.GetFullPath(Path.Combine(data,"updates"))+Path.DirectorySeparatorChar;
                    if(!path.StartsWith(folder,StringComparison.OrdinalIgnoreCase) || !Regex.IsMatch(Path.GetFileName(path),@"^NCT-Studio-Setup-\d+\.\d+\.\d+\.exe$"))return;
                    using(var sha=System.Security.Cryptography.SHA256.Create())using(var stream=File.OpenRead(path)){
                        string hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
                        if(hash!=obj["sha256"])return;
                    }
                    installer=path;await Shutdown();
                }catch(Exception ex){status.Text="Chưa thực hiện: "+ex.Message;status.Visible=true;}
            };
            web.CoreWebView2.NavigationCompleted+=async delegate(object s,CoreWebView2NavigationCompletedEventArgs e){
                if(!e.IsSuccess){status.Text="Chưa tải được giao diện. Đóng và mở lại ứng dụng.";status.Visible=true;return;}
                ready=true;title.Visible=false;status.Visible=false;
                if(report!="")File.WriteAllText(report,"UI_READY",Encoding.UTF8);
                if(smoke>0){await Task.Delay(smoke*1000);await Shutdown();}
            };
            web.CoreWebView2.Navigate(url);
        }catch(WebView2RuntimeNotFoundException){Fail("Thiếu Microsoft Edge WebView2. Chạy NCT-Studio-Setup.exe để cài thành phần này, rồi mở lại.");}
        catch(Exception ex){Fail(ex.Message);}
    }
    void External(string value){Uri u;if(Uri.TryCreate(value,UriKind.Absolute,out u) && (u.Scheme=="https" || u.Scheme=="http") && !value.StartsWith(origin+"/",StringComparison.OrdinalIgnoreCase)){try{Process.Start(new ProcessStartInfo(value){UseShellExecute=true});}catch{}}}
    void Fail(string message){status.Text=message;status.Visible=true;title.Visible=true;if(report!="")File.WriteAllText(report,"ERROR: "+message,Encoding.UTF8);}
    async Task Shutdown(){
        if(closing)return;closing=true;ready=false;
        try{
            if(backend!=null && !backend.HasExited){
                if(origin!=""){
                    try{using(var client=new WebClient()){client.Headers["X-NCT-Key"]=key;client.Headers["Content-Type"]="application/json";await client.UploadStringTaskAsync(origin+"/api/desktop-close","POST","{}");}}catch{}
                }
                bool ended=await Task.Run(()=>backend.WaitForExit(15000));
                if(!ended)backend.Kill();
            }
        }finally{if(web!=null)web.Dispose();if(log!=null){lock(log)log.Dispose();}if(report!="")File.AppendAllText(report,"\nCLOSED");}
        if(importSource!=""){
                title.Visible=true;status.Visible=true;status.Text="Đang sao lưu và nhập dữ liệu…";
                using(Process importer=Process.Start(Python("deployment.py","--import-data \""+importSource+"\" --destination \""+data+"\" --replace-existing"))){
                    Task<string> error=importer.StandardError.ReadToEndAsync();Task<string> output=importer.StandardOutput.ReadToEndAsync();
                    await Task.Run(()=>importer.WaitForExit());await output;await error;
                    if(importer.ExitCode!=0)MessageBox.Show("Chưa nhập được dữ liệu. Dữ liệu trước đó đã được giữ/khôi phục; xem thư mục data.backup-* nếu cần. Kiểm tra nguồn rồi thử lại.","NCT Studio");
                }
                Process.Start(new ProcessStartInfo(Path.Combine(root,"NCT Studio.exe")){UseShellExecute=true,Arguments="--restart-parent "+Process.GetCurrentProcess().Id+" --data-dir \""+data+"\""});
            }
            exitAllowed=true;if(installer!="")Process.Start(new ProcessStartInfo(installer){UseShellExecute=true,Arguments="/DIR=\""+root.TrimEnd(Path.DirectorySeparatorChar)+"\""});Close();
    }
}

class Welcome:Form {
    public bool Import=false;
    public Welcome(){
        Text="Chào mừng đến NCT Studio";Size=new Size(570,330);StartPosition=FormStartPosition.CenterParent;FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;MinimizeBox=false;
        BackColor=Color.FromArgb(12,12,16);ForeColor=Color.White;Font=new Font("Segoe UI",10);
        Controls.Add(new Label{Text="Không gian làm việc của bro.",Font=new Font("Segoe UI",21,FontStyle.Bold),Location=new Point(30,32),Size=new Size(500,50)});
        Controls.Add(new Label{Text="Bắt đầu mới hoặc nhập nhóm, kho nội dung và lịch sử từ máy cũ.\nTài khoản Facebook và API key sẽ được thiết lập trên máy này.",ForeColor=Color.FromArgb(165,165,175),Location=new Point(32,100),Size=new Size(490,65)});
        var fresh=new Button{Text="Bắt đầu mới",BackColor=Color.FromArgb(235,235,240),ForeColor=Color.Black,FlatStyle=FlatStyle.Flat,Location=new Point(32,200),Size=new Size(220,45)};
        var old=new Button{Text="Nhập dữ liệu cũ",BackColor=Color.FromArgb(35,35,43),ForeColor=Color.White,FlatStyle=FlatStyle.Flat,Location=new Point(270,200),Size=new Size(220,45)};
        fresh.Click+=delegate{Close();};old.Click+=delegate{Import=true;Close();};Controls.Add(fresh);Controls.Add(old);
    }
}
