/* Load before styles so a saved preference is applied before the first paint. */
(() => {
  const root=document.documentElement,key="omni-color-theme";
  let theme="light";
  try{const saved=localStorage.getItem(key);if(saved==="light"||saved==="dark")theme=saved;}catch{}
  root.dataset.theme=theme;
  function mount(){
    const nav=document.querySelector('.header-nav');if(!nav)return;
    const button=document.createElement('button');button.type='button';button.className='theme-toggle';
    function label(){const dark=root.dataset.theme==='dark';button.textContent=dark?'Light view':'Dark view';button.setAttribute('aria-label',dark?'Switch to light colors':'Switch to dark colors');}
    button.addEventListener('click',()=>{
      root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';
      try{localStorage.setItem(key,root.dataset.theme);}catch{}
      label();window.dispatchEvent(new CustomEvent('omni-theme-change'));
    });label();nav.append(button);
    window.addEventListener('storage',event=>{if(event.key===key&&(event.newValue==='light'||event.newValue==='dark')){root.dataset.theme=event.newValue;label();window.dispatchEvent(new CustomEvent('omni-theme-change'));}});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
