#!/usr/bin/env python3
"""Consumer of the exact pinned Devtool native plan, scheduler and checkpoint."""
import json, pathlib, sys
from devtool.config import load_project_config
from devtool.execution_environments import detect_current_environment
from devtool.federation_capabilities import project_capability_dependencies
from devtool.federation_plan import build_federated_plan
from devtool.federation_execution import _provider_capabilities_for_workflow
from devtool.federation_scheduler import build_federated_schedule
from devtool.federation_resume import load_checkpoint

def need(ok,msg):
    if not ok: raise RuntimeError(msg)
mode,coord,ev=sys.argv[1],pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3])
config=load_project_config(str(coord),str(coord/'.devtool.toml'),target_name='',variant_name='',allow_ambiguous_target=True,allow_ambiguous_project_kind=True)
if mode=='placement':
    need(detect_current_environment()=='desktop-linux','HOSTED_SUBSTRATE_NOT_DESKTOP_LINUX')
    workflow=project_capability_dependencies(config,config.federation.workflows['validate-both'])
    plan=build_federated_plan(config,'validate-both'); policy=config.workspace.scheduler
    providers=_provider_capabilities_for_workflow(config,workflow,plan)
    need({p.provider_id for p in providers}=={'local'},'UNEXPECTED_REMOTE_PROVIDERS')
    schedule=build_federated_schedule(workflow,plan,parallel_requested=False,max_parallel=1,max_gradle=max(0,int(policy.max_gradle_nodes)),max_dotnet=max(0,int(policy.max_dotnet_nodes)),provider_capabilities=providers,provider_budgets=policy.provider_budgets,resource_budgets=policy.resource_budgets,max_local_gradle=policy.max_local_gradle,max_ssh_oci_gradle=policy.max_ssh_oci_gradle,max_tablet_gradle=policy.max_tablet_gradle,max_android_device=policy.max_android_device)
    need(len(schedule.nodes)==2 and {n.repository for n in schedule.nodes}=={'mmrl-next','mmrl-lsposed'},'SCHEDULE_REPOSITORIES_MISMATCH')
    need(all(n.provider_id=='local' and n.execution_environment in {'auto','desktop-linux'} and n.resource_class!='device-exclusive' for n in schedule.nodes),'UNSAFE_SCHEDULE')
    (ev/'placement.json').write_text(json.dumps(schedule.as_dict(),indent=2)+'\n')
    print('N05G_HOSTED_PLACEMENT_PASS',flush=True)
elif mode=='checkpoint':
    report=json.loads((ev/'run.json').read_text())['data']
    parent=report['parent_run_id']; children=report['children']
    need(bool(parent) and len(children)==2 and {c['repository'] for c in children}=={'mmrl-next','mmrl-lsposed'},'CHILD_REPORT_MEMBERSHIP')
    ids={c['run_id'] for c in children}
    need(len(ids)==2 and '' not in ids and parent not in ids,'CHILD_RUN_IDENTITY')
    checkpoint=load_checkpoint(config,parent)
    need(checkpoint['status']=='succeeded' and checkpoint['exit_code']==0 and checkpoint['workflow']=='validate-both' and checkpoint['mode']=='run' and checkpoint['source_lock']==report['plan']['source_lock'],'CHECKPOINT_STATUS_OR_SOURCE_MISMATCH')
    rows={r['run_id']:r for r in checkpoint['children']}
    need(set(rows)==ids and len(checkpoint['children'])==2,'CHECKPOINT_CHILD_MEMBERSHIP')
    for c in children:
        child_id=c['run_id']; line=c['run_lineage']; row=rows[child_id]
        need(c['status']=='succeeded' and c['exit_code']==0 and c['lifecycle']=='executed','CHILD_NOT_EXECUTED_SUCCESSFULLY')
        need(line['parent_run_id']==parent and line['child_run_id']==child_id and line['repository']==c['repository'] and line['federation_workflow']=='validate-both','CHILD_LINEAGE_MISMATCH')
        need(c['placement']['provider_id']=='local','CHILD_PROVIDER_MISMATCH')
        need(row['run_lineage']==line and row['status']==c['status'] and row['exit_code']==0 and row['repository']==c['repository'] and row['step_id']==c['step_id'],'DURABLE_CHECKPOINT_CHILD_MISMATCH')
    (ev/'checkpoint.json').write_text(json.dumps(checkpoint,indent=2)+'\n')
    print('N05G_HOSTED_CHECKPOINT_PASS',flush=True)
else: raise SystemExit('Unknown operation')
