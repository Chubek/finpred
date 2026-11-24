/* Highlight.js language registration: hljs.registerLanguage('ottomat', ottomat); */
export default function ottomat(hljs) {
 return {name:'Ottomat',aliases:['ottmat'],case_insensitive:false,
 keywords:{keyword:'ottomat ottmat input source transform algorithm strategy gate output profile effect import let emit',literal:'pure read record required optional',built_in:'target_bps curve objective'},
 contains:[{className:'type',begin:/\b[a-z][a-z0-9_.-]*@[0-9]+\b/},hljs.C_NUMBER_MODE,{className:'operator',begin:/=/}]};
}
