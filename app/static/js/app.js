document.querySelectorAll('img').forEach((image)=>image.addEventListener('error',()=>{if(!image.src.includes('placeholder-bird.svg'))image.src='/static/images/placeholder-bird.svg'},{once:true}));
