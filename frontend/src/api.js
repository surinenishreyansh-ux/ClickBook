export const BASE=(import.meta.env.VITE_API_BASE_URL||'').replace(/\/$/,'');
export const imageUrl=(code,id,size='thumb')=>`${BASE}/api/g/${encodeURIComponent(code)}/photos/${encodeURIComponent(id)}/image?size=${size}`;
export const guestUrl=(code)=>`${window.location.origin}/g/${code}`;
export const inviteUrl=(code)=>`${window.location.origin}/invite/${code}`;
export function readToken(){return localStorage.getItem('clickbook_auth')||''}
export function saveToken(value){if(value)localStorage.setItem('clickbook_auth',value);else localStorage.removeItem('clickbook_auth')}
export async function api(path, opts={}){
  const token=readToken();
  const headers={...(opts.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(token?{'Authorization':'Bearer '+token}:{}),...(opts.headers||{})};
  let r;
  try{r=await fetch(BASE+path,{...opts,headers})}catch(e){throw new Error('Cannot connect to Clickbook. Check your internet connection or backend server.')}
  if(!r.ok){const j=await r.json().catch(()=>({}));const detail=j.detail;
    throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(i=>i.msg).join('; '):`Request failed (${r.status})`)}
  return r.status===204?null:r.json();
}
export async function downloadAuthed(path,filename='photo.jpg'){
 const r=await fetch(BASE+path,{headers:{Authorization:'Bearer '+readToken()}});
 if(!r.ok)throw new Error('Unable to download this photo');
 const blob=await r.blob(),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
}
