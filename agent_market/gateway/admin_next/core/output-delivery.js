// Delivery is Edge-first even when an Agent must compute on the private server.
export function wantsEdgeOutput(path, method) {
  const url=new URL(path,location.href);
  return url.origin===location.origin&&['GET','POST'].includes(method)&&
    /^(?:\/admin\/api\/(?:v2\/catalog-tools\/)?test-reports(?:\/[^/]+)?|\/admin\/api\/(?:v2\/catalog-tools\/)?test\/execute|\/admin\/api\/(?:v2\/catalog-tools\/)?connections\/[1-9][0-9]*\/contracts\/[^/]+\/test|\/admin\/api\/workflows\/(?:[1-9][0-9]*\/run|runs\/[^/]+)|\/admin\/api\/(?:workflow-workspaces|v2\/(?:workspace-panels|staff-workspaces))\/[^/]+\/(?:.*?\/)?(?:runs(?:\/[^/]+)?|product-test(?:\/[^/]+)?|app-factory\/model-proposals(?:\/[^/]+)?|advancement\/support\/assistant|remote-a2a\/tasks(?:\/[^/]+(?:\/messages)?)?))$/.test(url.pathname);
}

export async function resolveEdgeOutput(response,local,guard=()=>{}) {
  if(!response.headers.get('Content-Type')?.startsWith('application/vnd.agentconcierge.edge-output+json'))return response;
  const value=await response.json();guard();
  if(value?._edge_output_v1!==true||value.base!=='https://agentconcierge.biz'||!/^er_[a-f0-9]{32}$/.test(value.run_id)||
      value.path!=='/api/edge-gateway/v1/outputs/'+value.run_id||typeof value.access_token!=='string')throw Error('The retained output authority is unavailable.');
  try {
    const result=await fetch(value.base+value.path,{credentials:'omit',cache:'no-store',signal:AbortSignal.timeout(8000),
      headers:{Authorization:'Bearer '+value.access_token}});
    if(!result.ok)throw Error('Edge output unavailable');
    const output=await result.json();guard();
    if(!Number.isInteger(output.status)||output.status<200||output.status>599||!Object.hasOwn(output,'body'))throw Error('Output contract');
    const headers=new Headers(response.headers);headers.delete('Content-Length');headers.delete('Content-Encoding');headers.delete('ETag');
    headers.set('Content-Type','application/json');headers.set('X-Execution-Delivery','edge');
    return new Response(JSON.stringify(output.body),{status:output.status,headers});
  } catch(error) {
    guard();
    // Fetch only the retained response; never retry the original Agent request.
    const restored=await local('/admin/api/v2/gateway/edge-output/'+value.run_id),headers=new Headers(restored.headers);
    if(response.headers.get('X-Admin-Audit-State')==='pending')headers.set('X-Admin-Audit-State','pending');
    return new Response(restored.body,{status:restored.status,headers});
  }
}
