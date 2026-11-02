"""Exercise the generated click handler in a browser with mocked clipboard writes."""
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from create_report import email_page


def test_clipboard_click_paths_in_browser(tmp_path):
    candidates = [shutil.which(name) for name in ('chromium', 'chromium-browser', 'google-chrome', 'msedge')]
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
            candidates.append(str(Path(os.environ.get(variable, '')) / relative))
    browser = next((path for path in candidates if path and Path(path).is_file()), None)
    if not browser:
        pytest.skip('A Chromium browser is needed for the clipboard JavaScript check')

    checks = r"""
<script>
(async()=>{
  const results=[];
  const scenarios=[
    {name:'selection',native:'ok',expected:'rich'},
    {name:'modern',native:'false',expected:'rich'},
    {name:'selection error',native:'throw',expected:'rich'},
    {name:'plain',native:'false',htmlFails:true,expected:'plain'},
    {name:'missing clipboard',native:'false',missing:true,expected:'manual'},
    {name:'denied',native:'throw',htmlFails:true,textFails:true,expected:'manual'},
    {name:'missing execCommand',native:'missing',expected:'rich'}
  ];
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  for(const scenario of scenarios){
    try{
      const calls=[];
      const payload={};
      let richItems;
      const el=document.getElementById('email-body');
      const selection=window.getSelection();
      const before=document.createRange();before.selectNodeContents(document.getElementById('outside'));
      selection.removeAllRanges();selection.addRange(before);
      const originalSelection=selection.toString();
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:scenario.missing?undefined:{
        write:async items=>{calls.push('html');if(scenario.htmlFails)throw Error('denied');richItems=items;},
        writeText:async text=>{calls.push('plain');if(scenario.textFails)throw Error('denied');payload['text/plain']=text;}
      }});
      window.ClipboardItem=class {constructor(data){this.data=data;}};
      window.Blob=class {constructor(parts,options){this.content=parts.join('');this.type=options.type;}};
      document.execCommand=scenario.native==='missing'?undefined:()=>{
        calls.push('selection');
        assert(selection.getRangeAt(0).startContainer===el,'wrong selected content');
        if(scenario.native==='throw')throw Error('denied');
        if(scenario.native==='false')return false;
        const event=new Event('copy',{cancelable:true,bubbles:true});
        Object.defineProperty(event,'clipboardData',{value:{setData:(type,value)=>{payload[type]=value;}}});
        document.dispatchEvent(event);
        assert(event.defaultPrevented,'copy payload was not supplied');
        return true;
      };
      // Trigger the actual generated button; clipboard operations are mocked.
      document.querySelector('button').click();
      await new Promise(resolve=>setTimeout(resolve,0));
      const status=document.getElementById('copy-status').textContent;
      if(scenario.expected==='rich'){
        assert(status.startsWith('Másolva.'),'rich copy not confirmed');
        if(richItems){
          payload['text/html']=richItems[0].data['text/html'].content;
          payload['text/plain']=richItems[0].data['text/plain'].content;
        }
        assert(payload['text/html']===el.innerHTML,'table formatting or links lost');
        assert(payload['text/plain']===el.innerText,'plain alternative differs');
      }else if(scenario.expected==='plain'){
        assert(status.startsWith('Egyszerű szöveg másolva.'),'plain fallback not labelled');
        assert(payload['text/plain']===el.innerText,'wrong fallback text');
      }else{
        assert(status.startsWith('A böngésző letiltotta'),'failure reported as success');
        assert(selection.getRangeAt(0).startContainer===el,'manual fallback did not select email');
      }
      if(scenario.expected!=='manual'){
        assert(selection.toString()===originalSelection,'previous selection not restored');
        assert(!status.includes('Ctrl+C'),'successful copy still requests Ctrl+C');
      }
      if(scenario.native==='ok')assert(calls.join(',')==='selection','unnecessary permission request');
      const lateEvent=new Event('copy',{cancelable:true});
      Object.defineProperty(lateEvent,'clipboardData',{value:{setData:()=>{throw Error('copy listener leaked');}}});
      document.dispatchEvent(lateEvent);
      assert(!lateEvent.defaultPrevented,'copy listener leaked');
      results.push({name:scenario.name,ok:true});
    }catch(error){results.push({name:scenario.name,error:String(error)});}
  }
  const output=document.createElement('pre');output.id='test-results';output.textContent=JSON.stringify(results);
  document.body.appendChild(output);
})();
</script>
"""
    page = email_page('<table style="border-collapse:collapse"><tr><td><a href="https://example.org">Árvíztűrő tender</a></td></tr></table>')
    page = page.replace('</body>', '<p id="outside">Korábbi kijelölés</p>' + checks + '</body>')
    target = tmp_path / 'clipboard.html'
    target.write_text(page, encoding='utf-8')
    run = subprocess.run([browser, '--headless', '--disable-gpu', '--no-sandbox', '--disable-background-networking',
                          '--no-first-run', '--no-default-browser-check',
                          '--user-data-dir=' + str(tmp_path / 'browser'), '--virtual-time-budget=3000',
                          '--dump-dom', target.as_uri()], capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr.decode('utf-8', errors='replace')
    dom = run.stdout.decode('utf-8')
    match = re.search(r'<pre id="test-results">(.*?)</pre>', dom, re.S)
    assert match, dom + run.stderr.decode('utf-8', errors='replace')
    results = json.loads(html.unescape(match.group(1)))
    assert len(results) == 7
    assert all(result.get('ok') for result in results), results
