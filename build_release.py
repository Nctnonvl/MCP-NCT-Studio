"""Reproducible Windows x64 desktop bundle, without production data or keys."""
import json,os,shutil,subprocess,sys,sysconfig,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output';BUNDLE=OUT/'NCT-Studio-Portable';SOURCE=ROOT/'source'
PYTHON=Path(sys.base_prefix)
SITE=Path(os.environ.get('NCT_BUILD_SITE_PACKAGES',sysconfig.get_paths()['purelib']))

def build():
    BUNDLE.mkdir(parents=True,exist_ok=True)
    app=BUNDLE/'app';app.mkdir(exist_ok=True)
    for pattern in ('*.py','*.html','*.css','*.js'):
        for file in SOURCE.glob(pattern):shutil.copy2(file,app/file.name)
    shutil.copytree(SOURCE/'assets',app/'assets',dirs_exist_ok=True)
    runtime=BUNDLE/'runtime';runtime.mkdir(exist_ok=True)
    for file in PYTHON.iterdir():
        if file.is_file() and (file.suffix.lower() in {'.dll','.exe','.txt'} or file.name=='LICENSE'):shutil.copy2(file,runtime/file.name)
    ignored=shutil.ignore_patterns('__pycache__','test','tests','idlelib','ensurepip','site-packages')
    shutil.copytree(PYTHON/'Lib',runtime/'Lib',dirs_exist_ok=True,ignore=ignored)
    shutil.copytree(PYTHON/'DLLs',runtime/'DLLs',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(SITE,runtime/'Lib/site-packages',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    sdk=ROOT/'tools/webview2'
    notices=BUNDLE/'THIRD-PARTY';notices.mkdir(exist_ok=True)
    for name in ('LICENSE.txt','NOTICE.txt'):shutil.copy2(sdk/name,notices/('WebView2-'+name))
    for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll'):
        shutil.copy2(sdk/'lib/net462'/name,BUNDLE/name)
    shutil.copy2(sdk/'runtimes/win-x64/native/WebView2Loader.dll',BUNDLE/'WebView2Loader.dll')
    from PIL import Image,ImageOps,ImageDraw
    image=Image.open(SOURCE/'assets/brand-logo.png').convert('RGBA')
    canvas=Image.new('RGBA',(256,256),(8,8,10,255));thumb=ImageOps.contain(image,(240,240));canvas.alpha_composite(thumb,((256-thumb.width)//2,(256-thumb.height)//2))
    canvas.save(BUNDLE/'studio.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    wizard=Image.new('RGB',(164,314),(10,10,14));logo=ImageOps.contain(image.convert('RGB'),(140,140));wizard.paste(logo,((164-logo.width)//2,42));wizard.save(ROOT/'native/wizard.bmp')
    canvas.convert('RGB').resize((55,55)).save(ROOT/'native/wizard-small.bmp')
    csc=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    command=[str(csc),'/nologo','/target:winexe','/platform:x64','/optimize+','/utf8output','/out:'+str(BUNDLE/'NCT Studio.exe'),'/win32icon:'+str(BUNDLE/'studio.ico'),'/win32manifest:'+str(ROOT/'native/app.manifest'),'/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Net.Http.dll','/r:System.Web.Extensions.dll','/r:'+str(BUNDLE/'Microsoft.Web.WebView2.Core.dll'),'/r:'+str(BUNDLE/'Microsoft.Web.WebView2.WinForms.dll'),str(ROOT/'native/Studio.cs')]
    subprocess.run(command,check=True)
    (BUNDLE/'NCT Studio.exe.config').write_text('<?xml version="1.0"?><configuration><startup useLegacyV2RuntimeActivationPolicy="true"><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup><runtime><loadFromRemoteSources enabled="true"/></runtime><appSettings><add key="EnableWindowsFormsHighDpiAutoResizing" value="true"/></appSettings></configuration>',encoding='utf-8')
    shutil.copy2(ROOT/'HUONG-DAN.txt',BUNDLE/'HUONG-DAN.txt')
    (BUNDLE/'portable.mode').write_text('Store data beside this application. Remove this marker only before first launch to use LocalAppData.\n')
    # Hash shipped files before any smoke test creates data.
    import hashlib
    manifest={str(f.relative_to(BUNDLE)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in BUNDLE.rglob('*') if f.is_file() and not any(p in {'data','WebView','__pycache__'} for p in f.relative_to(BUNDLE).parts)}
    (OUT/'files.sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Built desktop bundle:',BUNDLE)

if __name__=='__main__':build()
