(() => {
  const el=id=>document.getElementById(id);
  const mode=el('downloadSubtitleMode'), language=el('downloadSubtitleLanguage'), cpu=el('downloadSubtitleCpu'),save=el('saveDownloadSubtitleSettings'),status=el('downloadSubtitleSettingsStatus');
  let loaded=false;
  function describe() {
    el('downloadSubtitleHint').textContent=vipSubtitleOptions.describe(mode.value,language).hint;
  }
  for(const field of [mode,language,cpu])field.addEventListener('change',()=>{describe();status.textContent='Unsaved download settings';});
  save.disabled=true;
  async function load() {
    try {const data=await vipReadJSON(await fetch('/api/subtitles/download-settings'));vipSubtitleOptions.restore(mode,data.settings.mode);language.value=data.settings.language;cpu.value=String(data.settings.cpu_threads);loaded=true;describe();status.textContent='Download settings loaded.';}
    catch(error){status.textContent='Could not load download settings: '+error.message;}
    finally{save.disabled=!loaded;}
  }
  save.onclick=async()=>{
    save.disabled=true;mode.disabled=true;language.disabled=true;cpu.disabled=true;status.textContent='Saving…';
    try {const response=await fetch('/api/subtitles/download-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode.value,language:language.value,cpu_threads:Number(cpu.value)})});const data=await vipReadJSON(response);if(!response.ok)throw Error(data.error||'Could not save settings');describe();status.textContent='Saved. New subtitle jobs use these settings; queued jobs keep their settings.';}
    catch(error){status.textContent=error.message;}
    finally{save.disabled=!loaded;mode.disabled=!loaded;cpu.disabled=!loaded;describe();}
  };
  void load();
})();
