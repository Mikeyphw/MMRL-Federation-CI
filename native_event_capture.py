#!/usr/bin/env python3
"""Observe native events without changing dispatch, scheduling or truth.
Raw commands, output, arbitrary metadata and environment are not exported.
The resulting projection still requires independent node-to-contract correlation.
"""
import json
import pathlib
import sys

FIELDS=('run_id','event_id','sequence','node_id','parent_id','label','kind','source','status','exit_code')

def capture(event):
    row={'event_type':type(event).__name__}
    for key in FIELDS:
        value=getattr(event,key,None)
        if hasattr(value,'value'): value=value.value
        if isinstance(value,(str,int,float,bool)) and len(str(value))<=512:
            row[key]=value
    return row

def main(path, argv):
    from devtool.cli import main as native_main
    from devtool.core.events import get_event_bus, RunStarted, RunFinished, NodeDiscovered, NodeStarted, NodeFinished, NodeBlocked
    bus=get_event_bus()
    failures=[]
    with pathlib.Path(path).open('x',encoding='utf-8') as output:
        def listener(event):
            if not isinstance(event,(RunStarted,RunFinished,NodeDiscovered,NodeStarted,NodeFinished,NodeBlocked)):
                return
            try:
                output.write(json.dumps(capture(event),sort_keys=True)+'\n'); output.flush()
            except Exception as exc:
                failures.append(type(exc).__name__)
                raise
        bus.subscribe_all(listener)
        try:
            rc=native_main(argv)
        finally:
            bus.unsubscribe_all(listener)
        if failures:
            print('N05G_EVENT_CAPTURE_FAILED',file=sys.stderr)
            return rc or 1
        if output.tell()==0:
            print('N05G_EVENT_CAPTURE_EMPTY',file=sys.stderr)
            return rc or 1
        return rc

if __name__=='__main__':
    sys.exit(main(sys.argv[1],sys.argv[2:]))
