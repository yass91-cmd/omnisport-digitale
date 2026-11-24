import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css=readFileSync(new URL('../dist/assets/comfort.css',import.meta.url),'utf8');
const tokens=body=>Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[\da-f]{6})/gi)].map(match=>[match[1],match[2]]));
const light=tokens(css.match(/:root,\s*:root\[data-theme="light"\]\s*\{([^}]+)\}/)[1]);
const dark=tokens(css.match(/:root\[data-theme="dark"\]\s*\{([^}]+)\}/)[1]);
function luminance(hex){
  const rgb=hex.slice(1).match(/../g).map(value=>parseInt(value,16)/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4);
  return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
}
function contrast(a,b){const values=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (values[0]+.05)/(values[1]+.05);}
for(const [name,palette] of Object.entries({light,dark})){
  test(`${name} text, actions and status labels retain readable contrast`,()=>{
    for(const [text,background] of [['text','bg'],['text','panel'],['text','field'],['muted','panel'],['muted','panel-subtle'],['action-text','action'],['info-text','info-bg'],['available-text','available-bg'],['reserved-text','reserved-bg'],['danger-text','danger-bg']]){
      const ratio=contrast(palette[text],palette[background]);assert.ok(ratio>=4.5,`${text}/${background}: ${ratio.toFixed(2)}`);
    }
    assert.ok(contrast(palette['control-line'],palette.field)>=3,'Input boundaries must remain distinguishable.');
  });
  test(`${name} sport labels remain readable on cards and selected filters`,()=>{
    for(const sport of ['football','basketball','tennis']){
      const selector=name==='light'?new RegExp(`\\[data-sport="${sport}"\\] \\{([^}]+)\\}`):new RegExp(`:root\\[data-theme="dark"\\] \\[data-sport="${sport}"\\] \\{([^}]+)\\}`);
      const colors=tokens(css.match(selector)[1]);
      for(const background of [palette.panel,palette['panel-subtle'],colors['soft-accent']])assert.ok(contrast(colors.accent,background)>=4.5,`${sport} label against ${background}`);
    }
  });
}
