/* NCT Studio · interaction layer */
(function(){
 const root=document.documentElement;root.dataset.theme='dark';
 document.querySelector('.side-bottom').replaceChildren();
 const mark=document.querySelector('.brand-mark');mark.removeAttribute('role');mark.removeAttribute('aria-label');const brandLogo=document.createElement('img');brandLogo.src='/brand-logo.png?key='+encodeURIComponent(KEY);brandLogo.alt='Logo NCT';brandLogo.decoding='async';mark.replaceChildren(brandLogo);const favicon=document.createElement('link');favicon.rel='icon';favicon.type='image/png';favicon.href=brandLogo.src;document.head.append(favicon);
 document.querySelector('.brand small').textContent='AI WORKSPACE';
 const titleNames={campaign:'Chiến dịch AI',studio:'Tạo nội dung',groups:'Nhóm & phân loại',library:'Kho nội dung',schedule:'Lịch đăng bài',telegram:'Telegram',settings:'Cài đặt'};
 for(const [key,value] of Object.entries(titleNames))titles[key][1]=value;
 const selected=document.querySelector('.nav button.active');if(selected)$('page-title').textContent=titleNames[selected.dataset.page];
 document.querySelector('.crumb').firstChild.textContent='Studio / ';
 const campaignPreview=$('campaign-preview');campaignPreview.textContent='Xem dự kiến';
 const briefLabel=document.querySelector('label+textarea#group-draft-brief')?.previousElementSibling;if(briefLabel)briefLabel.textContent='Nội dung muốn AI viết';
 const activity=document.createElement('div');activity.className='activity-panel';activity.setAttribute('role','status');activity.setAttribute('aria-live','polite');activity.innerHTML='<div class="activity-icon" aria-hidden="true"><span class="activity-aura"></span><span class="activity-orbit orbit-one"></span><span class="activity-orbit orbit-two"></span><span class="activity-spark">✦</span></div><div class="activity-copy"><strong>Sẵn sàng</strong><p>Chọn một tác vụ để bắt đầu</p></div><span class="activity-tag">NCT AI</span><div class="activity-equalizer" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>';
 document.querySelector('.topbar').after(activity);let activitySignature='';
 function renderActivity(){
  if(!state)return;const task=state.studio||{},scan=state.group_scan||{},working=(state.jobs||[]).find(j=>j.state==='working'),update=(state.link_refresh||[]).find(j=>j.state==='working');
  const generating=task.status==='running',scanning=scan.status==='running',busy=generating||scanning||!!working||!!update;
  let title='Sẵn sàng',detail='Chọn một tác vụ để bắt đầu';
  if(generating){title=task.stop_requested?'AI đang dừng…':'AI đang xử lý';detail=task.message||'Đang tạo nội dung theo yêu cầu'}
  else if(update){title='Đang cập nhật link';detail=update.group_name||'Đang kiểm tra đúng bài đăng'}
  else if(working){title='Đang thao tác Facebook';detail=working.group_name||'Đang xử lý lượt đã lên lịch'}
  else if(scanning){title='Đang quét nhóm';detail=scan.message||'Đọc danh sách nhóm đã tham gia'}
  else if(task.status==='error'){title='Tác vụ AI cần kiểm tra';detail=task.message||'Mở tiến trình để xem chi tiết'}
  else if(task.status==='done'){title='AI đã hoàn tất';detail=task.message||'Nội dung đã sẵn sàng trong kho'}
  else if(task.status==='stopped'){title='AI đã dừng';detail='Các nội dung đã tạo được giữ trong kho'}
  for(const source of state.ai_sources||[])detail=detail.split(source.id).join(source.name);
  if(!busy&&task.status==='error'&&/HTTP 503/.test(detail)){title='Nguồn AI tạm gián đoạn';detail='Dịch vụ đang bảo trì. Có thể thử lại sau vài phút.'}
  for(const id of ['library-task','group-draft-task']){const node=$(id);if(node){let value=node.textContent;for(const source of state.ai_sources||[])value=value.split(source.id).join(source.name);if(node.textContent!==value)node.textContent=value}}
  const signature=JSON.stringify([title,detail,busy]);if(signature===activitySignature)return;activitySignature=signature;
  activity.setAttribute('aria-busy',String(busy));activity.classList.toggle('is-generating',generating);activity.classList.toggle('is-running',busy);activity.classList.toggle('needs-review',!busy&&task.status==='error');activity.querySelector('strong').textContent=title;activity.querySelector('p').textContent=detail;
  activity.querySelector('.activity-tag').textContent=busy?'Đang chạy':'NCT AI';
 }
 const activityDetails=document.createElement('button');activityDetails.type='button';activityDetails.className='help-dot';activityDetails.textContent='!';activityDetails.setAttribute('aria-label','Xem chi tiết hoạt động');activityDetails.onclick=()=>{const task=state?.studio||{};nctDialog(task.message||activity.querySelector('p').textContent,{title:'Hoạt động hiện tại'})};activity.append(activityDetails);
 document.addEventListener('nct:state',renderActivity);renderActivity();setInterval(renderActivity,1200);
 const tooltip=document.createElement('div');tooltip.id='nct-help-tooltip';tooltip.className='help-tooltip hidden';tooltip.setAttribute('role','tooltip');document.body.append(tooltip);let helpButton=null,pinned=false;
 function hideHelp(){tooltip.classList.add('hidden');if(helpButton)helpButton.setAttribute('aria-expanded','false');helpButton=null;pinned=false}
 function showHelp(button){if(helpButton&&helpButton!==button)helpButton.setAttribute('aria-expanded','false');helpButton=button;tooltip.textContent=button.dataset.help;tooltip.classList.remove('hidden');button.setAttribute('aria-expanded','true');const r=button.getBoundingClientRect(),w=tooltip.offsetWidth,h=tooltip.offsetHeight;tooltip.style.left=Math.max(12,Math.min(innerWidth-w-12,r.left))+'px';tooltip.style.top=(r.bottom+h+18<innerHeight?r.bottom+9:Math.max(12,r.top-h-9))+'px'}
 document.querySelectorAll('p.hint,.intro p,p.muted').forEach(node=>{
  if(node.id||node.closest('#backend-banner')||node.querySelector('a,input,button,select')||node.textContent.trim().length<65)return;
  const text=node.textContent.trim();node.classList.add('hint-compact');node.replaceChildren();const button=document.createElement('button');button.type='button';button.className='help-dot';button.textContent='!';button.dataset.help=text;button.setAttribute('aria-label','Thông tin: '+text);button.setAttribute('aria-describedby',tooltip.id);button.setAttribute('aria-expanded','false');
  button.addEventListener('pointerenter',()=>{if(!pinned)showHelp(button)});button.addEventListener('pointerleave',()=>{if(!pinned)hideHelp()});button.addEventListener('focus',()=>showHelp(button));button.addEventListener('blur',()=>{if(!pinned)hideHelp()});button.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();if(helpButton===button&&pinned)hideHelp();else{showHelp(button);pinned=true}});let before=node.previousElementSibling,target=null;
  if(before?.matches('input,textarea,select'))target=before.labels?.[0]||(before.previousElementSibling?.tagName==='LABEL'?before.previousElementSibling:null);
  if(!target)target=node.closest('details,dialog')?.querySelector('summary strong,h2,h3,label');
  if(!target&&before?.tagName==='DIV')target=before.querySelector('label,h2,h3,strong');
  if(!target){let scope=node.parentElement;while(scope&&scope!==document.body&&!target){target=scope.querySelector('h2,h3,label,summary strong');scope=scope.parentElement}}
  if(target){const existing=target.querySelector(':scope>.help-dot');if(existing){existing.dataset.help+='\n\n'+text;existing.setAttribute('aria-label','Thông tin: '+existing.dataset.help)}else{target.classList.add('has-inline-help');target.append(button)}node.remove()}else node.append(button);
 });
 document.addEventListener('click',e=>{if(!e.target.closest('.help-dot'))hideHelp()});document.addEventListener('keydown',e=>{if(e.key==='Escape')hideHelp()});window.addEventListener('scroll',hideHelp,{passive:true});window.addEventListener('resize',hideHelp);
})();
const nctDialogQueue=[];let nctDialogCurrent=null;
function nctDialog(message,{confirm=false,title='Thông tin',accept='Đã hiểu'}={}){
 return new Promise(resolve=>{nctDialogQueue.push({message,confirm,title,accept,resolve});nctShowNextDialog()});
}
function nctShowNextDialog(){
 if(nctDialogCurrent||!nctDialogQueue.length)return;
 nctDialogCurrent=nctDialogQueue.shift();const request=nctDialogCurrent,previous=document.activeElement;const dialog=document.createElement('dialog');dialog.className='nct-dialog';dialog.setAttribute('aria-labelledby','nct-dialog-title');dialog.setAttribute('aria-describedby','nct-dialog-description');dialog.innerHTML='<div class="nct-dialog-head"><h2 id="nct-dialog-title"></h2><button type="button" class="nct-dialog-close" aria-label="Đóng cửa sổ">×</button></div><div id="nct-dialog-description" class="nct-dialog-content"></div><div class="nct-dialog-actions"><button type="button" data-dialog-cancel>Hủy</button><button type="button" class="primary" data-dialog-accept></button></div>';
 dialog.querySelector('h2').textContent=request.title;dialog.querySelector('.nct-dialog-content').textContent=request.message;const cancel=dialog.querySelector('[data-dialog-cancel]'),accept=dialog.querySelector('[data-dialog-accept]');cancel.hidden=!request.confirm;accept.textContent=request.accept;
 let closing=false;const close=result=>{if(closing)return;closing=true;dialog.classList.add('is-closing');setTimeout(()=>{dialog.close();dialog.remove();nctDialogCurrent=null;if(previous?.isConnected)previous.focus();request.resolve(result);nctShowNextDialog()},matchMedia('(prefers-reduced-motion:reduce)').matches?0:150)};
 accept.onclick=()=>close(true);cancel.onclick=()=>close(false);dialog.querySelector('.nct-dialog-close').onclick=()=>close(false);dialog.addEventListener('cancel',e=>{e.preventDefault();close(false)});dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close(false)}});document.body.append(dialog);dialog.showModal();(request.confirm?cancel:accept).focus();
}
function askConfirm(message){return nctDialog(message,{confirm:true,title:'Xác nhận thao tác',accept:'Xác nhận'})}
function showInfo(message){return nctDialog(message,{title:'Chi tiết lượt đăng'})}

function jobStateLabel(value){return ({draft:'Nháp',queued:'Đã lên lịch',working:'Đang xử lý',submitted:'Đã đăng',pending:'Chờ duyệt',uncertain:'Cần kiểm tra',error:'Không thành công',prepared:'Đã soạn thử',cancelled:'Đã hủy'})[value]||value}
function formatQueueStatus(value){
 const jobs=value.jobs||[],count=key=>jobs.filter(j=>j.state===key).length;
 const sourceName=(id,fallback)=>(value.ai_sources||[]).find(s=>s.id===id)?.name||fallback;
 return (value.status.includes('▶ Đang chạy')?'Đang chạy lịch đăng':'Hàng đợi đang tạm dừng')+'\n'+count('queued')+' lượt đã lên lịch · '+count('working')+' lượt đang xử lý\n'+count('submitted')+' bài đã đăng · '+count('pending')+' bài chờ duyệt · '+(count('uncertain')+count('error'))+' lượt cần kiểm tra\n\nAI viết bài: '+sourceName(value.content_ai?.writer_provider,value.content_ai?.writer_provider==='ollama'?'AI trên máy':'xKiro')+'\nAI điều khiển: '+sourceName(value.control_ai?.provider,value.control_ai?.provider==='ollama'?'AI trên máy':'xKiro');
}

/* The native select remains the form value; this layer only presents the menu. */
(function(){
 const entries=new Map();let opened=null,menu=null,active=-1,search='',searchTimer,serial=0;
 const labelFor=select=>select.labels?.[0]||(select.previousElementSibling?.tagName==='LABEL'?select.previousElementSibling:null);
 function closeMenu(commit=false){const entry=opened;let changed=false;if(entry?.select.multiple){if(commit!==true){const initial=new Set(entry.initialSelected||[]);for(const option of entry.select.options)option.selected=initial.has(option.value)}changed=JSON.stringify([...entry.select.selectedOptions].map(o=>o.value))!==JSON.stringify(entry.initialSelected||[])}if(entry){entry.button.setAttribute('aria-expanded','false');entry.button.removeAttribute('aria-activedescendant')}menu?.remove();menu=null;opened=null;active=-1;search='';if(entry)sync(entry);if(entry&&commit===true&&changed){entry.select.dispatchEvent(new Event('input',{bubbles:true}));entry.select.dispatchEvent(new Event('change',{bubbles:true}))}}
 function options(entry){return [...entry.select.options].filter(o=>!o.hidden)}
 function move(index){if(!opened)return;const opts=options(opened),enabled=opts.map((o,i)=>!o.disabled&&!o.parentElement.disabled?i:-1).filter(i=>i>=0);if(!enabled.length)return;active=enabled.includes(index)?index:enabled.find(i=>i>=index)??enabled[0];const items=[...menu.querySelectorAll('[role=option]')];items.forEach((node,i)=>node.classList.toggle('is-highlighted',i===active));const target=items[active];if(target){opened.button.setAttribute('aria-activedescendant',target.id);target.scrollIntoView({block:'nearest'})}}
 const checkSvg='<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8 3 3 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
 function choose(index){if(!opened)return;const entry=opened,option=options(entry)[index];if(!option||option.disabled||option.parentElement.disabled)return;if(entry.select.multiple){option.selected=!option.selected;menu.querySelectorAll('[role=option]').forEach((row,i)=>row.setAttribute('aria-selected',String(options(entry)[i].selected)));sync(entry);return}const changed=entry.select.value!==option.value;entry.select.value=option.value;closeMenu();sync(entry);entry.button.focus();if(changed){entry.select.dispatchEvent(new Event('input',{bubbles:true}));entry.select.dispatchEvent(new Event('change',{bubbles:true}))}}
 function openMenu(entry){
  if(entry.select.disabled)return;if(opened===entry){closeMenu();return}closeMenu();sync(entry);opened=entry;entry.initialSelected=[...entry.select.selectedOptions].map(o=>o.value);entry.button.setAttribute('aria-expanded','true');
  menu=document.createElement('div');menu.className='nct-select-menu';menu.id=entry.menuId;menu.setAttribute('role','listbox');menu.setAttribute('aria-label',entry.button.getAttribute('aria-label'));
  const opts=options(entry);let list=menu;if(entry.select.multiple){menu.classList.add('is-multi');menu.setAttribute('role','dialog');list=document.createElement('div');list.className='nct-select-list';list.setAttribute('role','listbox');list.setAttribute('aria-multiselectable','true');list.setAttribute('aria-label',entry.button.getAttribute('aria-label'));menu.append(list)}
  opts.forEach((option,i)=>{const row=document.createElement('div');row.id=entry.menuId+'-'+i;row.className='nct-select-option';row.setAttribute('role','option');row.setAttribute('aria-selected',String(option.selected));row.setAttribute('aria-disabled',String(!!(option.disabled||option.parentElement.disabled)));const caption=document.createElement('span');caption.textContent=option.textContent;const check=document.createElement('span');check.className='nct-option-check';check.innerHTML=checkSvg;if(entry.select.multiple)check.classList.add('multi-check');check.setAttribute('aria-hidden','true');row.append(caption,check);row.addEventListener('pointerdown',e=>e.preventDefault());row.addEventListener('pointermove',()=>{if(!option.disabled)move(i)});row.addEventListener('click',()=>choose(i));list.append(row)});
  if(!opts.length){const empty=document.createElement('div');empty.className='nct-select-empty';empty.textContent='Chưa có lựa chọn';menu.append(empty)}
  if(entry.select.multiple){const footer=document.createElement('div');footer.className='nct-multi-footer';const cancel=document.createElement('button'),apply=document.createElement('button');cancel.type=apply.type='button';cancel.textContent='Hủy';apply.textContent='Áp dụng';apply.className='primary';for(const button of [cancel,apply])button.addEventListener('pointerdown',e=>e.preventDefault());cancel.addEventListener('click',()=>{closeMenu();entry.button.focus()});apply.addEventListener('click',()=>{closeMenu(true);entry.button.focus()});footer.append(cancel,apply);menu.append(footer)}
  (entry.select.closest('dialog[open]')||document.body).append(menu);
  const rect=entry.button.getBoundingClientRect(),width=Math.min(Math.max(rect.width,210),innerWidth-24);menu.style.width=width+'px';menu.style.left=Math.max(12,Math.min(rect.left,innerWidth-width-12))+'px';menu.style.maxHeight=Math.min(300,Math.max(120,innerHeight-36))+'px';
  const height=menu.offsetHeight,below=innerHeight-rect.bottom-12,above=rect.top-12;
  if(below>=Math.min(height,180)||below>=above){menu.style.top=rect.bottom+7+'px';menu.style.maxHeight=Math.max(80,Math.min(300,below-7))+'px'}else{menu.style.maxHeight=Math.max(80,Math.min(300,above-7))+'px';menu.style.top=Math.max(12,rect.top-Math.min(height,above-7)-7)+'px'}
  move(Math.max(0,opts.findIndex(o=>o.selected)));
 }
 function sync(entry){
  const select=entry.select,option=select.options[select.selectedIndex];const caption=entry.button.querySelector('.nct-select-caption'),selected=[...select.selectedOptions].map(o=>o.textContent),value=select.multiple?(selected.length===0?'Chọn kho':selected.length<=2?selected.join(', '):selected.length+' kho đã chọn'):(option?.textContent||'Chọn…');if(caption.textContent!==value)caption.textContent=value;if(entry.button.disabled!==select.disabled)entry.button.disabled=select.disabled;
  const label=entry.label||labelFor(select);let labelText=select.getAttribute('aria-label');if(!labelText&&label){const clone=label.cloneNode(true);clone.querySelectorAll('button').forEach(b=>b.remove());labelText=clone.textContent.trim()}if(entry.button.getAttribute('aria-label')!==(labelText||'Lựa chọn'))entry.button.setAttribute('aria-label',labelText||'Lựa chọn');
  if(opened===entry&&!select.multiple&&entry.lastValue!==select.value)closeMenu();entry.lastValue=select.value;
 }
 function install(){
  for(const select of document.querySelectorAll('select')){
   if((select.size>1&&!select.multiple)||entries.has(select))continue;
   const fieldLabel=labelFor(select);const wrapper=document.createElement('div');wrapper.className='nct-select';select.before(wrapper);wrapper.append(select);select.classList.add('nct-native-select');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
   const button=document.createElement('button');button.type='button';button.className='nct-select-trigger';button.setAttribute('role','combobox');button.setAttribute('aria-haspopup',select.multiple?'dialog':'listbox');button.setAttribute('aria-expanded','false');const menuId='nct-select-'+(++serial);button.setAttribute('aria-controls',menuId);button.innerHTML='<span class="nct-select-caption"></span><svg class="nct-select-chevron" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';wrapper.append(button);
   button.querySelector('.nct-select-caption').id=menuId+'-value';button.setAttribute('aria-describedby',menuId+'-value');const entry={select,button,menuId,label:fieldLabel,lastValue:select.value};entries.set(select,entry);sync(entry);
   button.addEventListener('click',()=>openMenu(entry));select.addEventListener('focus',()=>button.focus());select.addEventListener('change',()=>sync(entry));
   button.addEventListener('keydown',e=>{
    if(e.key==='Escape'){if(opened===entry){e.preventDefault();e.stopPropagation();closeMenu()}return}
    if(e.key==='Tab'){if(opened===entry&&entry.select.multiple&&!e.shiftKey){e.preventDefault();menu.querySelector('button')?.focus();return}closeMenu();return}
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(opened!==entry)openMenu(entry);else{const opts=options(entry),step=e.key==='ArrowDown'?1:-1;let next=active+step;while(next>=0&&next<opts.length&&(opts[next].disabled||opts[next].parentElement.disabled))next+=step;if(next>=0&&next<opts.length)move(next)}return}
    if(e.key==='Home'||e.key==='End'){e.preventDefault();if(opened!==entry)openMenu(entry);const opts=options(entry);const enabled=opts.map((o,i)=>!o.disabled&&!o.parentElement.disabled?i:-1).filter(i=>i>=0);move(e.key==='Home'?enabled[0]:enabled.at(-1));return}
    if(e.key==='Enter'||e.key===' '){e.preventDefault();if(opened===entry)choose(active);else openMenu(entry);return}
    if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();if(opened!==entry)openMenu(entry);search+=e.key.toLocaleLowerCase('vi');clearTimeout(searchTimer);searchTimer=setTimeout(()=>{search=''},650);const index=options(entry).findIndex(o=>!o.disabled&&o.textContent.trim().toLocaleLowerCase('vi').startsWith(search));if(index>=0)move(index)}
   });
  }
  for(const [select,entry] of entries){if(!select.isConnected){if(opened===entry)closeMenu();entries.delete(select)}else sync(entry)}
 }
 document.addEventListener('pointerdown',e=>{if(opened&&!opened.button.contains(e.target)&&!menu?.contains(e.target))closeMenu()});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenu()});document.addEventListener('focusin',e=>{if(opened&&e.target!==opened.button&&!menu?.contains(e.target))closeMenu()});window.addEventListener('resize',closeMenu);window.addEventListener('scroll',e=>{if(menu&&!menu.contains(e.target))closeMenu()},{capture:true,passive:true});
 document.addEventListener('nct:groups-render',install);install();setInterval(install,350);
})();

/* Accessible number controls; native min/max/step and keyboard editing stay active. */
(function(){
 const entries=new Map();
 function sync(entry){const input=entry.input,value=Number(input.value),locked=input.disabled||input.readOnly;entry.down.disabled=locked||(input.value!==''&&input.min!==''&&value<=Number(input.min));entry.up.disabled=locked||(input.value!==''&&input.max!==''&&value>=Number(input.max));entry.wrapper.classList.toggle('is-disabled',input.disabled)}
 function install(){
  for(const input of document.querySelectorAll('input[type=number]')){
   if(entries.has(input))continue;
   const label=input.labels?.[0]||(input.previousElementSibling?.tagName==='LABEL'?input.previousElementSibling:null),clone=label?.cloneNode(true);clone?.querySelectorAll('button').forEach(b=>b.remove());const name=input.getAttribute('aria-label')||clone?.textContent.trim()||'giá trị';if(!input.labels?.length&&!input.getAttribute('aria-label'))input.setAttribute('aria-label',name);
   const wrapper=document.createElement('div');wrapper.className='number-field';input.before(wrapper);wrapper.append(input);const controls=document.createElement('div');controls.className='number-controls';
   const up=document.createElement('button'),down=document.createElement('button');for(const [button,increase] of [[up,true],[down,false]]){button.type='button';button.className='number-step';button.setAttribute('aria-label',(increase?'Tăng ':'Giảm ')+name);button.innerHTML=increase?'<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4.5 10 3.5-4 3.5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>':'<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4.5 6 3.5 4 3.5-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';button.addEventListener('click',()=>{if(input.disabled||input.readOnly)return;const before=input.value;try{if(increase)input.stepUp();else input.stepDown()}catch{return}if(input.value!==before){input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))}sync(entry)})}
   controls.append(up,down);wrapper.append(controls);const entry={input,wrapper,up,down};entries.set(input,entry);input.addEventListener('input',()=>sync(entry));input.addEventListener('change',()=>sync(entry));sync(entry);
  }
  for(const [input,entry] of entries){if(!input.isConnected)entries.delete(input);else sync(entry)}
 }
 install();setInterval(install,500);
})();

/* Header navigation and real workspace stats, styled from the supplied reference. */
(function(){
 const sidebar=document.querySelector('.sidebar'),nav=document.querySelector('.nav');nav.id='nct-workspace-nav';nav.setAttribute('aria-label','Danh mục quản lý');
 const burger=document.createElement('button');burger.type='button';burger.className='workspace-burger';burger.setAttribute('aria-controls',nav.id);burger.setAttribute('aria-expanded','false');burger.setAttribute('aria-label','Mở danh mục');burger.innerHTML='<span class="workspace-burger-lines" aria-hidden="true"><i></i><i></i><i></i></span>';sidebar.append(burger);
 const backdrop=document.createElement('div');backdrop.className='workspace-menu-backdrop';backdrop.setAttribute('aria-hidden','true');document.body.prepend(backdrop);
 function setMenu(open){document.body.classList.toggle('workspace-menu-open',open);burger.setAttribute('aria-expanded',String(open));burger.setAttribute('aria-label',open?'Đóng danh mục':'Mở danh mục');document.querySelector('.main').inert=open;if(!open&&innerWidth<=1100&&nav.contains(document.activeElement))burger.focus();}
 burger.addEventListener('click',()=>setMenu(!document.body.classList.contains('workspace-menu-open')));backdrop.addEventListener('click',()=>setMenu(false));
 nav.addEventListener('click',e=>{if(e.target.closest('button[data-page]')){setMenu(false);requestAnimationFrame(styleHeadline)}});
 document.addEventListener('keydown',e=>{if(e.key==='Tab'&&document.body.classList.contains('workspace-menu-open')){const controls=[burger,...nav.querySelectorAll('button:not(:disabled)')],index=controls.indexOf(document.activeElement),next=e.shiftKey?(index<=0?controls.length-1:index-1):(index+1)%controls.length;e.preventDefault();controls[next].focus()}if(e.key==='Escape'&&document.body.classList.contains('workspace-menu-open')){setMenu(false);burger.focus()}});window.addEventListener('resize',()=>{if(innerWidth>1100)setMenu(false)});
 function styleHeadline(){const node=$('page-title');if(node.querySelector('em'))return;const text=node.textContent,match=/\bAI\b/.exec(text);if(match){const em=document.createElement('em');em.textContent='AI';node.replaceChildren(document.createTextNode(text.slice(0,match.index)),em,document.createTextNode(text.slice(match.index+2)))}}
 styleHeadline();
 const stats=document.createElement('div');stats.className='workspace-stats';stats.setAttribute('aria-label','Tổng quan không gian làm việc');
 const icons=['<path d="M8.5 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7 0a3 3 0 1 0 0-6M2.5 20v-2a4.5 4.5 0 0 1 4.5-4.5h3a4.5 4.5 0 0 1 4.5 4.5v2m2-6a4 4 0 0 1 5 4v2"/>','<path d="M6 3h8l4 4v14H6V3Zm8 0v5h4M9 12h6m-6 4h6"/>','<path d="M7 3v4m10-4v4M4 10h16M4 5h16v16H4V5Zm4 9h3m2 0h3m-8 3h3"/>'];
 for(let i=0;i<3;i++){const item=document.createElement('div');item.className='workspace-stat';item.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+icons[i]+'</svg><span><b>—</b><span></span></span>';stats.append(item)}
 document.querySelector('.activity-panel').after(stats);let signature='';
 function renderStats(){if(!state)return;const values=[(state.groups||[]).filter(g=>g.enabled).length,(state.contents||[]).length,(state.jobs||[]).filter(j=>j.state==='queued').length],labels=['nhóm đang bật','bài trong kho','lượt chờ'];const next=JSON.stringify(values);if(next===signature)return;signature=next;[...stats.children].forEach((node,i)=>{node.querySelector('b').textContent=Number(values[i]).toLocaleString('vi-VN');node.querySelector('span>span').textContent=labels[i]})}
 document.addEventListener('nct:state',renderStats);renderStats();setInterval(renderStats,1500);
 for(const element of [document.querySelector('.brand'),...nav.children,document.querySelector('.main')]){if(!element)continue;element.classList.add('workspace-entrance');element.addEventListener('animationend',event=>{if(event.target===element)element.classList.add('is-in')},{once:true})}
 requestAnimationFrame(()=>requestAnimationFrame(()=>{for(const element of document.querySelectorAll('.workspace-entrance')){if(!element.getAnimations().some(a=>a.playState==='running'||a.playState==='finished'))element.classList.add('is-in')}}));
})();

/* One naming system, compact media vault and neutral operational UI. */
(function(){
 document.title='NCT Studio';
 const names={campaign:'Tự động',studio:'Soạn bài',groups:'Nhóm',library:'Bài viết',schedule:'Lịch đăng',settings:'Cài đặt'};
 for(const [key,name] of Object.entries(names))titles[key]=[name,name];
 document.querySelector('.nav [data-page="telegram"]')?.remove();
 const telegram=$('page-telegram');if(telegram){telegram.classList.add('hidden');telegram.setAttribute('aria-hidden','true')}
 for(const button of document.querySelectorAll('.nav [data-page]'))button.textContent=names[button.dataset.page]||button.textContent;
 const current=document.querySelector('.section.active')?.id.replace('page-','');if(names[current]){$('page-title').textContent=names[current];$('crumb').textContent=names[current]}
 const mediaCard=$('library-grid')?.closest('.card');
 if(mediaCard){const vault=document.createElement('details');vault.id='media-vault';vault.className='vault';const summary=document.createElement('summary');summary.className='vault-summary';summary.innerHTML='<span>Kho ảnh và video</span><span class="vault-toggle">Mở kho</span>';const content=document.createElement('div');content.className='vault-content';mediaCard.before(vault);content.append(mediaCard);vault.append(summary,content);vault.addEventListener('toggle',()=>{summary.querySelector('.vault-toggle').textContent=vault.open?'Đóng kho':'Mở kho';if(vault.open)renderLibrary();else for(const video of vault.querySelectorAll('video'))video.pause()});$('library-grid').replaceChildren();}
 const byId={
 'stop-ai-global':'Dừng AI','quick-pause':'Tạm dừng','retry-media':'Tải lại','campaign-preview':'Xem dự kiến','group-drafts':'Tạo nháp','group-autopost':'Tạo và đăng','stop-ai-batch':'Dừng AI',
 'reload-library':'Tải lại','library-upload':'Thêm tệp','library-assign':'Gán game','library-delete':'Xóa đã chọn','library-restore':'Khôi phục','load-example':'Bài mẫu','generate':'Viết bài','save-post-footer':'Lưu cuối bài',
 'save-post':'Lưu bài','save-plan':'Lưu và lên lịch','auto-gen-post':'Tạo và đăng','open-batch-ai':'Tạo hàng loạt','stop-ai':'Dừng AI','scan-joined-groups':'Quét nhóm','stop-group-scan':'Dừng quét','classify':'Phân loại','save-group':'Thêm nhóm',
 'preview-links':'Xem trước','apply-links':'Thay link','stop-link-refresh':'Dừng cập nhật','content-clear-selection':'Bỏ chọn','schedule-selected':'Lên lịch','content-delete-selected':'Xóa đã chọn','save-recovery':'Lưu thiết lập',
 'pool-select-all':'Chọn tất cả','pool-clear':'Bỏ chọn','campaign-select-all':'Chọn tất cả','campaign-clear':'Bỏ chọn','test-one':'Thử một bài','create-plan':'Tạo lịch nháp','start-campaign':'Đăng theo lịch','approve-all':'Duyệt lịch','clear-jobs':'Xóa lịch',
 'save-daily-limit':'Lưu','save-settings':'Lưu cài đặt','browser':'Mở Facebook','source-oxion':'Thêm OxionAI','source-save':'Lưu nguồn','source-new':'Thêm nguồn','save-content-ai':'Lưu AI viết bài','check-kira':'Kiểm tra','refresh-kira-models':'Xem model',
 'save-control-ai':'Lưu AI thao tác','check-xkiro':'Kiểm tra API','check':'Kiểm tra','copy-pair':'Sao chép','target-close':'Đóng','target-all':'Chọn tất cả','target-none':'Bỏ chọn','target-save':'Lưu nhóm'
 };
 const exact={'Chọn nhóm':'Chọn nhóm','Mở trong Studio':'Sửa bài','Lên lịch riêng':'Lên lịch','Sửa / đổi tên':'Chỉnh sửa','Kiểm tra model':'Xem model','Xóa nguồn':'Xóa nguồn','Lưu danh tính':'Lưu','Bản thường / có link':'Có link','Bản không link':'Không link','Quản lý / tick nhóm →':'Chọn nhóm','Tạo bài mới':'Tạo bài','AI Content Studio':'Viết với AI'};
 function plain(value){return value.replace(/^[\s\p{S}\uFE0F\u200D]+/u,'').replace(/[\s→↗]+$/u,'').trim()}
 function polishButtons(){
  for(const b of document.querySelectorAll('button')){
   if(b.matches('.help-dot,.number-step,.nct-select-trigger,.workspace-burger'))continue;
   let label=byId[b.id];
   if(b.closest('.nav'))label=names[b.dataset.page];
   else if(b.dataset.openPost)label='Sửa bài';else if(b.dataset.planPost)label='Lên lịch';else if(b.dataset.targetPost)label='Chọn nhóm';else if(b.dataset.newPost)label='Tạo bài';else if(b.dataset.removeMedia!==undefined)label='Xóa';
   else if(b.dataset.control)label={run:'Chạy lịch',pause:'Tạm dừng',stop:'Dừng và hủy lịch'}[b.dataset.control];
   else if(b.classList.contains('nct-dialog-close'))label='Đóng';
   if(!label){const original=b.textContent.trim();label=exact[original]||exact[plain(original)]||plain(original);if(!label&&original==='×')label='Đóng';}
   if(label&&b.textContent!==label)b.textContent=label;
  }
  for(const node of document.querySelectorAll('h2,h3')){
   const first=[...node.childNodes].find(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim());if(!first)continue;
   const original=first.textContent.trim(),cleaned=plain(original);const replacement=({'AI Content Studio':'Viết với AI','Nội dung cố định cuối bài':'Cuối bài','Kho ảnh & video theo game':'Ảnh và video','Chiến dịch AI: chọn số bài, tool chọn nhóm':'Tạo bài tự động','Soạn bài cho đúng nhóm':'Soạn bài','Nội dung & tệp':'Nội dung bài','Thiết lập chiến dịch':'Thiết lập lịch'})[cleaned]||cleaned;
   if(original!==replacement)first.textContent=replacement;
  }
 }
 const token=$('token');if(token){token.classList.add('hidden');const label=token.previousElementSibling;if(label?.tagName==='LABEL')label.classList.add('hidden');const fold=token.closest('details');const title=fold?.querySelector('summary strong'),subtitle=fold?.querySelector('summary small');if(title)title.textContent='Thiết lập nâng cao';if(subtitle)subtitle.textContent='Mô hình chạy trên máy';}
 let pending=false;const observer=new MutationObserver(records=>{if(pending||!records.some(r=>r.target.nodeType===1&&!r.target.closest('.nct-select-menu,.workspace-stats,.activity-panel')&&r.target.tagName!=='CANVAS'))return;pending=true;requestAnimationFrame(()=>{pending=false;polishButtons()})});
 polishButtons();observer.observe(document.body,{childList:true,subtree:true,characterData:true});
})();
/* Original-style silver particle ribbons: quiet, sparse and without a glowing core. */
(function(){
 const canvas=document.createElement('canvas');canvas.className='nct-particles nct-ribbons';canvas.setAttribute('aria-hidden','true');document.body.prepend(canvas);
 const ctx=canvas.getContext('2d');if(!ctx)return;
 const texture=document.createElement('canvas'),reduced=matchMedia('(prefers-reduced-motion:reduce)');
 let width=0,height=0,ratio=1,frame=0,last=0;
 function size(){
  width=innerWidth;height=Math.min(innerHeight,420);ratio=Math.min(devicePixelRatio||1,1.5);
  canvas.width=texture.width=Math.ceil(width*ratio);canvas.height=texture.height=Math.ceil(height*ratio);canvas.style.height=height+'px';
  const c=texture.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,width,height);
  c.save();c.translate(width*.57,185);c.rotate(-.28);
  for(let i=0;i<2700;i++){
   const angle=Math.random()*Math.PI*2,lane=i%3,spread=(Math.random()+Math.random()-1)*13;
   const rx=width*(.4+lane*.07)+spread,ry=51+lane*26+spread*.6;
   const x=Math.cos(angle)*rx,y=Math.sin(angle)*ry,v=.6+Math.random()*.9;
   c.fillStyle='rgba(230,230,230,'+(.14+Math.random()*.46).toFixed(3)+')';c.fillRect(x,y,v,v);
  }
  c.restore();ctx.setTransform(ratio,0,0,ratio,0,0);draw(0);
 }
 function draw(time){ctx.clearRect(0,0,width,height);ctx.drawImage(texture,Math.sin(time*.12)*3,Math.cos(time*.1)*2,width,height)}
 function tick(now){if(document.hidden||reduced.matches)return;if(now-last>=1000/30){draw(now/1000);last=now}frame=requestAnimationFrame(tick)}
 function run(){cancelAnimationFrame(frame);if(document.hidden)return;if(reduced.matches){draw(0);return}last=0;frame=requestAnimationFrame(tick)}
 window.addEventListener('resize',size,{passive:true});document.addEventListener('visibilitychange',run);reduced.addEventListener('change',run);size();run();
})();

/* Show nickname only when that identity is selected. */
document.addEventListener('change',event=>{const id=event.target.dataset.identityMode;if(!id)return;const field=document.querySelector('[data-identity-nickname="'+id+'"]');if(field)field.classList.toggle('hidden',event.target.value!=='nickname')});

/* Keep selection stable and toggle group status without replacing the table. */
function applyGroupEnabled(ids,enabled){if(!state)return;const selected=new Set(ids);for(const group of state.groups){if(!selected.has(group.id))continue;group.enabled=enabled?1:0;const button=document.querySelector('[data-toggle-group="'+group.id+'"]');if(button){button.dataset.enabled=enabled?'0':'1';button.textContent=enabled?'Đang bật':'Đang tắt';button.classList.toggle('secondary',enabled);button.setAttribute('aria-pressed',String(enabled))}}groupFingerprint=JSON.stringify(state.groups);renderPool()}
async function toggleGroupButton(button){
 if(button.disabled)return;const id=Number(button.dataset.toggleGroup),enabled=button.dataset.enabled==='1';button.disabled=true;button.setAttribute('aria-busy','true');
 try{await api('/api/group-toggle',{id,enabled});applyGroupEnabled([id],enabled);toast(enabled?'Đã bật nhóm.':'Đã tắt nhóm.');await refresh()}
 catch(error){toast(error.message,true)}finally{if(button.isConnected){button.disabled=false;button.removeAttribute('aria-busy')}}
}
(function(){
 const table=$('group-rows').closest('table');table.id='group-table';const card=table.closest('.card');const header=$('group-search').parentElement;header.classList.add('group-table-head');
 const tools=document.createElement('div');tools.className='group-bulk-tools';tools.innerHTML='<button type="button" id="group-select-all">Chọn tất cả</button><button type="button" id="groups-enable-all">Bật tất cả</button><button type="button" id="groups-disable-all">Tắt tất cả</button><span id="group-selection-count"></span>';header.after(tools);
 function checks(){return [...document.querySelectorAll('#group-rows .group-check')]}
 function update(){const items=checks(),chosen=items.filter(c=>c.checked);$('group-select-all').textContent=items.length&&chosen.length===items.length?'Bỏ chọn':'Chọn tất cả';$('group-select-all').disabled=items.length===0;$('groups-enable-all').textContent=chosen.length?'Bật đã chọn':'Bật tất cả';$('groups-disable-all').textContent=chosen.length?'Tắt đã chọn':'Tắt tất cả';$('group-selection-count').textContent=chosen.length?chosen.length+'/'+items.length+' đã chọn':items.length+' nhóm';if(!bulkBusy){$('groups-enable-all').disabled=items.length===0;$('groups-disable-all').disabled=items.length===0}}
 let bulkBusy=false;
 $('group-select-all').onclick=()=>{const items=checks(),select=!items.length||!items.every(c=>c.checked);for(const c of items){c.checked=select;select?selectedManagedGroups.add(Number(c.value)):selectedManagedGroups.delete(Number(c.value))}update()};
 document.addEventListener('change',event=>{if(event.target.classList.contains('group-check')){const id=Number(event.target.value);event.target.checked?selectedManagedGroups.add(id):selectedManagedGroups.delete(id);update()}});
 async function bulk(enabled){
  if(bulkBusy)return;const items=checks(),chosen=items.filter(c=>c.checked),targets=chosen.length?chosen:items,ids=targets.map(c=>Number(c.value));if(!ids.length)return;
  const accepted=await nctDialog((enabled?'Bật ':'Tắt ')+ids.length+' nhóm '+(chosen.length?'đã chọn':'trong danh sách hiện tại')+'?'+(enabled?'\nNhóm chưa rõ quy định link hoặc đang thao tác sẽ được bỏ qua.':'\nCác lịch chưa chạy của những nhóm này sẽ bị hủy. Nhóm đang thao tác sẽ được bỏ qua.'),{confirm:true,title:enabled?'Bật nhóm':'Tắt nhóm',accept:enabled?'Bật nhóm':'Tắt nhóm'});if(!accepted)return;
  bulkBusy=true;$('groups-enable-all').disabled=$('groups-disable-all').disabled=true;
  try{const result=await api('/api/groups-toggle',{ids,enabled});applyGroupEnabled(result.changed.changed_ids,enabled);await refresh();toast(result.message);if(result.changed.skipped.length)await nctDialog(result.changed.skipped.map(g=>g.name+': '+g.reason).join('\n'),{title:'Nhóm chưa cập nhật'})}
  catch(error){toast(error.message,true)}finally{bulkBusy=false;update()}
 }
 $('groups-enable-all').onclick=()=>bulk(true);$('groups-disable-all').onclick=()=>bulk(false);
 document.addEventListener('nct:groups-render',update);document.addEventListener('nct:state',()=>requestAnimationFrame(update));update();
})();
