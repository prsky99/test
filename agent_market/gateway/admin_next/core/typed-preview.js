import * as ui from './ui.js';
import {pearlFlow} from './pearl-flow.js';

// Only the already-authorized definition is used. The preview grants no rights.
export function typedPreview(definition,run=null){
  if(!definition || !Array.isArray(definition.nodes) || definition.nodes.length>10)throw Error('최대 10단계의 유효한 정의를 입력하세요.');
  const nodes=definition.nodes.map(node=>({id:node.id,name:node.id+' · '+node.contract_id,resource_id:node.resource_id,kind:'mcp'}));
  const edges=definition.nodes.flatMap(node=>(Array.isArray(node.after)?node.after:[]).map(id=>({source:id,target:node.id})));
  const states=Object.fromEntries((run?.steps || []).map(step=>[step.node_id,step.status]));
  return pearlFlow(ui,{nodes,edges},{states});
}
