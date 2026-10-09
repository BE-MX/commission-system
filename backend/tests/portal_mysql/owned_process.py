"""Finite metadata only, including cleanup faults after a partial-output timeout."""
import re
import subprocess


def safe_runner_summary(exit_code, stdout, stderr, *, timed_out=False):
    """Discard arbitrary output; retain only fixed classifications and source numbers."""
    category = 'none' if exit_code == 0 else 'process_failure'
    if timed_out or 'TimeoutError' in stderr or re.search(r'Timeout \d+ms', stderr):
        category = 'timeout'
    elif 'AssertionError' in stderr:
        category = 'assertion'
    frames = re.findall(r'(?:applicationTrade|applicationOnboarding|applicationCapabilities|applicationSurfaces|applicationAccessibility|applicationReorder|applicationDecisions|applicationInventory)\.browser\.mjs:(\d{1,6}):(\d{1,6})\b', stderr)
    return {'exit_code': int(exit_code), 'timed_out': bool(timed_out),
        'phase': 'application_ui', 'failure_category': category,
        'stdout_bytes': len(stdout.encode('utf-8')), 'stderr_bytes': len(stderr.encode('utf-8')),
        'source_frames': [{'line': int(line), 'column': int(column)} for line, column in frames[-3:]],
        'raw_output_retained': False}


def scrub_exception(error):
    seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error));next_error=error.__context__ or error.__cause__
        for name,value in [('output',None),('stdout',None),('stderr',None),('cmd',[]),('doc',''),('object',b'')]:
            if hasattr(error,name):
                try:setattr(error,name,value)
                except (AttributeError,TypeError):pass
        error.args=('Owned process failure',)
        error.__traceback__=error.__context__=error.__cause__=None
        error=next_error


def consume_owned_process(command,private_input,*,timeout=240):
    stdout=stderr='';child=None;timed_out=False;cleanup_failure=False;reaped=True
    summary={'exit_code':-1,'timed_out':False,'phase':'application_ui','failure_category':'process_failure','stdout_bytes':0,'stderr_bytes':0,'source_frames':[],'raw_output_retained':False}
    try:
        child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            stdout,stderr=child.communicate(input=private_input,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            timed_out=True;scrub_exception(error)
            try:
                killed=subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
                if killed.returncode!=0:cleanup_failure=True
            except Exception as error:
                cleanup_failure=True;scrub_exception(error)
            if child.poll() is None:
                try:child.kill()
                except Exception as error:cleanup_failure=True;scrub_exception(error)
            try:stdout,stderr=child.communicate(timeout=15)
            except Exception as error:cleanup_failure=True;scrub_exception(error)
        summary = safe_runner_summary(child.returncode if child.returncode is not None else -1,
            stdout, stderr, timed_out=timed_out)
    except Exception as error:
        scrub_exception(error)
        summary['failure_category']='process_failure'
    finally:
        if child is not None:
            if child.poll() is None:
                try:child.kill();child.wait(timeout=5)
                except Exception as error:cleanup_failure=True;scrub_exception(error)
            reaped=child.poll() is not None
            child._input=None
            if reaped:
                for stream in (child.stdin,child.stdout,child.stderr):
                    if stream is not None:
                        try:stream.close()
                        except Exception as error:cleanup_failure=True;scrub_exception(error)
        stdout=stderr=private_input='';child=None
    summary.update(cleanup_failure=cleanup_failure,child_reaped=reaped)
    # A failed tree cleanup is never reported as a successful owned run.
    if cleanup_failure or not reaped:
        summary.update(exit_code=-1,failure_category='cleanup_failure')
    return summary
