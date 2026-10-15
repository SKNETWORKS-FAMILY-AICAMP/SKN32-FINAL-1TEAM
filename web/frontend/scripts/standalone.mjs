import fs from 'node:fs';
import path from 'node:path';
const dist=path.resolve('dist');
let html=fs.readFileSync(path.join(dist,'index.html'),'utf8');
html=html.replace(/<script type="module" crossorigin src="([^"]+)"><\/script>/g,(_,src)=>'<script>'+fs.readFileSync(path.join(dist,src),'utf8').replaceAll('</script','<\\/script')+'</script>');
html=html.replace(/<link rel="stylesheet" crossorigin href="([^"]+)">/g,(_,src)=>'<style>'+fs.readFileSync(path.join(dist,src),'utf8')+'</style>');
// Execute the precompiled app only after its root has been parsed.
const script=html.match(/<script>[\s\S]*?<\/script>/)?.[0];
if(!script)throw new Error('Built script was not found');
html=html.replace(script,'').replace('</body>',()=>script+'</body>');
fs.writeFileSync('../S-Brain-redesign.html',html);
console.log('Created standalone S-Brain-redesign.html ('+Buffer.byteLength(html)+' bytes)');
