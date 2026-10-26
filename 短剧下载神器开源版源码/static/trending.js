(()=>{
 const button=document.getElementById('refreshTrending'),status=document.getElementById('trendingStatus'),list=document.getElementById('trendingList');
 function updateArrows(){document.getElementById('trendingPrev').disabled=list.scrollLeft<=1;document.getElementById('trendingNext').disabled=list.scrollLeft+list.clientWidth>=list.scrollWidth-2}
 function move(direction){list.scrollBy({left:direction*Math.max(150,list.clientWidth*.8),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
 document.getElementById('trendingPrev').onclick=()=>move(-1);
 document.getElementById('trendingNext').onclick=()=>move(1);
 list.addEventListener('scroll',updateArrows,{passive:true});
 new ResizeObserver(updateArrows).observe(list);
 async function load(refresh=false){
  if(button.disabled && status.dataset.loading==='1')return;
  button.disabled=true;status.dataset.loading='1';status.textContent=list.children.length?'Refreshing ranking…':'Loading trending dramas…';
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),35000);
  try{
   const response=await fetch('/api/trending'+(refresh?'?refresh=1':''),{signal:controller.signal}),data=await vipReadJSON(response);
   if(!response.ok)throw new Error(data.error||'Could not load trending dramas.');
   if(!Array.isArray(data.items)||!data.items.length)throw new Error('No ranked dramas were returned. Please refresh again.');
   list.replaceChildren();
   data.items.forEach(item=>{
    const card=document.createElement('button');card.type='button';card.className='trending-card';card.setAttribute('aria-label',`Rank ${item.rank}: ${item.title}. View episodes`);
    const cover=document.createElement('div');cover.className='trending-cover';
    const fallback=document.createElement('span');fallback.textContent='▶';cover.append(fallback);
    if(item.cover){const image=document.createElement('img');image.src=thumbUrl(item.cover);image.alt='';image.loading='lazy';image.onerror=()=>image.remove();cover.append(image)}
    const rank=document.createElement('span');rank.className='trending-rank';rank.textContent='#'+item.rank;cover.append(rank);
    const title=document.createElement('strong');title.textContent=item.title;
    card.append(cover,title);card.onclick=()=>openDetails(normalizeRow(item));list.append(card);
   });
   list.scrollLeft=0;updateArrows();
   const fetched=new Date(data.updated_at*1000).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
   status.textContent=data.stale?`${data.warning} Saved ${fetched}.`:`${data.items.length} ranked dramas · Updated ${fetched}`;
  }catch(error){status.textContent=(error.name==='AbortError'?'The ranking request timed out. Try Refresh ranking again.':error.message)+(list.children.length?' Showing previously loaded rankings.':'')}
  finally{clearTimeout(timeout);status.dataset.loading='0';button.disabled=false}
 }
 button.onclick=()=>load(true);load();
})();
