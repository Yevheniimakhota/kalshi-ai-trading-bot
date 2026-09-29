
import subprocess, time, sys, datetime
def page_die():
    try:
        import httpx
        sys.path.insert(0, 'scripts')
        import aaa_data
        p = aaa_data.parse_aaa_page(httpx.get(aaa_data.LIVE_URL, timeout=30,
            headers=aaa_data.HEADERS, follow_redirects=True).text)
        return p['cur_die'], p['cur_reg']
    except Exception as e:
        return None, None
# wait until 07:45 UTC
now = datetime.datetime.now(datetime.timezone.utc)
start = now.replace(hour=7, minute=45, second=0, microsecond=0)
if now < start:
    time.sleep((start - now).total_seconds())
for attempt in range(10):
    die, reg = page_die()
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
    print(ts, 'poll:', die, reg, flush=True)
    if die is not None and abs(die - 6.4531) > 1e-9:
        print('NEW PRINT DETECTED - running morning cycle', flush=True)
        subprocess.run(['bash', 'scripts/run_morning.sh'])
        subprocess.run(['git', 'add', '-A', 'data/', 'logs/'])
        subprocess.run(['git', 'commit', '-q', '-m', 'data: morning cycle (9/29 print)'])
        print('MORNING_CYCLE_DONE', flush=True)
        sys.exit(0)
    time.sleep(180)
print('PRINT_NOT_DETECTED_AFTER_10_POLLS', flush=True)
