#!/usr/bin/env python3
"""Run only on the isolated GitHub-hosted Linux coordinator. No push or device actions."""
import hashlib, json, os, pathlib, re, subprocess, sys, tomllib

CURRENT_STAGE = "entry"
EVIDENCE = None

PINS = {'mmrl-next': ('Mikeyphw/MMRL', '0750675f3ff347c7487e25bf9f155dbc023769ea', 'next'), 'mmrl-lsposed': ('Mikeyphw/MMRL-LSPosed', 'a63961f35a812dec9bfe6c6954cb0525d2f4ce8a', 'main'), 'mmrl-shared': ('Mikeyphw/MMRL-Shared', '1bd273c7c386b4116144db5c36659ead47cd299a', 'main')}
DEV = '860671c4782ce58b3344871248456c516fb8ce08'
LOCK_BYTES = '4d32ce000eb309a8a346232a9d16fa522e695cdb97ea2bb347bd028553201429'
TARGETS = {'mmrl-next':'mmrl_next', 'mmrl-lsposed':'lsposed_app'}

def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)

def stage(name):
    global CURRENT_STAGE
    CURRENT_STAGE = name
    print('N05G_HOSTED_STAGE='+name, flush=True)
    if EVIDENCE is not None:
        write(EVIDENCE/'progress.json', receipt('running'))

def cmd(*argv, cwd=None, capture=False):
    print('+', ' '.join(map(str,argv)), flush=True)
    r = subprocess.run(list(map(str,argv)), cwd=cwd, text=True, stdout=subprocess.PIPE if capture else None, check=True)
    return r.stdout.strip() if capture else None

def git(root,*argv,capture=False):
    return cmd('git','-C',root,*argv,capture=capture)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def write(path, obj):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True)+'\n')
    tmp.replace(path)

def machine(raw):
    need(isinstance(raw,dict) and raw.get('ok') is True and raw.get('exit_code') == 0 and isinstance(raw.get('data'),dict), 'NATIVE_MACHINE_RESULT_REFUSED')
    return raw['data']

def check_portable(lock, m):
    for k in ('lock_digest','graph_digest','equivalence_digest'):
        need(lock.get(k)==m['portable'][k], 'PORTABLE_'+k.upper()+'_MISMATCH')
    need(lock.get('workflow')=='validate-both' and lock.get('drift_policy')=='fail','LOCK_SUBJECT_POLICY_MISMATCH')
    rows={r['repository']:r for r in lock['repositories']}
    need(set(rows)==set(TARGETS) and len(lock['repositories'])==2,'LOCK_MEMBERSHIP_MISMATCH')
    for alias,row in rows.items():
        expected=m['children'][alias]
        for k in ('start_commit','head_tree','index_tree','index_fingerprint','config_digest','source_digest','equivalence_digest','branch','head_ref','upstream','repository_remote_fingerprint'):
            need(row.get(k)==expected[k],f'PORTABLE_CHILD_MISMATCH:{alias}:{k}')
        need(row['dirty'] is False and row['commit_policy']=='none', f'CHILD_DIRTY_OR_COMMIT_POLICY:{alias}')

def check_plan(plan, m):
    check_portable(plan['source_lock'],m)
    need(plan.get('workflow')=='validate-both' and len(plan['nodes'])==7,'PLAN_SHAPE_MISMATCH')
    actual={(n['repository'],n['target'],n['workflow'],n['key']) for n in plan['nodes'] if not n.get('synthetic')}
    need(actual=={tuple(x) for x in m['nodes']} and len(actual)==6,'PLAN_NODES_MISMATCH')

def checkout(root, alias, row):
    repo,sha,branch=PINS[alias]
    need(not root.exists(), 'WORKSPACE_COLLISION:'+alias)
    root.mkdir()
    git(root,'init','--initial-branch='+branch)
    git(root,'remote','add','origin','https://github.com/'+repo+'.git')
    git(root,'fetch','--no-tags','--progress','origin',sha)
    git(root,'checkout','-B',branch,sha)
    if row is not None:
        need(row['branch']==branch and row['head_ref']=='refs/heads/'+branch,'UNSUPPORTED_BRANCH:'+alias)
        u=row['upstream']
        if u['configured']:
            need(u['resolved'] and not u['partial_configuration'] and u['remote']=='origin' and u['merge_ref']=='refs/heads/'+branch and u['name']=='refs/remotes/origin/'+branch and u['sha']==sha,'UNSUPPORTED_UPSTREAM:'+alias)
            git(root,'update-ref',u['name'],sha)
            git(root,'config','branch.'+branch+'.remote','origin')
            git(root,'config','branch.'+branch+'.merge',u['merge_ref'])
        else:
            need(not u['partial_configuration'],'PARTIAL_UPSTREAM:'+alias)
        locator=row['origin']
        allowed={p+repo+s for p in ('git@github.com:','ssh://git@github.com/','https://github.com/') for s in ('','.git')}
        need(locator in allowed and digest(locator.encode())==row['repository_remote_fingerprint'],'REMOTE_IDENTITY:'+alias)
    if alias in TARGETS:
        gl=git(root,'ls-tree','HEAD','--','third_party/mmrl-shared',capture=True).split()
        need(gl==['160000','commit',PINS['mmrl-shared'][1],'third_party/mmrl-shared'],'GITLINK_MISMATCH:'+alias)
        module=git(root,'config','-f','.gitmodules','--get','submodule.third_party/mmrl-shared.url',capture=True)
        need(module=='https://github.com/Mikeyphw/MMRL-Shared.git','SUBMODULE_REMOTE_MISMATCH')
        git(root,'-c','protocol.file.allow=never','submodule','update','--init','--recursive','--','third_party/mmrl-shared')
        need(git(root/'third_party/mmrl-shared','rev-parse','HEAD',capture=True)==PINS['mmrl-shared'][1],'SUBMODULE_SHA_MISMATCH')
        git(root,'remote','set-url','origin',row['origin'])
    need(git(root,'rev-parse','HEAD',capture=True)==sha,'SOURCE_SHA_MISMATCH:'+alias)
    need(not git(root,'status','--porcelain','--untracked-files=all','--ignore-submodules=none',capture=True),'DIRTY_SOURCE:'+alias)

def main(coord,ev):
    stage('host-boundary')
    need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted' and os.environ.get('RUNNER_OS')=='Linux' and os.environ.get('RUNNER_ARCH')=='X64','NOT_GITHUB_HOSTED_LINUX')
    need(os.environ.get('GITHUB_REPOSITORY')=='Mikeyphw/MMRL-Federation-CI' and os.environ.get('GITHUB_REF')=='refs/heads/main' and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch','HOSTED_REPOSITORY_EVENT_REF_MISMATCH')
    need(git(coord,'rev-parse','HEAD',capture=True)==os.environ['GITHUB_SHA'],'HARNESS_SHA_MISMATCH')
    m=json.loads((coord/'source-contract.json').read_text())
    need(m['accepted_lock_sha256']==LOCK_BYTES and m['devtool_sha']==DEV,'SOURCE_CONTRACT_ANCHOR_MISMATCH')
    need(digest((coord/'.devtool.toml').read_bytes())==m['projected_config_sha256'],'PROJECTED_CONFIG_CHANGED')
    need(set(m['children'])==set(TARGETS),'SOURCE_CONTRACT_MEMBERSHIP')
    stage('exact-source-checkout')
    config=tomllib.loads((coord/'.devtool.toml').read_text())
    enroll=config['federation']['repositories']
    need(set(enroll)==set(PINS),'ENROLLMENT_MEMBERSHIP')
    for alias in PINS:
        need(enroll[alias]['path']=='../'+alias,'ENROLLMENT_PATH_MISMATCH')
        checkout(coord.parent/alias,alias,m['children'].get(alias))
    stage('install-pinned-native-devtool')
    tmp=pathlib.Path(os.environ['RUNNER_TEMP']).resolve()
    source=tmp/'n05g-devtool-source'; venv=tmp/'n05g-devtool-venv'
    cmd('git','clone','--no-checkout','https://github.com/Mikeyphw/devtool.git',source)
    git(source,'checkout','--detach',DEV)
    need(git(source,'rev-parse','HEAD',capture=True)==DEV,'DEVTOOL_SHA_MISMATCH')
    cmd(sys.executable,'-m','venv',venv)
    py=venv/'bin/python'; executable=venv/'bin/devtool'
    cmd(py,'-m','pip','install',source)
    for k,d in [('DEVTOOL_XDG_DIR','n05g-state'),('XDG_CONFIG_HOME','n05g-config'),('XDG_STATE_HOME','n05g-xdg-state')]:
        path=tmp/d; path.mkdir(mode=0o700,exist_ok=False); os.environ[k]=str(path)
    os.environ['DEVTOOL_EXECUTION_PRESENTATION']='plain'
    os.environ['DEVTOOL_JOB_UI']='plain'
    # All source checkouts came from the independently reviewed public repositories.
    # Never pass GH_TOKEN/GITHUB_TOKEN or signing secrets to child processes.
    for k in ('GH_TOKEN','GITHUB_TOKEN','MMRL_FEDERATION_TOKEN','SSH_AUTH_SOCK'):
        os.environ.pop(k,None)
    # This source revision has no root --version option. Do not infer its
    # source identity from the package's version string (1.1.0 at this pin).
    # Check installed package metadata, entry point and schema instead.
    identity = cmd(py, '-c', """import importlib.metadata as m, json, pathlib, devtool
from devtool.core_parser import canonical_cli_schema
from devtool.cli import build_parser
p=pathlib.Path(devtool.__file__).resolve()
d=m.distribution('devtool')
assert p.is_relative_to(pathlib.Path(__import__('sys').prefix).resolve())
assert any(x.name=='devtool' and x.value=='devtool.cli:main' for x in d.entry_points)
s=canonical_cli_schema(); assert s['schema_version']==2
args=build_parser().parse_args(['-r','.', 'federation','plan','validate-both'])
assert args.command=='federation'
print(json.dumps({'distribution_version':d.version,'schema_version':s['schema_version'],'cli_federation_plan_parsed':True}))""", capture=True)
    write(ev/'launcher-identity.json', {'devtool_sha':DEV, **json.loads(identity)})
    cmd(executable, '--help')
    print('N05G_HOSTED_LAUNCHER_SMOKE_PASS', flush=True)
    def native(label,*args):
        print('N05G_NATIVE_COMMAND=federation '+' '.join(args)+' --json',flush=True)
        out=ev/(label+'.json')
        with out.open('x') as f:
            argv=[str(executable),'-r',str(coord),'federation',*args,'--json']
            if label=='run':
                argv=[str(py),str(coord/'native_event_capture.py'),str(ev/'native-events.jsonl'),*argv[1:]]
            r=subprocess.Popen(argv,stdout=subprocess.PIPE,text=True)
            for line in r.stdout:
                f.write(line); f.flush(); print(line,end='',flush=True)
            rc=r.wait()
        write(ev/(label+'-exit.json'), {'operation':label,'exit_code':rc})
        if rc != 0: raise subprocess.CalledProcessError(rc, argv)
        return machine(json.loads(out.read_text()))
    stage('portable-lock-before-freeze')
    plan=native('plan','plan','validate-both'); check_plan(plan,m)
    for label,operation in [('gate1','preflight'),('gate2','gate2')]:
        g=native(label,operation); need(g.get('status')=='ok' and g.get('ok') is True,'PREFLIGHT_REFUSED:'+label)
    stage('new-host-local-strict-lock')
    frozen=native('freeze','plan','validate-both','--freeze')
    # The canonical freeze command returns the plan; verify via independent lock command.
    lk=native('lock','lock'); local=lk['lock']; check_portable(local,m)
    need(lk['verification']['matched'] is True and lk['verification']['mode']=='strict-local' and lk['verification']['drift']==[],'HOST_LOCAL_LOCK_NOT_MATCHED')
    dag=native('dag','dag-contract','validate-both','--require-frozen')
    need(dag['status']=='locally_frozen' and dag['frozen_source_lock']['status']=='matching' and len(dag['nodes'])==6,'HOST_DAG_REFUSED')
    # Native scheduler proof, using the same production provider selection and policy.
    stage('hosted-placement')
    cmd(py,coord/'native_verify.py','placement',coord,ev)
    stage('actual-native-federation-run')
    report=native('run','run','validate-both','--drift-policy','fail')
    need(report['status']=='succeeded' and report['exit_code']==0,'PARENT_RUN_FAILED')
    need(report['plan']['source_lock']==local,'EXECUTED_LOCK_CHANGED')
    check_plan(report['plan'],m)
    stage('durable-native-evidence')
    cmd(py,coord/'native_verify.py','checkpoint',coord,ev)
    for alias,(_,sha,_) in PINS.items():
        root=coord.parent/alias
        need(git(root,'rev-parse','HEAD',capture=True)==sha,'POSTRUN_HEAD_CHANGED:'+alias)
        need(not git(root,'diff','--name-only','HEAD','--',capture=True),'POSTRUN_TRACKED_CHANGE:'+alias)
        if alias in TARGETS:
            need(git(root/'third_party/mmrl-shared','rev-parse','HEAD',capture=True)==PINS['mmrl-shared'][1],'POSTRUN_SUBMODULE_SHA_CHANGED')
    write(ev/'hosted-result.json',{'schema':1,'verdict':'NATIVE_PARENT_AND_CHILD_CHECKPOINT_ACCEPTED_PENDING_INDEPENDENT_CI_REVIEW','repository':os.environ['GITHUB_REPOSITORY'],'harness_sha':os.environ['GITHUB_SHA'],'run_id':int(os.environ['GITHUB_RUN_ID']),'attempt':int(os.environ['GITHUB_RUN_ATTEMPT']),'source_lock_digest':local['lock_digest'],'parent_run_id':report['parent_run_id'],'child_run_ids':{x['repository']:x['run_id'] for x in report['children']},'release_qualified':False,'device_qualified':False,'independently_verified':False})
    print('N05G_HOSTED_NATIVE_PARENT_CHILD_GATE_PASS',flush=True)

def receipt(status, rc=None, error=None):
    # Deliberately omit command arguments, environment, raw exception text,
    # credentials and log content. The full error is visible in Actions logs.
    return {'schema':1, 'status':status, 'stage':CURRENT_STAGE,
            'repository':os.environ.get('GITHUB_REPOSITORY',''),
            'harness_sha':os.environ.get('GITHUB_SHA',''),
            'run_id':os.environ.get('GITHUB_RUN_ID',''),
            'attempt':os.environ.get('GITHUB_RUN_ATTEMPT',''),
            'exit_code':rc, 'exception_type':type(error).__name__ if error else None,
            'devtool_sha':DEV, 'release_qualified':False, 'device_qualified':False}

def entry(coord, ev):
    global EVIDENCE, CURRENT_STAGE
    EVIDENCE=ev; CURRENT_STAGE='entry'
    ev.mkdir(parents=True, exist_ok=True)
    write(ev/'progress.json',receipt('running'))
    try:
        main(coord,ev)
    except BaseException as exc:
        rc=exc.returncode if isinstance(exc,subprocess.CalledProcessError) else 130 if isinstance(exc,KeyboardInterrupt) else 1
        rc=128-rc if rc<0 else rc or 1
        write(ev/'terminal-receipt.json',receipt('failed',rc,exc))
        print('N05G_HOSTED_REFUSED: '+str(exc),file=sys.stderr,flush=True)
        import traceback
        traceback.print_exc()
        return rc
    write(ev/'terminal-receipt.json',receipt('completed',0))
    return 0

if __name__=='__main__':
    sys.exit(entry(pathlib.Path(sys.argv[1]).resolve(),pathlib.Path(sys.argv[2]).resolve()))
