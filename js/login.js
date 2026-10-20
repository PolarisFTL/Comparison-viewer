'use strict';
(() => {
const $=id=>document.getElementById(id);let identity=null;
$('login-form').onsubmit=async e=>{
  e.preventDefault();$('login-submit').disabled=true;$('login-error').textContent='正在验证身份…';
  try{
    const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('access-code').value,nickname:$('nickname').value,recovery:$('recovery-code').value})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'无法登录');
    $('access-code').value=$('recovery-code').value='';$('login-error').textContent='';
    if(data.recovery){identity={nickname:data.nickname,recovery:data.recovery,server:location.origin};$('new-recovery').value=data.recovery;$('login-form').hidden=true;$('recovery-card').hidden=false}
    else location.assign('/viewer');
  }catch(error){$('login-error').textContent=error.message}finally{$('login-submit').disabled=false}
};
$('save-recovery').onclick=()=>{if(!identity)return;const blob=new Blob([JSON.stringify(identity,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Comparison-Viewer-身份恢复码.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000)};
$('enter-viewer').onclick=()=>location.assign('/viewer');
})();
