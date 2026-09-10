"""Generate synthetic media and exercise three revisions via real MCP calls."""
from pathlib import Path
import argparse
import asyncio
from datetime import datetime
import json
import os
import subprocess
import sys
import imageio_ffmpeg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='MCP演示_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    # Reuse core's path/name validation for filenames as well.
    sys.path.insert(0, str(ROOT))
    from jianying_local_mcp.core import project_name
    prefix = project_name(args.prefix)
    assets = ROOT / 'examples/generated' / prefix
    assets.mkdir(parents=True, exist_ok=False)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    for name, source in [('blue.mp4','testsrc2=size=1280x720:rate=30:duration=4'),
                         ('teal.mp4','color=c=0x087E8B:size=1280x720:rate=30:duration=4')]:
        subprocess.run([ff,'-nostdin','-v','error','-f','lavfi','-i',source,
                        '-c:v','libx264','-pix_fmt','yuv420p',str(assets/name)],check=True)
    subprocess.run([ff,'-nostdin','-v','error','-f','lavfi','-i',
                    'sine=frequency=440:sample_rate=48000:duration=6','-af','volume=0.2',
                    '-c:a','pcm_s16le',str(assets/'tone.wav')],check=True)
    names = [prefix + suffix for suffix in ('_基础版','_字幕版','_剪辑验证版')]
    plan = {'name':names[0],'width':1280,'height':720,'fps':30,'clips':[
        {'id':'shot_a','kind':'video','track':'画面','path':str(assets/'blue.mp4'),
         'start':0,'duration':3,'source_start':0.5},
        {'id':'shot_b','kind':'video','track':'画面','path':str(assets/'teal.mp4'),'start':3,'duration':3},
        {'id':'music','kind':'audio','track':'配乐','path':str(assets/'tone.wav'),
         'start':0,'duration':6,'volume':0.4}]}
    srt = (ROOT/'examples/demo.srt').read_text(encoding='utf-8')
    (assets/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    params = StdioServerParameters(command=sys.executable,args=['-m','jianying_local_mcp','serve'],
        env={**os.environ,'PYTHONPATH':str(ROOT),
             'JIANYING_MCP_WORKSPACE':os.environ.get('JIANYING_MCP_WORKSPACE',str(ROOT/'projects'))})
    report = []
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            init = await session.initialize()
            report.append({'protocol':init.protocolVersion,'tools':[t.name for t in (await session.list_tools()).tools]})
            calls = [
                ('create_draft',{'plan':plan,'dry_run':True}),
                ('create_draft',{'plan':plan,'dry_run':False}),
                ('add_srt',{'name':names[0],'new_name':names[1],'content':srt,'dry_run':False}),
                ('edit_draft',{'name':names[1],'new_name':names[2],'dry_run':False,'operations':[
                    {'op':'split','id':'shot_a','at':1.5},
                    {'op':'update','id':'music','changes':{'volume':0.25}}]})]
            for tool, arguments in calls:
                result = await session.call_tool(tool,arguments)
                if result.isError:
                    raise RuntimeError(str(result.content))
                report.append({'tool':tool,'result':result.structuredContent or json.loads(result.content[0].text)})
                print(tool, 'OK', flush=True)
    (assets/'mcp-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('已生成：' + names[-1] + '。尚未写入剪映原生草稿库。')

asyncio.run(main())
