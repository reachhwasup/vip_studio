(()=>{
 const button=document.getElementById('refreshTrending'),status=document.getElementById('trendingStatus'),list=document.getElementById('trendingList');
 function updateArrows(){document.getElementById('trendingPrev').disabled=list.scrollLeft<=1;document.getElementById('trendingNext').disabled=list.scrollLeft+list.clientWidth>=list.scrollWidth-2}
 function move(direction){list.scrollBy({left:direction*Math.max(150,list.clientWidth*.8),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
 document.getElementById('trendingPrev').onclick=()=>move(-1);
 document.getElementById('trendingNext').onclick=()=>move(1);
 list.addEventListener('scroll',updateArrows,{passive:true});
 new ResizeObserver(updateArrows).observe(list);
 async function load(refresh=false){
  button.disabled=true;status.textContent='Loading trending dramas…';
  try{
   const response=await fetch('/api/trending'+(refresh?'?refresh=1':'')),data=await vipReadJSON(response);
   if(!response.ok)throw new Error(data.error||'Could not load trending dramas.');
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
   status.textContent=`${data.items.length} ranked dramas · Fetched ${new Date(data.updated_at*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}`;
  }catch(error){status.textContent=error.message+(list.children.length?' Showing previously loaded rankings.':'')}
  finally{button.disabled=false}
 }
 button.onclick=()=>load(true);load();
})();
